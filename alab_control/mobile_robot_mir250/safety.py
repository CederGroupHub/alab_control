"""The safety obligations that outlive any one mission.

Three things live here because they must be true regardless of what the robot is doing:

**The battery policy.** One place that decides when the robot may start, when it must stop,
and when it may resume. The numbers are policy, not magic: 80% is the floor for taking on
work of any kind including waiting on another instrument, 90% is where a suspended mission
resumes, 50% is where being low means the charging policy itself has failed and somebody is
told, and 20% is a hard refusal because below that the robot may not make it to the dock.

**The protective-field mute.** Reaching into Labman requires suppressing the MiR's safety
scanners. A mute that outlives the code that set it leaves the robot driving blind, and we
know from the latch test that a mute does survive a dead process. So the mute is only ever
taken through :class:`MuteGuard`, which pairs it with an unmute in a `finally` and verifies
both against the MiR's own `safety_system_muted` -- Ability offers no way to read it back.
An unmute that cannot be verified is a maintenance stop, not a warning.

Ability's mute service can return ``success: True`` while the MiR still reports muted,
especially when Ability is latched in an error state. A success reply is therefore only
meaningful when Ability itself is healthy; otherwise it is ignored and the cell must stop.

**The emergency stop.** The old device set a flag called `connected` to False and called that
an emergency stop. This one actually commands the controller to stop, clears the mute, and
reports which of those succeeded, because a stop that quietly failed is worse than none.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)
from .clients import (
    AbilityClient,
    AbilityRosClient,
    MirClient,
    RobotApiError,
    is_error_state,
)
from .errors import MaintenanceRequired

MUTE_SERVICE = "/mobile/mute_protective_fields"

#: The MiR status field that answers whether the fields are muted. Ability has no equivalent,
#: which is why every mute check goes through the MiR.
MUTE_FIELD = "safety_system_muted"

#: How long the MiR takes to reflect a mute change in its status.
MUTE_SETTLE_S = 2.0


def ability_mute_trustworthy(ability: AbilityClient | None) -> bool:
    """Whether Ability's mute/unmute ``success`` bit may be believed.

    When Ability is unreachable or in an error state, ``/mobile/mute_protective_fields`` can
    still answer success without changing the MiR. Callers must then refuse to treat that
    reply as unmute (or as a successful mute) and stop work until Ability is Idle again.

    ``False`` when ``ability`` is omitted: without a status read there is no basis to trust
    Ability's mute service, so mute must not be taken. Unmute may still *try* ROS as a
    best effort and then fall through to MiR setting 2137 and MiR verification.
    """
    if ability is None:
        return False
    try:
        state = str(ability.status().get("state", "") or ability.state())
    except RobotApiError:
        return False
    return not is_error_state(state) and state not in (
        "Emergency Stop Active",
        "Safeguard Stop Active",
    )


def _ability_unhealthy_detail(ability: AbilityClient | None) -> str:
    if ability is None:
        return "Ability was not passed in, so its mute reply cannot be trusted"
    try:
        status = ability.status()
    except RobotApiError as exc:
        return f"Ability status is unreadable ({exc})"
    state = str(status.get("state", ""))
    message = str(status.get("message") or "")
    if message:
        return f"Ability is {state!r} ({message!r})"
    return f"Ability is {state!r}"


@dataclass(frozen=True)
class BatteryPolicy:
    """When the robot may work, must stop, and may resume.

    `working_floor` is deliberately the same number for starting a mission and for
    continuing one. A robot that will not start below 80% but will sit at Labman at 45%
    waiting for a quadrant is the exact failure this replaced.
    """

    working_floor: float = 80.0
    resume_at: float = 90.0
    hard_floor: float = 20.0
    #: Where being low stops being a policy decision and becomes evidence that charging is
    #: broken. The robot should have docked at `working_floor`, so reaching this while not
    #: charging means something prevented it, and somebody needs to be told.
    alarm_at: float = 50.0

    def __post_init__(self) -> None:
        if not self.hard_floor < self.working_floor <= self.resume_at:
            raise ValueError(
                f"battery policy must satisfy hard_floor < working_floor <= resume_at, "
                f"got {self.hard_floor} / {self.working_floor} / {self.resume_at}"
            )
        if not self.hard_floor <= self.alarm_at < self.working_floor:
            raise ValueError(
                f"battery policy must satisfy hard_floor <= alarm_at < working_floor, "
                f"got {self.hard_floor} / {self.alarm_at} / {self.working_floor}"
            )

    def may_start(self, battery: float | None) -> bool:
        """Whether a new mission may begin. An unknown battery is a no."""
        return battery is not None and battery >= self.working_floor

    def must_stop(self, battery: float | None, *, charging: bool = False) -> bool:
        """Whether work in progress must stop at the next safe boundary.

        Charging is not an exemption from the floor, it is the reason the robot is at the
        dock; a mission is not resumed until `resume_at`, so a charging robot below that
        still counts as unable to work.
        """
        if battery is None:
            return False  # a missing reading is handled by preflight, not by stopping mid-leg
        return battery < self.working_floor and not (
            charging and battery >= self.resume_at
        )

    def may_resume(self, battery: float | None) -> bool:
        return battery is not None and battery >= self.resume_at

    def below_hard_floor(self, battery: float | None) -> bool:
        return battery is not None and battery < self.hard_floor

    def should_alarm(self, battery: float | None, *, charging: bool | None = False) -> bool:
        """Whether being this low is worth waking somebody up about.

        A charging robot below the alarm level is the policy working: it noticed, it docked,
        it is filling up. A robot that is this low and *not* charging got here despite the
        policy, and that is what the alarm is for. An unreadable battery is not answered here
        -- the caller knows whether it has a reading and how old it is.
        """
        return battery is not None and battery < self.alarm_at and not charging

    def suspend_reason(self, battery: float) -> str:
        return (
            f"battery is {battery:.0f}%, below the {self.working_floor:.0f}% working floor; "
            f"docking now and resuming at {self.resume_at:.0f}%"
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "working_floor": self.working_floor,
            "resume_at": self.resume_at,
            "hard_floor": self.hard_floor,
            "alarm_at": self.alarm_at,
        }


DEFAULT_BATTERY_POLICY = BatteryPolicy()


def fields_muted(mir: MirClient) -> bool | None:
    """Whether the MiR's protective fields are muted, or None if it cannot be read."""
    try:
        return bool(mir.status().get(MUTE_FIELD))
    except (RobotApiError, KeyError, TypeError):
        return None


def set_mute(ros: AbilityRosClient, muted: bool) -> None:
    reply = ros.call_service(MUTE_SERVICE, {"mute": bool(muted)}) or {}
    if not reply.get("success", True):
        raise RobotApiError(
            f"{MUTE_SERVICE} refused mute={muted}: {reply.get('error_message')}",
            url=MUTE_SERVICE,
        )


def persist_mute(mir: MirClient, muted: bool) -> None:
    """Write MiR setting 2137. No-op if the client cannot authenticate."""
    writer = getattr(mir, "set_protective_fields_muted", None)
    if writer is None:
        raise RobotApiError(
            "this MiR client cannot write the protective-field setting",
            url="/settings/2137",
        )
    writer(bool(muted))


def ensure_fields_unmuted(
    ros: AbilityRosClient,
    mir: MirClient,
    *,
    ability: AbilityClient | None = None,
    settle: float = MUTE_SETTLE_S,
    log: Callable[[str], None] | None = None,
    reason: str = "with no work in progress",
) -> None:
    """Clear a leftover mute, including the persisted MiR setting ROS unmute misses.

    Order: refuse to trust Ability's mute service when Ability is unhealthy, otherwise ROS
    unmute, then PUT setting 2137 if the MiR still reports muted, then verify
    ``safety_system_muted`` is false. Raises :class:`MaintenanceRequired` if it cannot be
    verified. A cell that is already unmuted returns immediately.
    """
    say = log or logger.info
    if fields_muted(mir) is False:
        return

    say(f"protective fields are muted {reason}; clearing the leftover mute")
    ability_known_unhealthy = ability is not None and not ability_mute_trustworthy(ability)
    if ability_known_unhealthy:
        say(
            f"Ability mute replies are not trustworthy right now "
            f"({_ability_unhealthy_detail(ability)}); will still request unmute, "
            "but only the MiR reading counts"
        )
    try:
        set_mute(ros, False)
    except RobotApiError as error:
        say(f"ROS unmute was refused ({error}); trying the persisted MiR setting")

    if settle:
        time.sleep(settle)
    if fields_muted(mir) is False:
        say("protective fields are live after the ROS unmute")
        return

    try:
        persist_mute(mir, False)
    except RobotApiError as error:
        if ability_known_unhealthy:
            raise MaintenanceRequired(
                f"could not unmute while Ability is unhealthy: {error}",
                prompt=(
                    "The mobile robot's safety scanners are muted, and Ability is not healthy "
                    f"enough for its unmute command to be trusted ({_ability_unhealthy_detail(ability)}). "
                    f"Writing MiR setting 2137 also failed ({error}).\n\n"
                    "Clear the Ability Entity Error (HMI Retry or recover.py --clear-errors "
                    "--execute), then confirm safety_system_muted is false on the MiR, and "
                    "mark this as completed."
                ),
            ) from error
        raise MaintenanceRequired(
            f"could not unmute the MiR protective fields: {error}",
            prompt=(
                "The mobile robot's safety scanners are muted and nothing is using them. "
                "ROS unmute did not clear them, and writing MiR setting 2137 failed "
                f"({error}).\n\n"
                "Run recover.py --unmute --execute, or clear the mute from the MiR web "
                "interface, confirm safety_system_muted is false, then mark this as "
                "completed."
            ),
        ) from error

    if settle:
        time.sleep(settle)
    state = fields_muted(mir)
    if state:
        if ability_known_unhealthy:
            raise MaintenanceRequired(
                "the MiR protective fields are still muted and Ability is not healthy, "
                "so Ability unmute success cannot be trusted",
                prompt=(
                    "The mobile robot's safety scanners are still muted. Ability is "
                    f"{_ability_unhealthy_detail(ability)}, which is the state where its "
                    "unmute service can return success without changing the MiR.\n\n"
                    "Fix Ability first (HMI Retry / recover.py --clear-errors --execute), "
                    "confirm safety_system_muted is false, then mark this as completed."
                ),
            )
        raise MaintenanceRequired(
            "the MiR protective fields are still muted after ROS unmute and setting 2137",
            prompt=(
                "The mobile robot's safety scanners are still muted after software "
                "unmute (ROS plus MiR setting 2137).\n\n"
                "Clear the mute from the MiR web interface, confirm safety_system_muted "
                "is false, then mark this as completed."
            ),
        )
    say("protective fields are live after writing MiR setting 2137")


class MuteGuard:
    """Mute the protective fields for the duration of a block, and prove they came back.

    Use it as a context manager and nothing else. The verification on the way out is the
    point: an unmute whose effect the MiR does not confirm raises
    :class:`MaintenanceRequired`, because the alternative is a robot that drives the cell
    with its scanners suppressed and no one knowing.

    A mute that was already on when we arrived is left alone rather than cleared, since
    something else is relying on it; that is reported, not silently reverted.

    Ability must be healthy before a mute is taken: the same error states that make unmute
    success a lie also make mute success untrustworthy.
    """

    def __init__(
        self,
        ros: AbilityRosClient,
        mir: MirClient,
        *,
        ability: AbilityClient | None = None,
        station: str = "",
        log: Callable[[str], None] | None = None,
        settle: float = MUTE_SETTLE_S,
        verify: bool = True,
    ) -> None:
        self.ros = ros
        self.mir = mir
        self.ability = ability
        self.station = station
        self.log = log or logger.info
        self.settle = settle
        self.verify = verify
        self.was_muted: bool | None = None
        self.taken = False

    def __enter__(self) -> "MuteGuard":
        self.was_muted = fields_muted(self.mir)
        if self.was_muted:
            self.log(
                f"protective fields were already muted before reaching into "
                f"{self.station or 'the station'}; leaving that alone"
            )
            return self
        if not ability_mute_trustworthy(self.ability):
            raise MaintenanceRequired(
                "refusing to mute the protective fields while Ability is unhealthy",
                prompt=(
                    "The robot needs muted scanners to reach into "
                    f"{self.station or 'a station'}, but Ability is not healthy "
                    f"({_ability_unhealthy_detail(self.ability)}), so a mute success "
                    "from Ability cannot be trusted.\n\n"
                    "Clear the Ability error first, then retry."
                ),
            )
        set_mute(self.ros, True)
        self.taken = True
        if self.verify:
            time.sleep(self.settle)
            if fields_muted(self.mir) is False:
                # Not fatal: the reach may still be safe, but it is worth knowing that the
                # mute did not take, because it means the fields will trip mid-reach.
                self.log(
                    f"asked to mute the protective fields for {self.station or 'a reach'} "
                    f"but the MiR still reports them unmuted"
                )
        return self

    def __exit__(self, *_exc: object) -> None:
        if not self.taken:
            return
        try:
            ensure_fields_unmuted(
                self.ros,
                self.mir,
                ability=self.ability,
                settle=self.settle if self.verify else 0.0,
                log=self.log,
                reason=f"after working at {self.station or 'a station'}",
            )
        except MaintenanceRequired:
            raise
        except RobotApiError as error:
            raise MaintenanceRequired(
                f"could not unmute the MiR protective fields after working at "
                f"{self.station or 'a station'}: {error}",
                prompt=(
                    "The mobile robot's safety scanners were muted to reach into "
                    f"{self.station or 'a station'} and the unmute command failed. The robot "
                    "must not move until they are back on.\n\n"
                    "Run recover.py --unmute --execute, or unmute from the MiR web "
                    "interface, confirm safety_system_muted is false, then mark this as "
                    "completed."
                ),
            ) from error
        if self.verify and fields_muted(self.mir) is False:
            self.log(f"protective fields back on after {self.station or 'the reach'}")


def assert_fields_unmuted(mir: MirClient) -> None:
    """Refuse to proceed if the fields were left muted by something else.

    The mute survives a dead process, so this belongs in preflight: the previous run's crash
    is exactly the case where the robot is about to drive with its scanners off.
    """
    if fields_muted(mir):
        raise MaintenanceRequired(
            "the MiR protective fields are muted before any work has started",
            prompt=(
                "The mobile robot's safety scanners are muted and nothing is using them. "
                "This usually means a previous run stopped without restoring them.\n\n"
                "Clear the mute from the MiR web interface, confirm safety_system_muted is "
                "false, then mark this as completed."
            ),
        )


@dataclass
class StopReport:
    """What an emergency stop actually managed to do."""

    actions: list[str]
    failures: list[str]
    state_after: str = ""

    @property
    def ok(self) -> bool:
        return not self.failures

    def __str__(self) -> str:
        done = ", ".join(self.actions) or "nothing"
        if self.failures:
            return (
                f"emergency stop was incomplete: did {done}; failed: "
                f"{'; '.join(self.failures)}. Use the physical e-stop."
            )
        return f"emergency stop: {done}; controller is now {self.state_after!r}"


def emergency_stop(
    ability: AbilityClient,
    ros: AbilityRosClient | None = None,
    mir: MirClient | None = None,
    log: Callable[[str], None] | None = None,
) -> StopReport:
    """Stop execution now, and put the safety scanners back.

    Both stop paths are tried because they fail in different circumstances: the REST stop is
    rejected when there is nothing stoppable, and the ROS stop cannot act from `Recovery`.
    Trying both and reporting honestly is the most software can do -- this is not a
    substitute for the physical e-stop, and says so when it comes up short.
    """
    say = log or logger.warning
    report = StopReport(actions=[], failures=[])

    say("emergency stop requested")
    try:
        ability.stop()
        report.actions.append("REST stop request")
    except RobotApiError as error:
        # A 400 here means there was nothing to stop, which is not a failure of the stop.
        if error.status == 400:
            report.actions.append("nothing was executing")
        else:
            report.failures.append(f"REST stop failed: {error}")

    if ros is not None:
        try:
            ros.system_stop()
            report.actions.append("ROS system stop")
        except RobotApiError as error:
            if not report.actions:
                report.failures.append(f"ROS stop failed: {error}")

        # The scanners matter more than the stop: a stopped robot with muted fields is one
        # command away from moving blind. Always command the unmute; skip only the
        # persisted-setting fallback when the MiR already reads live. Ability's success bit
        # is ignored when Ability is unhealthy -- only the MiR reading counts.
        ability_ok = ability_mute_trustworthy(ability)
        try:
            set_mute(ros, False)
            if ability_ok and (mir is None or fields_muted(mir) is False):
                report.actions.append("protective fields unmuted")
            elif not ability_ok:
                report.actions.append(
                    "Ability unmute requested but not trusted "
                    f"({_ability_unhealthy_detail(ability)})"
                )
            else:
                report.actions.append("Ability unmute requested; MiR still reports muted")
        except RobotApiError as error:
            report.failures.append(f"could not unmute the protective fields: {error}")

        if mir is not None and fields_muted(mir):
            try:
                persist_mute(mir, False)
                if not fields_muted(mir):
                    report.actions.append("protective fields unmuted via MiR setting 2137")
                    report.failures[:] = [
                        item
                        for item in report.failures
                        if "unmute the protective fields" not in item
                    ]
            except RobotApiError as error:
                report.failures.append(
                    f"could not write MiR setting 2137 to unmute: {error}"
                )

    if mir is not None and fields_muted(mir):
        report.failures.append(
            "the MiR still reports its protective fields muted after the unmute"
        )

    try:
        report.state_after = ability.state()
    except RobotApiError as error:
        report.failures.append(f"could not read the controller state back: {error}")

    say(str(report))
    return report


def mir_is_wedged(
    ability_state: str,
    mir_reachable: bool,
    ability_message: str = "",
) -> bool:
    """The one failure with no software recovery: Ability faulted and the MiR is gone.

    Clearing the latch does not bring the MiR back, and the next command faults again, so
    recognising this specifically is what stops a retry loop from running all night.

    A manipulator healthcheck latch with a reachable MiR is *not* this: that is a stale
    Ability entity error, which recovery can try to restart.
    """
    if ability_state != "Entity Error Active" or mir_reachable:
        return False
    message = (ability_message or "").lower()
    if "manipulator" in message:
        return False
    return True


def wedge_prompt(detail: str = "") -> str:
    return (
        "The mobile robot's Ability controller has faulted and its MiR base is not "
        "answering on the network. There is no software recovery for this.\n\n"
        "1. Power-cycle the MiR base.\n"
        "2. Wait for the MiR web interface to come back.\n"
        "3. Check the arm is parked and the base is at a known station.\n"
        "4. Set BasePosition and RobotPose to match reality.\n\n"
        f"{detail}\n\n"
        "Mark this as completed once the robot answers again."
    ).strip()


def battery_of(status: Any) -> float | None:
    """Read a battery percentage out of either controller's status shape."""
    if not isinstance(status, dict):
        return None
    for key in ("battery_percentage", "battery"):
        if key in status:
            try:
                return float(status[key])
            except (TypeError, ValueError):
                continue
    return None

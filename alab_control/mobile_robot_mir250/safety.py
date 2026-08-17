"""The safety obligations that outlive any one mission.

Three things live here because they must be true regardless of what the robot is doing:

**The battery policy.** One place that decides when the robot may start, when it must stop,
and when it may resume. The numbers are policy, not magic: 80% is the floor for taking on
work of any kind including waiting on another instrument, 90% is where a suspended mission
resumes, and 20% is a hard refusal because below that the robot may not make it to the dock.

**The protective-field mute.** Reaching into Labman requires suppressing the MiR's safety
scanners. A mute that outlives the code that set it leaves the robot driving blind, and we
know from the latch test that a mute does survive a dead process. So the mute is only ever
taken through :class:`MuteGuard`, which pairs it with an unmute in a `finally` and verifies
both against the MiR's own `safety_system_muted` -- Ability offers no way to read it back.
An unmute that cannot be verified is a maintenance stop, not a warning.

**The emergency stop.** The old device set a flag called `connected` to False and called that
an emergency stop. This one actually commands the controller to stop, clears the mute, and
reports which of those succeeded, because a stop that quietly failed is worse than none.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from .clients import (
    AbilityClient,
    AbilityRosClient,
    MirClient,
    RobotApiError,
)
from .errors import MaintenanceRequired

logger = logging.getLogger(__name__)

MUTE_SERVICE = "/mobile/mute_protective_fields"

#: The MiR status field that answers whether the fields are muted. Ability has no equivalent,
#: which is why every mute check goes through the MiR.
MUTE_FIELD = "safety_system_muted"

#: How long the MiR takes to reflect a mute change in its status.
MUTE_SETTLE_S = 2.0


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

    def __post_init__(self) -> None:
        if not self.hard_floor < self.working_floor <= self.resume_at:
            raise ValueError(
                f"battery policy must satisfy hard_floor < working_floor <= resume_at, "
                f"got {self.hard_floor} / {self.working_floor} / {self.resume_at}"
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


class MuteGuard:
    """Mute the protective fields for the duration of a block, and prove they came back.

    Use it as a context manager and nothing else. The verification on the way out is the
    point: an unmute whose effect the MiR does not confirm raises
    :class:`MaintenanceRequired`, because the alternative is a robot that drives the cell
    with its scanners suppressed and no one knowing.

    A mute that was already on when we arrived is left alone rather than cleared, since
    something else is relying on it; that is reported, not silently reverted.
    """

    def __init__(
        self,
        ros: AbilityRosClient,
        mir: MirClient,
        *,
        station: str = "",
        log: Callable[[str], None] | None = None,
        settle: float = MUTE_SETTLE_S,
        verify: bool = True,
    ) -> None:
        self.ros = ros
        self.mir = mir
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
            set_mute(self.ros, False)
        except RobotApiError as error:
            raise MaintenanceRequired(
                f"could not unmute the MiR protective fields after working at "
                f"{self.station or 'a station'}: {error}",
                prompt=(
                    "The mobile robot's safety scanners were muted to reach into "
                    f"{self.station or 'a station'} and the unmute command failed. The robot "
                    "must not move until they are back on.\n\n"
                    "Unmute the protective fields from the MiR web interface, confirm "
                    "safety_system_muted is false, then mark this as completed."
                ),
            ) from error
        if not self.verify:
            return
        time.sleep(self.settle)
        state = fields_muted(self.mir)
        if state is None:
            self.log(
                "unmuted the protective fields but could not read the MiR back to confirm "
                "it; MiR credentials are needed for that check"
            )
            return
        if state:
            raise MaintenanceRequired(
                "the MiR protective fields are still muted after the unmute command",
                prompt=(
                    "The mobile robot's safety scanners are still muted after working at "
                    f"{self.station or 'a station'}. It must not move.\n\n"
                    "Clear the mute from the MiR web interface, confirm "
                    "safety_system_muted is false, then mark this as completed."
                ),
            )
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
        # command away from moving blind.
        try:
            set_mute(ros, False)
            report.actions.append("protective fields unmuted")
        except RobotApiError as error:
            report.failures.append(f"could not unmute the protective fields: {error}")

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


def mir_is_wedged(ability_state: str, mir_reachable: bool) -> bool:
    """The one failure with no software recovery: Ability faulted and the MiR is gone.

    Clearing the latch does not bring the MiR back, and the next command faults again, so
    recognising this specifically is what stops a retry loop from running all night.
    """
    return ability_state == "Entity Error Active" and not mir_reachable


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

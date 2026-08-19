"""The gate that runs before any commanded motion, and refuses to move otherwise.

Every check here exists because of something that went wrong on the real cell. The
expensive failure mode is not a refusal to move -- it is moving on a belief that is no
longer true, because ``Main`` picks its retreat path from a persisted variable and will
happily drive out of a station the robot is not in.

The checks, in the order they run and roughly in order of how cheap they are:

1. ``Main`` is on the controller at all.
2. The Ability state is ``Idle``, not merely ``Ready``. A load during teardown is rejected
   with "State machine couldn't process event: ActivateProgramming".
3. ``Recovery`` is a stranded programming token and is cleared with
   ``force_token_release``, never with ``stop()``: REST rejects every state request from
   ``Recovery`` and ``/er/system/stop`` cannot process a Stop there.
4. A latched error is cleared with a stop request. ``Entity Error Active`` alongside a MiR
   that cannot be reached is the one case with no software recovery -- the MiR API wedge --
   and raises :class:`MaintenanceRequired` instead of being retried.
5. The MiR key switch is in ``auto`` and it reports no errors.
6. A MiR ``Pause`` is only a problem when it still names a mission. Ability parks the base
   in ``Pause`` after every drive block and resumes it itself, so refusing all pauses
   blocks work for no reason.
7. The protective fields are not muted. A mute outlives the process that set it, so one
   found here was left behind by a run that died. Preflight clears it (ROS unmute, then
   MiR setting 2137) and only fails if the MiR still reports muted afterwards.
8. ``RobotPose`` is ``Home``. There is no safe-home interlock on this cell, so this
   variable plus recorded-pose agreement is the only gate on the arm being parked.
9. ``BasePosition`` agrees with a pose recorded at that station, cross-checked between two
   independent pose sources. A mismatch aborts rather than moves.
10. The battery is above the floor for the work about to be done.

Nothing here commands motion. Side effects are the documented recoveries: releasing a
stranded token, clearing a latched execution error, and unmuting leftover protective
fields. Restarting an Ability docker module to clear a stale entity error is
:func:`recovery.recover_cell`, not this gate.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .clients import (
    IDLE_STATES,
    STATE_IDLE,
    STATE_RECOVERY,
    AbilityClient,
    AbilityRosClient,
    MirClient,
    RobotApiError,
    is_error_state,
    mir_pause_reason,
)
from .errors import MaintenanceRequired, PreflightFailed
from .poses import StationPoses, pose_sources_disagree
from .safety import (
    DEFAULT_BATTERY_POLICY,
    MUTE_FIELD,
    MUTE_SETTLE_S,
    ensure_fields_unmuted,
    mir_is_wedged,
    wedge_prompt,
)

logger = logging.getLogger(__name__)

#: The arm posture ``Main`` records once the manipulator is parked.
ARM_PARKED_POSE = "Home"

#: ``BasePosition`` while a base move is in flight or was interrupted. Not a station, and
#: not something to reconcile against a pose -- it means the robot's location is unknown.
BASE_POSITION_UNKNOWN = "Unknown"

#: How long to wait after clearing a latch or releasing a token before re-reading state.
CLEAR_SETTLE_S = 3.0

#: There is no useful work below this. Enforced as a refusal, not a warning: the old system
#: had a 20% cutout as a comment and nothing else. Kept as an alias so there is one number.
HARD_BATTERY_FLOOR = DEFAULT_BATTERY_POLICY.hard_floor


@dataclass
class Check:
    """One preflight condition and what was observed."""

    name: str
    ok: bool
    detail: str = ""
    #: Set when the only fix is a person, so the caller raises a maintenance prompt rather
    #: than treating this as a transient failure to retry.
    needs_maintenance: bool = False

    def __str__(self) -> str:
        return f"{'ok' if self.ok else 'FAILED'} {self.name}: {self.detail}"


@dataclass
class PreflightReport:
    """The outcome of a preflight, and the facts it gathered on the way.

    The facts are worth keeping: ``base_position``, ``battery`` and the two poses are
    exactly what a caller needs next, and re-reading them would be both slower and a
    chance for them to have changed.
    """

    checks: list[Check] = field(default_factory=list)
    base_position: str = ""
    robot_pose: str = ""
    battery: float | None = None
    ability_state: str = ""
    ability_pose: Any = None
    mir_status: dict[str, Any] = field(default_factory=dict)
    is_charging: bool | None = None
    fields_muted: bool | None = None
    #: The MiR communication wedge. Set so a caller can put up the right prompt without
    #: pattern-matching on check names.
    wedged: bool = False

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if not check.ok]

    @property
    def needs_maintenance(self) -> bool:
        return any(check.needs_maintenance for check in self.failures)

    def summary(self) -> str:
        if self.ok:
            return (
                f"preflight passed: BasePosition={self.base_position!r} "
                f"RobotPose={self.robot_pose!r} battery={self.battery}%"
            )
        return "preflight failed: " + "; ".join(
            f"{check.name} -- {check.detail}" for check in self.failures
        )

    def raise_if_failed(self) -> "PreflightReport":
        """Raise the right kind of error, or return self so this can be chained."""
        if self.ok:
            return self
        if self.needs_maintenance:
            raise MaintenanceRequired(self.summary(), prompt=self._maintenance_prompt())
        raise PreflightFailed(self.summary())

    def _maintenance_prompt(self) -> str:
        problems = "\n".join(
            f"- {check.detail}" for check in self.failures if check.needs_maintenance
        )
        if self.wedged:
            return wedge_prompt(problems)
        return (
            "The mobile robot cannot be used until someone checks it.\n"
            f"{problems}\n\n"
            "Nothing has moved. Once the cell is right, mark this as completed."
        )


def preflight(
    ability: AbilityClient,
    ros: AbilityRosClient,
    mir: MirClient,
    *,
    poses: StationPoses | None = None,
    minimum_battery: float = HARD_BATTERY_FLOOR,
    expect_base_position: str | None = None,
    require_arm_parked: bool = True,
    clear_recovery: bool = True,
    clear_latched_error: bool = True,
    unmute_leftover_fields: bool = True,
    unmute_settle: float = MUTE_SETTLE_S,
    log: Callable[[str], None] | None = None,
) -> PreflightReport:
    """Gather every safety precondition. Returns a report; never raises on a failed check.

    Only transport failures propagate, since being unable to reach the controller is not a
    verdict about the cell.

    Args:
        poses: recorded pose truth for the ``BasePosition`` reconciliation. Skipped when
            omitted, which is only right for a caller that has already reconciled.
        minimum_battery: the floor for the work about to be done. Never below
            :data:`HARD_BATTERY_FLOOR`.
        expect_base_position: fail unless ``Main`` believes it is parked here. Use it when
            a caller's plan depends on the starting station.
        require_arm_parked: whether ``RobotPose`` must be ``Home``. Only a caller that is
            about to park the arm itself should turn this off.
    """
    say = log or logger.info
    report = PreflightReport()
    add = report.checks.append
    floor = max(minimum_battery, HARD_BATTERY_FLOOR)

    # -- Ability: is there a program, and will the controller accept one? ---
    status = ability.status()
    state = str(status.get("state", ""))
    report.ability_state = state
    say(f"preflight: Ability state={state!r} message={status.get('message')!r}")

    programs = ability.programs()
    add(
        Check(
            "main_program_present",
            "Main" in programs,
            f"programs on the controller: {programs}",
        )
    )

    if state == STATE_RECOVERY and clear_recovery:
        # A programming token left stranded by an editor session or a crashed process.
        # stop() cannot clear this, and trying it wastes the one chance to say why.
        say("Ability is in Recovery (a stranded programming token); releasing it")
        try:
            ros.force_token_release()
        except RobotApiError as exc:
            add(
                Check(
                    "recovery_cleared",
                    False,
                    f"could not release the stranded programming token: {exc}",
                    needs_maintenance=True,
                )
            )
        else:
            time.sleep(CLEAR_SETTLE_S)
            status = ability.status()
            state = str(status.get("state", ""))
            report.ability_state = state
            add(
                Check(
                    "recovery_cleared",
                    state != STATE_RECOVERY,
                    f"state after releasing the token: {state!r}",
                )
            )

    mir_reachable = True
    try:
        mir_status = mir.status()
    except RobotApiError as exc:
        mir_reachable = False
        mir_status = {}
        add(
            Check(
                "mir_reachable",
                False,
                f"the MiR REST API did not answer: {exc}",
                needs_maintenance=state == "Entity Error Active",
            )
        )
    report.mir_status = mir_status

    if is_error_state(state):
        # Entity Error Active together with an unreachable MiR is the API wedge. There is
        # no software recovery for it: clearing the latch does not restore the MiR, and
        # the next command faults again.
        if mir_is_wedged(state, mir_reachable, str(status.get("message") or "")):
            add(
                Check(
                    "ability_error_cleared",
                    False,
                    "Ability reports 'Entity Error Active' and the MiR API is not "
                    "answering. This is the MiR communication wedge, which has no "
                    "software recovery: power-cycle the MiR and re-home the robot",
                    needs_maintenance=True,
                )
            )
            report.wedged = True
        elif clear_latched_error:
            say(f"Ability has a latched error ({state}); clearing it with a stop request")
            try:
                ability.stop()
            except RobotApiError as exc:
                say(f"the REST stop was rejected ({exc.status}); trying the ROS stop")
                try:
                    ros.system_stop()
                except RobotApiError as ros_exc:
                    add(
                        Check(
                            "ability_error_cleared",
                            False,
                            f"neither stop path cleared {state!r}: {ros_exc}",
                            needs_maintenance=True,
                        )
                    )
            time.sleep(CLEAR_SETTLE_S)
            status = ability.status()
            state = str(status.get("state", ""))
            report.ability_state = state
            add(
                Check(
                    "ability_error_cleared",
                    not is_error_state(state),
                    f"state after the stop request: {state!r} "
                    f"message={status.get('message')!r}",
                )
            )
        else:
            add(Check("ability_error_cleared", False, f"controller is {state!r}"))

    # Idle rather than merely in IDLE_STATES: Ready is a real state, but a program load
    # during the Ready-to-Idle teardown window is rejected.
    if state in IDLE_STATES and state != STATE_IDLE:
        try:
            state = ability.wait_until_loadable()
            report.ability_state = state
        except RobotApiError as exc:
            add(Check("ability_idle", False, str(exc)))
    add(
        Check(
            "ability_idle",
            state == STATE_IDLE or state == "No Program",
            f"controller is {state!r}; a program can only be loaded from Idle",
        )
    )

    # -- MiR: automatic mode, no errors, no harmful pause ------------------
    if mir_reachable:
        mode_key = mir_status.get("mode_key_state")
        add(
            Check(
                "mir_automatic_mode",
                mode_key == "auto",
                f"MiR mode key is {mode_key!r}; turn the key switch to automatic",
            )
        )
        errors = mir_status.get("errors") or []
        add(
            Check(
                "mir_no_errors",
                not errors,
                f"MiR is reporting errors: {errors}" if errors else "no MiR errors",
            )
        )
        pause_problem = mir_pause_reason(mir_status)
        add(
            Check(
                "mir_pause_harmless",
                not pause_problem,
                pause_problem
                or f"MiR state_text={mir_status.get('state_text')!r} is fine to work from",
            )
        )
        # A mute survives the process that set it, so a mute we find here was left behind by
        # something that died. Clear it before refusing; fail only if it will not go.
        muted = mir_status.get(MUTE_FIELD)
        if muted and unmute_leftover_fields:
            try:
                ensure_fields_unmuted(
                    ros, mir, settle=unmute_settle, log=say
                )
                mir_status = mir.status()
                report.mir_status = mir_status
                muted = mir_status.get(MUTE_FIELD)
                add(
                    Check(
                        "protective_fields_live",
                        not muted,
                        "cleared a leftover mute; the MiR protective fields are active"
                        if not muted
                        else (
                            "the MiR protective fields are still muted after ROS unmute "
                            "and MiR setting 2137"
                        ),
                        needs_maintenance=bool(muted),
                    )
                )
            except MaintenanceRequired as exc:
                add(
                    Check(
                        "protective_fields_live",
                        False,
                        str(exc),
                        needs_maintenance=True,
                    )
                )
                muted = True
        else:
            add(
                Check(
                    "protective_fields_live",
                    not muted,
                    "the MiR protective fields are muted and no work is in progress, so a "
                    "previous run left them suppressed. Run recover.py --unmute --execute "
                    "before the robot moves"
                    if muted
                    else "the MiR protective fields are active",
                    needs_maintenance=bool(muted),
                )
            )
        report.fields_muted = bool(muted) if muted is not None else None
        report.battery = _as_float(mir_status.get("battery_percentage"))

    # -- battery ----------------------------------------------------------
    if report.battery is None:
        # The Ability status carries a battery reading too, and it needs no MiR at all.
        report.battery = _as_float(status.get("battery"))
    if report.battery is None:
        add(
            Check(
                "battery_above_floor",
                False,
                "neither the MiR nor Ability reported a battery percentage, so the "
                "battery policy cannot be enforced",
            )
        )
    else:
        add(
            Check(
                "battery_above_floor",
                report.battery >= floor,
                f"battery is {report.battery:.1f}%, floor for this work is {floor:.0f}%",
            )
        )

    # -- what the program believes, and whether reality agrees ------------
    try:
        report.base_position = ros.base_position()
        report.robot_pose = ros.robot_pose()
        report.is_charging = ros.is_charging()
    except RobotApiError as exc:
        add(
            Check(
                "base_position_readable",
                False,
                f"could not read Main's persisted state over ROS: {exc}",
            )
        )
        return report
    say(
        f"preflight: BasePosition={report.base_position!r} RobotPose={report.robot_pose!r} "
        f"is_charging={report.is_charging}"
    )

    if require_arm_parked:
        parked = report.robot_pose == ARM_PARKED_POSE
        add(
            Check(
                "arm_parked",
                parked,
                f"RobotPose is {ARM_PARKED_POSE!r}, so the arm is parked"
                if parked
                else f"RobotPose is {report.robot_pose!r}, not {ARM_PARKED_POSE!r}. The arm "
                "is not parked, and there is no safe-home interlock on this cell to fall "
                "back on, so no base move may be commanded",
            )
        )

    if expect_base_position is not None:
        as_expected = report.base_position == expect_base_position
        add(
            Check(
                "base_position_expected",
                as_expected,
                f"Main believes the base is at {expect_base_position!r}, as expected"
                if as_expected
                else f"Main believes the base is at {report.base_position!r}, not "
                f"{expect_base_position!r}. BaseHandler picks its retreat path from this "
                "variable, so continuing would drive the wrong path out of a station the "
                "robot is not in",
            )
        )

    add(
        Check(
            "base_position_known",
            report.base_position != BASE_POSITION_UNKNOWN,
            f"BasePosition is {BASE_POSITION_UNKNOWN!r}, which means a base move was "
            "interrupted and the robot's station is genuinely not known. Drive it to a "
            "station by hand, or run a Home move under supervision"
            if report.base_position == BASE_POSITION_UNKNOWN
            else f"BasePosition is {report.base_position!r}",
        )
    )

    try:
        report.ability_pose = ability.transform()
    except RobotApiError as exc:
        add(Check("pose_readable", False, f"could not read the arm base pose: {exc}"))
        return report

    if mir_reachable:
        mir_position = mir_status.get("position") or {}
        disagreement = pose_sources_disagree(
            report.ability_pose,
            _as_float(mir_position.get("x"), default=float("nan")),
            _as_float(mir_position.get("y"), default=float("nan")),
            _as_float(mir_position.get("orientation"), default=float("nan")),
        )
        add(
            Check(
                "pose_sources_agree",
                not disagreement,
                disagreement or "the Ability and MiR pose sources agree",
            )
        )

    if poses is not None and report.base_position not in ("", BASE_POSITION_UNKNOWN):
        mismatch = poses.check(report.base_position, report.ability_pose)
        add(
            Check(
                "base_position_matches_recorded_pose",
                not mismatch,
                mismatch
                or f"the robot is where {report.base_position!r} was recorded",
            )
        )

    return report


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

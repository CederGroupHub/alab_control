"""`MiR250MobileManipulator`: everything above, composed into one object.

This is the whole driver as an AlabOS device sees it. It owns the three clients, the
registry, the recorded poses and the mission engine, and it is where the safety obligations
that span a mission are actually discharged:

- preflight before any mission, and again before resuming a suspended one
- retries on an approach or a calibration, capped, because an uncapped retry against a
  station whose marker is obscured runs all night and then fails anyway
- the protective-field mute paired with an unmute around every reach into a station that
  needs one, verified against the MiR
- `settle_on_charge` after every dock, because Ability's teardown aborts the docking mission
  up to half a minute after the program ends and the robot silently stops charging
- the recorded pose updated whenever the robot arrives somewhere under its own power, so the
  reconciliation has something current to check against

Nothing here knows what a crucible is. Missions arrive built.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterator

from .clients import (
    ABILITY_HOST,
    MIR_HOST,
    AbilityClient,
    AbilityRosClient,
    MirClient,
    Pose,
    RobotApiError,
    load_env,
    mir_client_from_env,
    settle_on_charge,
)
from .engine import (
    MissionEngine,
    MissionEvent,
    MissionResult,
    Reason,
    interrupted_status,
)
from .errors import (
    CollisionStop,
    LegFailed,
    MaintenanceRequired,
    MissionInterrupted,
    MobileRobotError,
    ObstructionDetected,
    ObstructionHold,
    PreflightFailed,
)
from .hold import ObstructionHoldRecord
from .hold import clear as clear_hold
from .hold import load as load_hold
from .hold import save as save_hold
from .mission import Leg, LegKind, Mission, dock, travel
from .obstruction import Obstruction, ObstructionWatch, hard_stop, stop_base
from .poses import StationPoses, pose_dict
from .preflight import PreflightReport, preflight
from .registry import Registry, registry as load_station_registry
from .safety import (
    DEFAULT_BATTERY_POLICY,
    MUTE_SETTLE_S,
    BatteryPolicy,
    MuteGuard,
    StopReport,
    emergency_stop,
    ensure_fields_unmuted,
    fields_muted,
)

logger = logging.getLogger(__name__)

#: The station a recovery always drives to first. Everything is reachable from here.
PARKING_STATION = "Home"

#: Docking without waiting for the battery, so Python decides when to resume rather than
#: blocking inside an Ability block for an hour.
CHARGER_NO_WAIT = "ChargingNoWait"
CHARGER_WAIT = "Charging"

#: Messages Ability puts in its status that we know how to react to. Matching on prose is
#: unpleasant but it is the only signal the controller gives, and each of these was seen on
#: the real cell.
BLOCKED_PATH = "The Move action timed out after being blocked"
CALIBRATION_FAILED = "Failed to Calibrate Tag"
MANIPULATOR_NOT_READY = "Manipulator is not ready"
ARM_HOMED = "arm is homed"

#: What the obstruction watchdog puts at the front of its message. Matched rather than
#: type-checked in `classify_failure` because that function is also handed plain strings from
#: logs and tests, and it must classify those the same way.
OBSTRUCTION_STOPPED = "stopped for an obstruction"

#: The same, for the stop that latches. Never classified as a retryable failure: a
#: `CollisionStop` is a `MissionInterrupted`, so it goes straight past the retry policy.
COLLISION_STOPPED = "emergency-stopped for a collision"


def classify_failure(message: str) -> str:
    """Name a leg failure so the retry policy can decide what to do about it.

    - `obstruction`: the watchdog stopped a drive that was getting nowhere. Retried by
      re-approaching, and put on hold for a person if that does not work.
    - `blocked`: Ability's own move timed out. Retrying after a pause often works.
    - `calibration`: the station marker was not seen. Retrying from Home re-approaches, which
      is what usually fixes it.
    - `transient`: the manipulator was not ready. Short retries, no re-approach.
    - `obstacle`: the arm hit something. A person has to look, so no retry.
    - `unknown`: everything else, treated as an obstacle because guessing is worse.
    """
    if OBSTRUCTION_STOPPED in message:
        return "obstruction"
    if BLOCKED_PATH in message:
        return "blocked"
    if CALIBRATION_FAILED in message:
        return "calibration"
    if MANIPULATOR_NOT_READY in message:
        return "transient"
    if ARM_HOMED in message:
        return "obstacle"
    return "unknown"


class MiR250MobileManipulator:
    """Python control of the MiR250 + UR5e cell.

    Thread safety: `run_mission` and the recovery paths take a single lock, so a battery
    guard thread and a task thread cannot command motion at the same time. The read-only
    accessors do not take it, because a dashboard poll must never be able to block the robot.
    """

    def __init__(
        self,
        ability_host: str = ABILITY_HOST,
        mir_host: str = MIR_HOST,
        *,
        registry: Registry | None = None,
        poses: StationPoses | None = None,
        battery_policy: BatteryPolicy = DEFAULT_BATTERY_POLICY,
        log: Callable[[str], None] | None = None,
        env_file: str | None = None,
        hold_path: Any = None,
        ability: Any = None,
        ros: Any = None,
        mir: Any = None,
    ) -> None:
        """The three clients can be supplied rather than built, which is how the test double
        replaces the cell without reimplementing any of the logic above it."""
        self.log = log or logger.info
        self.registry = registry or load_station_registry()
        self.poses = poses or StationPoses()
        self.battery_policy = battery_policy

        if ability is None or ros is None or mir is None:
            load_env(env_file)
        self.ability = ability if ability is not None else AbilityClient(ability_host)
        self.ros = ros if ros is not None else AbilityRosClient(ability_host)
        if mir is not None:
            self.mir = mir
        else:
            try:
                self.mir = mir_client_from_env(host=mir_host)
            except Exception:  # noqa: BLE001 - credentials are optional, most reads work
                self.mir = MirClient(mir_host)
        # Legs go through the retrying, field-muting runner below rather than the engine's
        # bare Main invocation. The engine keeps ordering and interruption; this keeps safety.
        self.engine = MissionEngine(
            self.ability, log=self.log, leg_runner=self.run_leg_with_retries
        )
        #: How long to let the MiR reflect a mute change before reading it back. Only a test
        #: has any business changing this.
        self.mute_settle = MUTE_SETTLE_S
        #: Where an obstruction hold is written. Overridden so a test, or an imaginary
        #: robot, cannot write to the record the real one is resumed from.
        self.hold_path = hold_path
        #: The clock the obstruction watch measures its grace periods against. Replaced by
        #: the test double, which has no interest in waiting twenty real seconds.
        self.clock: Callable[[], float] = time.monotonic

        self._lock = threading.RLock()
        #: The mission in flight, and how far it got. Read by the dashboard.
        self.mission: Mission | None = None
        self.legs_completed = 0
        self.mission_status = "idle"
        self.mission_detail = ""
        self.last_event: MissionEvent | None = None
        self.last_result: MissionResult | None = None
        self._event_listeners: list[Callable[[MissionEvent], None]] = []

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self.ability.close()
        self.mir.close()

    def subscribe(self, listener: Callable[[MissionEvent], None]) -> None:
        """Register a mission event listener. The device uses this to publish to the UI."""
        self._event_listeners.append(listener)

    # -- reads, all safe to call from a dashboard poll ---------------------

    def battery(self) -> float | None:
        """Charge percentage, from the MiR if it answers and Ability otherwise."""
        try:
            return self.mir.battery_percentage()
        except RobotApiError:
            pass
        try:
            value = self.ability.status().get("battery")
            return float(value) if value is not None else None
        except (RobotApiError, TypeError, ValueError):
            return None

    def is_charging(self) -> bool | None:
        try:
            return self.ros.is_charging()
        except RobotApiError:
            return None

    def base_position(self) -> str:
        """The station `Main` believes it is parked at."""
        try:
            return self.ros.base_position()
        except RobotApiError:
            return ""

    def robot_pose(self) -> str:
        try:
            return self.ros.robot_pose()
        except RobotApiError:
            return ""

    def pose(self) -> Pose | None:
        """Where the base actually is on the map."""
        try:
            return self.ability.transform()
        except RobotApiError:
            return None

    def state(self) -> str:
        try:
            return self.ability.state()
        except RobotApiError:
            return ""

    def is_running(self) -> bool:
        return self.mission_status in ("running", "suspending", "cancelling")

    def fields_are_muted(self) -> bool | None:
        return fields_muted(self.mir)

    def snapshot(self) -> dict[str, Any]:
        """Everything the dashboard needs, in one call.

        Deliberately tolerant: a robot that is switched off should render as a robot that is
        switched off, not as a 500 from the API.
        """
        pose = self.pose()
        battery = self.battery()
        base_prefix = self._base_prefix()
        mission = self.mission
        return {
            "state": self.state(),
            "base_position": self.base_position(),
            "robot_pose": self.robot_pose(),
            "pose": pose_dict(pose) if pose else None,
            "battery": battery,
            "battery_policy": self.battery_policy.to_dict(),
            "is_charging": self.is_charging(),
            "fields_muted": self.fields_are_muted(),
            "mission": mission.to_dict(
                legs_completed=self.legs_completed,
                status=self.mission_status,
                base_prefix=base_prefix,
                detail=self.mission_detail,
            )
            if mission
            else None,
            "carried": mission.carried_after(self.legs_completed, base_prefix)
            if mission and base_prefix
            else {},
            "last_event": self.last_event.to_dict() if self.last_event else None,
            # An uncleared hold is the one piece of driver state a dashboard has to be able
            # to show while nothing is running, because nothing *will* run until someone
            # goes and looks at the coordinates in it.
            "hold": hold.to_dict() if (hold := self.hold()) else None,
            "stations": {
                name: {
                    "kind": station.kind,
                    "description": station.description,
                    # The recorded record carries x, y, yaw_deg plus when and why it was
                    # taken, which is exactly what the floor plan draws and what a person
                    # needs to judge whether a marker is stale.
                    "recorded_pose": self.poses.known(name),
                }
                for name, station in self.registry.stations.items()
            },
        }

    def _base_prefix(self) -> str:
        base = self.registry.base_region()
        return base.resources[0] if base and base.resources else ""

    # -- preflight ---------------------------------------------------------

    def preflight(
        self,
        *,
        minimum_battery: float | None = None,
        expect_base_position: str | None = None,
        require_arm_parked: bool = True,
    ) -> PreflightReport:
        """Run the safety gate. Returns the report; does not raise on a failed check."""
        floor = (
            self.battery_policy.working_floor
            if minimum_battery is None
            else minimum_battery
        )
        return preflight(
            self.ability,
            self.ros,
            self.mir,
            poses=self.poses,
            minimum_battery=floor,
            expect_base_position=expect_base_position,
            require_arm_parked=require_arm_parked,
            unmute_settle=self.mute_settle,
            log=self.log,
        )

    # -- missions ----------------------------------------------------------

    def run_mission(
        self,
        mission: Mission,
        *,
        should_cancel: Reason | None = None,
        should_suspend: Reason | None = None,
        before_leg: Callable[[Leg], None] | None = None,
        on_event: Callable[[MissionEvent], None] | None = None,
        start_at: int = 0,
        skip_preflight: bool = False,
    ) -> MissionResult:
        """Run a mission under the full safety discipline.

        Raises `MissionCancelled` or `BatterySuspend` at a leg boundary, `MaintenanceRequired`
        when a person is needed, and `LegFailed` when a leg could not be completed after its
        retries. The caller decides what to do next; the robot is left parked either way.
        """
        with self._lock:
            self.mission = mission
            self.legs_completed = start_at
            self.mission_status = "running"
            self.mission_detail = ""

            if not skip_preflight:
                report = self.preflight(
                    minimum_battery=(
                        self.battery_policy.working_floor
                        if start_at == 0
                        else self.battery_policy.hard_floor
                    )
                )
                self.log(report.summary())
                report.raise_if_failed()

            try:
                result = self.engine.run(
                    mission,
                    on_event=self._on_event(on_event),
                    should_cancel=should_cancel,
                    should_suspend=should_suspend,
                    before_leg=before_leg,
                    start_at=start_at,
                )
            except MissionInterrupted as interruption:
                partial = interruption.result
                self.legs_completed = getattr(partial, "legs_completed", self.legs_completed)
                self.mission_status = getattr(
                    partial, "status", interrupted_status(interruption)
                )
                self.mission_detail = str(interruption)
                self.last_result = partial if isinstance(partial, MissionResult) else None
                raise
            except MobileRobotError as failure:
                self.mission_status = "failed"
                self.mission_detail = str(failure)
                raise

            self.legs_completed = result.legs_completed
            self.mission_status = "completed"
            self.last_result = result
            return result

    def _on_event(
        self, extra: Callable[[MissionEvent], None] | None
    ) -> Callable[[MissionEvent], None]:
        def handle(event: MissionEvent) -> None:
            self.last_event = event
            if event.kind == "leg_finished":
                self.legs_completed = event.leg_index + 1
                if event.leg is not None:
                    self._after_leg(event.leg)
            for listener in list(self._event_listeners):
                try:
                    listener(event)
                except Exception:  # noqa: BLE001
                    logger.exception("mission event listener failed")
            if extra is not None:
                extra(event)

        return handle

    def _after_leg(self, leg: Leg) -> None:
        """The obligations that fall due the moment a leg finishes."""
        if not leg.moves_the_base:
            return
        if leg.kind is LegKind.DOCK:
            self._confirm_charging(leg.station)
            return
        # The robot arrived somewhere under its own power, so this is the one moment its true
        # pose at that station is known. Recording it is what keeps the reconciliation useful
        # after a station is nudged or re-taught.
        self._record_arrival(leg.station)

    def _record_arrival(self, station: str) -> None:
        pose = self.pose()
        if pose is None:
            return
        mismatch = self.poses.check(station, pose)
        if not mismatch:
            return
        if station not in self.poses.stations:
            self.log(f"recording the pose of {station!r} for the first time: {pose}")
            self.poses.record(station, pose, evidence="arrived under Main's own approach")
            return
        # A station that has moved is worth saying out loud rather than silently re-recording:
        # the pose is the safety check, and quietly following it would defeat it.
        self.log(
            f"arrived at {station!r} but {mismatch}. Leaving the recorded pose alone; "
            f"re-record it deliberately if the station really moved."
        )

    def _confirm_charging(self, station: str) -> None:
        """Make sure the dock actually took, and redock if Ability's teardown aborted it."""
        guid = self.registry.station(station).mir_charging_station_guid or ""
        try:
            settled = settle_on_charge(
                self.ros, self.mir, self.log, charging_station_guid=guid
            )
        except RobotApiError as error:
            self.log(f"could not confirm charging after docking: {error}")
            return
        if settled:
            self.log("charging confirmed and holding")
            return
        raise MaintenanceRequired(
            "the robot docked but is not charging",
            prompt=(
                "The mobile robot drove to its charger but is not drawing charge. Ability "
                "aborts the docking mission during teardown and the redock did not take.\n\n"
                "Push the robot onto the dock by hand or redock it from the MiR interface, "
                "confirm it is charging, then mark this as completed."
            ),
        )

    # -- single legs, with the retry policy -------------------------------

    def run_leg_with_retries(self, leg: Leg) -> None:
        """Run one leg, retrying the failures that are worth retrying.

        The caps come from the station registry, so a station whose marker is awkward can be
        given more attempts by editing `stations.toml`. Uncapped retries are the failure mode
        this replaces: the old code looped `while not success` forever on a blocked path.
        """
        station = self.registry.stations.get(leg.station)
        approach_cap = station.approach_attempts if station else 3
        calibration_cap = station.calibration_attempts if station else 2
        obstruction_cap = self.registry.obstruction_settings(leg.station).max_attempts
        attempts = {
            "blocked": approach_cap,
            "calibration": calibration_cap,
            "transient": 3,
            "obstruction": obstruction_cap,
        }
        tried: dict[str, int] = {}

        while True:
            try:
                self._run_leg_guarding_fields(leg)
                return
            except LegFailed as failure:
                kind = classify_failure(str(failure))
                cap = attempts.get(kind, 0)
                tried[kind] = tried.get(kind, 0) + 1
                if tried[kind] > cap:
                    raise self._exhausted(leg, kind, tried[kind] - 1, failure) from failure
                self.log(
                    f"leg {leg.index + 1} failed ({kind}, attempt {tried[kind]} of {cap}): "
                    f"{failure}"
                )
                try:
                    self._recover_for(kind, leg, attempt=tried[kind])
                except ObstructionDetected as during_recovery:
                    # The recovery drive hit something too. There is nowhere further to back
                    # off to, so this is a hold now rather than another attempt.
                    raise self._hold_for_obstruction(
                        leg, tried[kind], during_recovery
                    ) from during_recovery

    def _run_leg_guarding_fields(self, leg: Leg) -> None:
        """Run a leg, watching the base if it moves and muting the fields if it reaches in.

        The mute lives here rather than in the engine because it is a property of the station
        being reached into, which is registry knowledge, and because pairing it with the
        unmute in a `finally` is the only way to guarantee it comes back.

        The obstruction watch is the mirror of that for a base move. It is installed only for
        legs that move the base, because that is where stopping part way is safe: the arm is
        parked and anything being carried is on the robot's own rack.
        """
        station = self.registry.stations.get(leg.station)
        if leg.moves_the_base:
            self._run_leg_watching_the_base(leg)
            return
        if leg.kind is not LegKind.TRANSFER or station is None:
            self.engine.run_leg(leg)
            return
        if not station.mutes_protective_fields:
            self.engine.run_leg(leg)
            return
        with MuteGuard(
            self.ros,
            self.mir,
            ability=self.ability,
            station=leg.station,
            log=self.log,
            settle=self.mute_settle,
        ):
            self.engine.run_leg(leg)

    def _run_leg_watching_the_base(self, leg: Leg) -> None:
        """Drive, and stop the moment the base stops getting closer to where it is going.

        The watch is cleared in a `finally` for the same reason the mute is: a check left
        installed would be consulted during the next leg with the previous leg's history,
        and would either fire on nothing or miss a real stall.
        """
        watch = ObstructionWatch(
            self.mir,
            self.ros,
            station=leg.station,
            leg_index=leg.index,
            settings=self.registry.obstruction_settings(leg.station),
            log=self.log,
            clock=self.clock,
        )

        def look(_leg: Leg) -> None:
            found = watch.check()
            if found is None:
                return
            if found.hard:
                raise self._latch_for_collision(leg, found)
            self.log(f"obstruction on leg {leg.index + 1}:\n{found.describe()}")
            for step in stop_base(
                self.ros, self.ability, self.mir, settle=self.mute_settle, log=self.log
            ):
                if not step.ok:
                    self.log(f"  stop step {step.name} did not complete: {step.detail}")
            raise ObstructionDetected(
                f"{OBSTRUCTION_STOPPED} on the way to {leg.station}: {found.reason} "
                f"({found.signal})",
                leg_index=leg.index,
                obstruction=found,
            )

        self.engine.mid_leg_check = look
        try:
            self.engine.run_leg(leg)
        finally:
            self.engine.mid_leg_check = None
            if watch.saw_mute:
                # Worth saying out loud even on a leg that went fine: it means the base drove
                # part of this path with its scanners suppressed by Ability's own missions,
                # and that window is the reason this watchdog exists.
                self.log(
                    f"  note: the protective fields were muted at some point during leg "
                    f"{leg.index + 1}, so part of that drive was unprotected"
                )

    def _exhausted(
        self, leg: Leg, kind: str, attempts: int, failure: Exception
    ) -> MobileRobotError:
        if kind == "obstruction":
            return self._hold_for_obstruction(leg, attempts, failure)
        if kind in ("obstacle", "unknown"):
            return MaintenanceRequired(
                f"leg {leg.index + 1} ({leg}) hit something: {failure}",
                prompt=(
                    f"The mobile robot could not {leg.reason}.\n\n"
                    f"{failure}\n\n"
                    "Clear whatever is in the way, put the arm back to Home and the base at a "
                    "known station, set RobotPose and BasePosition to match, then mark this "
                    "as completed."
                ),
            )
        return MaintenanceRequired(
            f"leg {leg.index + 1} ({leg}) failed {attempts} time(s) with a {kind} fault: "
            f"{failure}",
            prompt=(
                f"The mobile robot tried {attempts} time(s) to {leg.reason} and could not.\n\n"
                f"{failure}\n\n"
                + (
                    "The station marker could not be seen. Check it is clean and not "
                    "obstructed.\n\n"
                    if kind == "calibration"
                    else "The path was blocked each time. Check nothing is parked in it.\n\n"
                )
                + "Then mark this as completed."
            ),
        )

    def _recover_for(self, kind: str, leg: Leg, *, attempt: int = 1) -> None:
        """What to do between attempts. Each of these is a deliberate choice."""
        self._clear_latched_error()
        if kind == "transient":
            # The manipulator was not ready. Nothing is wrong with where the robot is, so
            # waiting is the whole recovery; re-approaching would waste a minute.
            time.sleep(10.0)
            return
        if kind == "calibration":
            # The marker was not in view from the taught camera pose. Driving out and back in
            # re-runs the approach, which is what actually fixes this.
            self.log("re-approaching the station so the calibration gets a fresh look")
            self._drive(PARKING_STATION, "backing off after a failed calibration")
            self._drive(leg.station, f"re-approaching {leg.station} to retry the calibration")
            return
        if kind == "obstruction":
            self._recover_from_obstruction(leg, attempt)
            return
        if kind == "blocked":
            time.sleep(15.0)

    def _recover_from_obstruction(self, leg: Leg, attempt: int) -> None:
        """Escalate: let the MiR replan first, then make it plan from somewhere else.

        Python cannot compute a way around an obstacle. It has no scan data and no planner;
        only the MiR has both, and only while its protective fields are live. So the whole of
        "try moving around it" is: put the fields back, hand the same target to the MiR again
        so its local planner routes around whatever it can see, and if that fails, start the
        approach from `detour_via` so it plans a genuinely different path in rather than
        retrying the one that just failed.
        """
        settings = self.registry.obstruction_settings(leg.station)
        # Allowed to raise. Driving again into the thing we just stopped short of, with the
        # scanners still suppressed, is worse than giving up and asking for a person.
        ensure_fields_unmuted(
            self.ros,
            self.mir,
            ability=self.ability,
            settle=self.mute_settle,
            log=self.log,
            reason="before retrying a drive that was obstructed",
        )

        if attempt <= 1:
            self.log(
                "letting the MiR replan: driving to the same target again with the "
                "protective fields live"
            )
            time.sleep(5.0)
            return

        via = settings.detour_via
        if not via or via == leg.station:
            time.sleep(5.0)
            return
        self.log(f"re-approaching {leg.station} from {via} so the MiR plans a fresh path in")
        self._drive(via, f"backing off to {via} after an obstruction on the way to {leg.station}")

    def _latch_for_collision(self, leg: Leg, found: Obstruction) -> MobileRobotError:
        """Emergency-stop the robot, record where, and hold. No retry, ever.

        This is the path for evidence of contact or of something appearing in the way, and it
        differs from `_hold_for_obstruction` in the two ways that matter. The controller is
        latched rather than asked politely to stop, and the mission goes on hold immediately
        instead of after a re-approach. Retrying a drive that has already hit something, or
        that stopped because a person stepped into the aisle, is the one recovery that could
        make the situation worse.
        """
        self.log(f"COLLISION STOP on leg {leg.index + 1}:\n{found.describe()}")
        for step in hard_stop(self.ros, self.ability, self.mir, log=self.log):
            if not step.ok:
                self.log(f"  stop step {step.name} did not complete: {step.detail}")
        reason = (
            f"{COLLISION_STOPPED} on the way to {leg.station}: {found.reason} "
            f"({found.signal})"
        )
        record = self._record_hold(leg, 0, reason, found, latched=True)
        return CollisionStop(
            f"leg {leg.index + 1} ({leg}) was emergency-stopped: {reason}",
            leg_index=leg.index,
            held_resources=tuple(leg.resources),
            obstruction=found,
            prompt=record.prompt(),
        )

    def _hold_for_obstruction(
        self, leg: Leg, attempts: int, failure: Exception
    ) -> MobileRobotError:
        """Record where the obstruction was, then hand back an interruption, not a failure.

        A hold is not a failed mission: nothing is in the gripper, every leg before this one
        stands, and the work resumes from here once someone has moved whatever is in the way.
        Saying so with `ObstructionHold` rather than `MaintenanceRequired` is what lets the
        caller dock the robot and come back to it.
        """
        found = getattr(failure, "obstruction", None)
        record = self._record_hold(leg, attempts, str(failure), found, latched=False)
        return ObstructionHold(
            f"leg {leg.index + 1} ({leg}) could not get through after {attempts} attempt(s): "
            f"{failure}",
            leg_index=leg.index,
            held_resources=tuple(leg.resources),
            obstruction=found,
            prompt=record.prompt(),
        )

    def _record_hold(
        self,
        leg: Leg,
        attempts: int,
        reason: str,
        found: object | None,
        *,
        latched: bool,
    ) -> ObstructionHoldRecord:
        """Write the hold to disk, which is the only part of this that outlives the process."""
        record = ObstructionHoldRecord(
            reason=reason,
            station=leg.station,
            leg_index=leg.index,
            legs_completed=self.legs_completed,
            legs_total=len(self.mission) if self.mission else leg.index + 1,
            mission_id=self.mission.id if self.mission else "",
            mission_route=self.mission.route if self.mission else "",
            mission_description=self.mission.description if self.mission else "",
            leg_reason=leg.reason,
            attempts=attempts,
            obstruction=found.to_dict() if isinstance(found, Obstruction) else {},
            sample_positions=(
                self.mission.positions_after(self.legs_completed) if self.mission else {}
            ),
            held_resources=list(leg.resources),
            marker=self._mark_obstruction(found) if isinstance(found, Obstruction) else "",
            latched=latched,
        )
        path = save_hold(record, self.hold_path)
        self.log(f"the mission is on hold; the obstruction is recorded in {path}")
        self.log(record.describe())
        return record

    def _mark_obstruction(self, found: Obstruction) -> str:
        """Pin the obstruction on the MiR map, so it shows up where people already look.

        Best effort by design. It needs MiR credentials, and the hold record already holds
        the coordinates, so a failure here costs nothing worth failing a mission over.
        """
        point = found.obstruction_point
        if point is None:
            return ""
        name = f"OBSTRUCTION {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        try:
            self.mir.create_position(
                name,
                point["x"],
                point["y"],
                (found.robot_pose or {}).get("orientation_deg", 0.0),
                map_id=found.sample.map_id or None,
            )
        except Exception as error:  # noqa: BLE001 - the coordinates are already recorded
            self.log(f"could not mark the obstruction on the MiR map: {error}")
            return ""
        self.log(f"marked the obstruction on the MiR map as {name!r}")
        return name

    def _drive(self, station: str, reason: str) -> None:
        """One base move, without disturbing the mission in progress.

        A recovery happens inside a mission, so it must not overwrite the mission the
        dashboard is showing or the leg counter a resume depends on. `go_to` is for a base
        move that *is* the work; this is for one that gets the work unstuck.

        Watched like any other base move. A recovery drive is the most likely of all of them
        to meet the obstruction that caused the recovery, so running it unwatched would leave
        the one move made after something went wrong as the only one nothing is looking at.
        """
        self._run_leg_watching_the_base(travel(station, reason))
        self._record_arrival(station)

    def _clear_latched_error(self) -> None:
        try:
            self.ability.stop()
        except RobotApiError:
            pass  # nothing to stop is the normal case here

    # -- the standing moves -----------------------------------------------

    def go_to(self, station: str, reason: str) -> MissionResult:
        """Drive to a station as a one-leg mission, so it shows up like any other work."""
        self.registry.station(station)
        return self.run_mission(
            Mission.build(
                [travel(station, reason)], route=f"-> {station}", description=reason
            ),
            skip_preflight=True,
        )

    def go_home(self, reason: str = "returning to the parking spot") -> MissionResult:
        return self.go_to(PARKING_STATION, reason)

    def send_to_charger(
        self,
        reason: str = "docking to charge",
        *,
        wait_for_charge: bool = False,
        should_cancel: Reason | None = None,
    ) -> MissionResult:
        """Dock. Never waits inside Ability unless explicitly asked to.

        `ChargingNoWait` is the default because a mission that resumes at 90% needs Python
        watching the battery, not an Ability block sitting on it for an hour with no way to
        report progress or be interrupted.
        """
        station = CHARGER_WAIT if wait_for_charge else CHARGER_NO_WAIT
        return self.run_mission(
            Mission.build([dock(station, reason)], route=f"-> {station}", description=reason),
            should_cancel=should_cancel,
            skip_preflight=True,
        )

    def wait_until_charged(
        self,
        *,
        should_cancel: Reason | None = None,
        timeout: float = 3 * 60 * 60,
    ) -> float | None:
        """Wait on the dock until the battery clears the resume level.

        Interruptible, and it says why it is waiting, because this is the longest thing the
        robot ever does and a silent hour looks identical to a hang.
        """
        target = self.battery_policy.resume_at
        self.engine.wait_for(
            lambda: self.battery_policy.may_resume(self.battery()),
            f"the battery to reach {target:.0f}%",
            timeout=timeout,
            mission=self.mission,
            should_cancel=should_cancel,
        )
        return self.battery()

    # -- the obstruction hold ----------------------------------------------

    def hold(self) -> ObstructionHoldRecord | None:
        """The mission on hold for an obstruction, if there is one.

        Read from disk rather than from memory, because the whole point of a hold is that it
        survives the process that created it: the person who has to move the box may not
        arrive until tomorrow.
        """
        return load_hold(self.hold_path)

    @contextmanager
    def _keeping_the_mission_state(self, status: str, detail: str) -> Iterator[None]:
        """Report ``status`` for the interrupted mission across a drive taken on its behalf.

        Docking after a hold or a cancellation is itself run as a one-leg mission, so without
        this the driver would end up reporting that one leg, completed, in place of the
        delivery that is actually stopped part-way with a sample still on the robot.
        """
        mission = self.mission
        legs_completed = self.legs_completed
        self.mission_status = status
        self.mission_detail = detail
        try:
            yield
        finally:
            self.mission = mission
            self.legs_completed = legs_completed
            self.mission_status = status
            self.mission_detail = detail

    def park_for_obstruction(self, held: ObstructionHold) -> None:
        """Get the robot onto the charger and leave the mission where it stopped.

        Never raises, for the same reason `park_after_cancellation` does not: this runs on a
        path that already has a reason for stopping, and replacing that reason with a second
        failure would lose the coordinates a person needs. A robot that cannot reach the
        charger is left where it is, said out loud, and still on hold.

        A latched robot is not sent anywhere. The check is here rather than in the callers
        because there are three of them and this is the function that would do the damage: a
        robot that has just hit something must not drive back past it to reach the charger,
        and after an emergency stop it could not anyway.
        """
        with self._keeping_the_mission_state("held", str(held)):
            if held.latched:
                self.log(
                    "emergency-stopped, so the robot stays where it is: it needs a person to "
                    "check it and reset the stop before it can be driven anywhere"
                )
                return
            try:
                self.log("stopped for an obstruction; docking and holding the mission")
                self.send_to_charger(f"holding after an obstruction: {held}")
            except MobileRobotError as failure:
                self.log(f"could not dock after an obstruction: {failure}")
                try:
                    self.go_home("could not reach the charger after an obstruction")
                except MobileRobotError as second:
                    self.log(
                        f"could not reach Home either ({second}); the robot is holding where "
                        f"it stopped"
                    )

    def obstruction_cleared(self) -> bool:
        """Whether a person has said the path is clear, so a resume may go ahead."""
        record = self.hold()
        return record is not None and record.cleared

    def resume_after_obstruction(
        self,
        mission: Mission,
        *,
        on_event: Callable[[MissionEvent], None] | None = None,
        **kwargs: Any,
    ) -> MissionResult:
        """Pick the held mission up from the leg it stopped on.

        Refuses unless someone has cleared the hold. That refusal is the safety property
        this whole feature exists for: without it the robot would drive back into the same
        object as soon as anything retried, which is exactly what the uncapped retry loop
        this replaced used to do.
        """
        record = self.hold()
        if record is None:
            raise PreflightFailed(
                "there is no obstruction hold to resume from; run the mission normally"
            )
        if not record.cleared:
            raise PreflightFailed(
                "the obstruction has not been cleared, so the robot will not drive that "
                f"path again.\n{record.describe()}"
            )
        if record.latched:
            # Said before the preflight refuses, so the reason is the collision rather than
            # whichever check happens to fail first. After an emergency stop the robot is
            # standing in the aisle with no station recorded, and both of those have to be
            # put right by a person at the robot, not by a retry.
            self.log(
                "this hold was an emergency stop. The robot must have been reset at the "
                "robot, driven back to a known station, and its position re-established "
                "before this can go anywhere; the preflight below will say so if not"
            )
        self.log(
            f"the obstruction was cleared at {record.cleared_at} by "
            f"{record.cleared_by or 'someone'}; resuming at leg {record.leg_index + 1}"
        )
        # Cleared before the mission starts, not after it finishes: if this resume hits a
        # fresh obstruction it must write a new hold, not find the old one already there.
        clear_hold(self.hold_path)
        return self.run_mission(
            mission, start_at=record.leg_index, on_event=on_event, **kwargs
        )

    def park_after_cancellation(self, reason: str) -> None:
        """Get the robot somewhere safe after a cancel, without ever raising.

        Called from a cancellation path, where a second exception would replace the reason
        the task was stopping in the first place. Failures become maintenance prompts, which
        is the honest outcome: the robot is stranded and someone has to look.
        """
        with self._keeping_the_mission_state("cancelled", reason):
            try:
                self.log(f"cancelled ({reason}); docking the robot")
                self.send_to_charger(f"cancelled: {reason}", wait_for_charge=False)
            except MobileRobotError as failure:
                self.log(f"could not dock after cancellation: {failure}")
                try:
                    self.go_home("could not reach the charger after a cancellation")
                except MobileRobotError as second:
                    self.log(f"could not reach Home either: {second}")

    # -- emergencies -------------------------------------------------------

    def emergency_stop(self) -> StopReport:
        """Stop now. Reports what it managed, and does not pretend to be a physical e-stop."""
        self.mission_status = "stopped"
        self.mission_detail = "emergency stop"
        return emergency_stop(self.ability, self.ros, self.mir, log=self.log)

    def validate(self) -> None:
        """Check the registry against the live cell. Call this from `alabos setup`."""
        problems = self.registry.validate_against_controller(ros=self.ros, mir=self.mir)
        if problems:
            raise PreflightFailed(
                "the station registry disagrees with the robot:\n  - "
                + "\n  - ".join(problems)
            )
        self.log(f"{self.registry} validated against the live controller")

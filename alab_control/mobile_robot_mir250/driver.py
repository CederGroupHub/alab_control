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
from typing import Any, Callable

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
from .engine import MissionEngine, MissionEvent, MissionResult, Reason
from .errors import (
    LegFailed,
    MaintenanceRequired,
    MissionInterrupted,
    MobileRobotError,
    PreflightFailed,
)
from .mission import Leg, LegKind, Mission, dock, travel
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


def classify_failure(message: str) -> str:
    """Name a leg failure so the retry policy can decide what to do about it.

    - `blocked`: something is in the way. Retrying after a pause often works.
    - `calibration`: the station marker was not seen. Retrying from Home re-approaches, which
      is what usually fixes it.
    - `transient`: the manipulator was not ready. Short retries, no re-approach.
    - `obstacle`: the arm hit something. A person has to look, so no retry.
    - `unknown`: everything else, treated as an obstacle because guessing is worse.
    """
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
                self.mission_status = getattr(partial, "status", "cancelled")
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
        attempts = {"blocked": approach_cap, "calibration": calibration_cap, "transient": 3}
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
                self._recover_for(kind, leg)

    def _run_leg_guarding_fields(self, leg: Leg) -> None:
        """Run a leg, muting the protective fields only if the station needs it.

        The mute lives here rather than in the engine because it is a property of the station
        being reached into, which is registry knowledge, and because pairing it with the
        unmute in a `finally` is the only way to guarantee it comes back.
        """
        station = self.registry.stations.get(leg.station)
        if leg.kind is not LegKind.TRANSFER or station is None:
            self.engine.run_leg(leg)
            return
        if not station.mutes_protective_fields:
            self.engine.run_leg(leg)
            return
        with MuteGuard(
            self.ros,
            self.mir,
            station=leg.station,
            log=self.log,
            settle=self.mute_settle,
        ):
            self.engine.run_leg(leg)

    def _exhausted(
        self, leg: Leg, kind: str, attempts: int, failure: Exception
    ) -> MobileRobotError:
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

    def _recover_for(self, kind: str, leg: Leg) -> None:
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
        if kind == "blocked":
            time.sleep(15.0)

    def _drive(self, station: str, reason: str) -> None:
        """One base move, without disturbing the mission in progress.

        A recovery happens inside a mission, so it must not overwrite the mission the
        dashboard is showing or the leg counter a resume depends on. `go_to` is for a base
        move that *is* the work; this is for one that gets the work unstuck.
        """
        self.engine.run_leg(travel(station, reason))
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

    def park_after_cancellation(self, reason: str) -> None:
        """Get the robot somewhere safe after a cancel, without ever raising.

        Called from a cancellation path, where a second exception would replace the reason
        the task was stopping in the first place. Failures become maintenance prompts, which
        is the honest outcome: the robot is stranded and someone has to look.
        """
        self.mission_status = "cancelled"
        self.mission_detail = reason
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

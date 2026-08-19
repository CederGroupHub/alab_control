"""A MiR250 cell that exists only in memory.

The point of these is that the code under test cannot tell the difference. `FakeAbility`
answers `status`, `load_program` and `start` the way the controller does, including the
Ready-then-Idle teardown and the delay before a started program reports Executing, so the
engine's wait loop runs for real rather than being stubbed out. `MockMiR250` swaps those in
behind the real :class:`MiR250MobileManipulator`, so a test of cancellation exercises the
same `run_mission` the robot does.

They are scriptable in the ways that matter: which leg fails and with what controller
message, when the battery drops, and whether the protective-field mute takes.

This lives in the package rather than beside the tests because AlabOS's simulation mode
needs it too. A device that returns a bare ``Mock`` in sim mode reports a ``Mock`` battery
and a ``Mock`` pose, which cannot be compared with 80 and so exercises none of the logic
that matters here; with this driver, `alabos` sim mode runs the same mission state machine,
the same battery policy and the same cancellation path as the cell.
"""

from __future__ import annotations

from typing import Any, Callable

from .clients import Pose, RobotApiError
from .driver import MiR250MobileManipulator
from .poses import ARM_MOUNT_OFFSET_M, StationPoses
from .registry import registry as load_registry

#: Where the fake cell says it is, so the recorded-pose reconciliation has something to
#: agree with. These are the real recorded values for the two stations we have.
FAKE_POSES = {
    "Charging": Pose(-4.3465, -2.1534, 0.0, 0.6186, 0.0, 0.0),
    "LABMAN": Pose(-4.895, -6.269, 0.0, 0.5748, 0.0, 0.0),
}


class FakeAbility:
    """Ability REST V2, in memory.

    A started program reports Executing for `executing_polls` status reads and then goes
    Idle, which is what makes the engine's "has it started yet" logic get exercised instead
    of being short-circuited by an instantly-finished leg.
    """

    def __init__(
        self,
        *,
        executing_polls: int = 2,
        fail_on: dict[int, str] | None = None,
        stall_at: set[str] | None = None,
        collide_at: set[str] | None = None,
        battery: float = 95.0,
    ) -> None:
        self.executing_polls = executing_polls
        #: Leg number (1-based, in the order started) to the controller message it fails with.
        self.fail_on = dict(fail_on or {})
        #: Stations whose approach never completes, standing in for something parked in the
        #: path. Keyed on the station rather than the leg number so a re-approach to the same
        #: place is obstructed too, which is what makes the escalation testable.
        self.stall_at = set(stall_at or ())
        #: Stations whose approach drives into something: the same lack of progress as
        #: `stall_at`, but with the wheels still turning. That one difference is what tells
        #: the watchdog to latch instead of retry, so the two must be separately stageable.
        self.collide_at = set(collide_at or ())
        self.battery = battery

        self.loaded: dict[str, Any] | None = None
        self.started: list[dict[str, str]] = []
        self.state_name = "Idle"
        self.message = ""
        self.polls = 0
        self.stops = 0
        self.load_attempts = 0
        self.program_list = ["Main"]

    # -- the surface the driver uses ---------------------------------------

    def wait_until_loadable(self, timeout: float = 30.0, poll: float = 0.5) -> str:
        return "Idle"

    def load_program(self, name: str, arguments: Any = None, **_: Any) -> dict[str, Any]:
        self.load_attempts += 1
        self.loaded = {"name": name, "arguments": dict(arguments or {})}
        return self.loaded

    def program_current(self) -> dict[str, Any] | None:
        return self.loaded

    def programs(self) -> list[str]:
        return list(self.program_list)

    def start(self) -> dict[str, Any]:
        assert self.loaded is not None, "start() before load_program()"
        self.started.append(dict(self.loaded["arguments"]))
        self.state_name = "Executing"
        self.message = ""
        self.polls = 0
        return {"state": "Executing"}

    def stop(self) -> dict[str, Any]:
        self.stops += 1
        if self.state_name in (
            "Idle",
            "Entity Error Active",
            "Emergency Stop Active",
            "Safeguard Stop Active",
        ):
            raise RobotApiError("nothing to stop", status=400)
        self.state_name = "Idle"
        self.message = ""
        return {"state": "Idle"}

    def state(self) -> str:
        return self.state_name

    @property
    def driving_to(self) -> str:
        """The station the leg in flight is driving to, or "" for anything else."""
        if self.state_name != "Executing":
            return ""
        return str((self.loaded or {}).get("arguments", {}).get("target_base_position") or "")

    @property
    def stalled(self) -> bool:
        return self.driving_to in self.stall_at or self.colliding

    @property
    def colliding(self) -> bool:
        return self.driving_to in self.collide_at

    def status(self) -> dict[str, Any]:
        self.polls += 1
        if self.state_name == "Executing" and self.polls > self.executing_polls:
            failure = self.fail_on.get(len(self.started))
            if failure:
                self.state_name = "Execution Error"
                self.message = failure
            elif self.stalled:
                # Ability sees nothing wrong: its own move block only complains minutes
                # later, which is the gap the obstruction watch exists to close.
                pass
            else:
                self.state_name = "Idle"
                self.message = ""
        return {
            "state": self.state_name,
            "message": self.message,
            "battery": self.battery,
            "program": (self.loaded or {}).get("name", ""),
        }

    def transform(self, ref_id: str = "Base", from_ref: str = "World") -> Pose:
        return FAKE_POSES.get(self.base_position_hint or "Charging", FAKE_POSES["Charging"])

    #: Set by FakeRos so the fake pose follows the fake BasePosition.
    base_position_hint: str = "Charging"

    def close(self) -> None:
        pass


class FakeRos:
    """The Ability rosbridge, in memory. Tracks BasePosition the way `Main` does."""

    def __init__(self, *, base_position: str = "Charging", charging: bool = True) -> None:
        self.variables = {"BasePosition": base_position, "RobotPose": "Home"}
        self.charging = charging
        self.muted = False
        self.mute_calls: list[bool] = []
        self.stops = 0
        self.token_releases = 0
        self.dock_calls: list[str] = []
        #: Set to refuse the unmute, which must become a maintenance stop.
        self.refuse_unmute = False
        self.ability: FakeAbility | None = None
        self.module_names = ["manipulator", "mobile", "ability_backend"]
        self.health: dict[str, bool] = {}
        self.restarted: list[str] = []
        self.deleted_programs: list[str] = []
        self.published: list[tuple[str, dict[str, Any], str]] = []
        self.joystick_active = False
        self.teach_active = False
        self.manual_mode = False
        #: How many times the base was told to stop, so a test can prove the wheels were
        #: stopped before anything else was attempted.
        self.base_stops = 0
        #: What the blocked topic says. None means it published nothing, which is the normal
        #: case on the real cell and must not be read as "not blocked".
        self.blocked: bool | None = None
        self.mobile_error = ""

    def base_position(self) -> str:
        return str(self.variables["BasePosition"])

    def robot_pose(self) -> str:
        return str(self.variables["RobotPose"])

    def is_charging(self) -> bool:
        return self.charging

    def system_stop(self) -> dict[str, Any]:
        self.stops += 1
        if self.ability is not None and self.ability.state_name == "Entity Error Active":
            raise RobotApiError("couldn't process event: Stop")
        return {"success": True}

    def docker_modules(self, timeout: float = 5.0) -> list[str]:
        return list(self.module_names)

    def restart_docker_module(self, name: str) -> dict[str, Any]:
        self.restarted.append(name)
        if self.ability is not None and name in ("manipulator", "mobile"):
            if self.ability.state_name == "Entity Error Active":
                self.ability.state_name = "Idle"
                self.ability.message = ""
        return {"success": True}

    def healthcheck(self, name: str) -> dict[str, Any]:
        ok = self.health.get(name, True)
        return {"success": ok, "message": "" if ok else "failed"}

    def publish(
        self, topic: str, message: Any, *, type_name: str
    ) -> None:
        self.published.append((topic, dict(message or {}), type_name))

    def service_type(self, service: str) -> str:
        return "std_srvs/Trigger"

    def topic_type(self, topic: str) -> str:
        return "std_msgs/Empty"

    def force_token_release(self) -> dict[str, Any]:
        self.token_releases += 1
        return {"success": True}

    def positions(self) -> dict[str, str]:
        return {
            station.mir_position: station.mir_position_guid
            for station in load_registry().stations.values()
            if station.mir_position and station.mir_position_guid
        }

    def charging_stations(self) -> dict[str, str]:
        return {
            station.mir_charging_station: station.mir_charging_station_guid
            for station in load_registry().stations.values()
            if station.mir_charging_station and station.mir_charging_station_guid
        }

    def move_to_charging_station(self, guid: str) -> dict[str, Any]:
        self.dock_calls.append(guid)
        self.charging = True
        return {"success": True}

    def topic_messages(
        self, topic: str, *, count: int = 1, timeout: float | None = None
    ) -> Any:
        """Yield what a topic would publish. Quiet by default, like the real ones."""
        if topic.endswith("mobile_device_blocked") and self.blocked is not None:
            yield {"data": bool(self.blocked)}
            return
        if topic == "/mobile/status":
            yield {"mobile_driver_status": {"error_msg": self.mobile_error}}
            return
        return

    def call_service(self, service: str, payload: Any = None) -> dict[str, Any]:
        args = payload or {}
        if service == "/mobile/stop":
            self.base_stops += 1
            return {"success": True}
        if service.endswith("mute_protective_fields"):
            wanted = bool(args.get("mute"))
            self.mute_calls.append(wanted)
            if not wanted and self.refuse_unmute:
                return {"success": False, "error_message": "refused"}
            self.muted = wanted
            return {"success": True}
        if service.endswith("restart_module"):
            return self.restart_docker_module(str(args.get("request") or ""))
        if service.endswith("healthcheck"):
            name = service.strip("/").split("/")[0]
            return self.healthcheck(name)
        if service.endswith("start_joystick"):
            self.joystick_active = True
            return {"success": True}
        if service.endswith("stop_joystick"):
            self.joystick_active = False
            return {"success": True}
        if service.endswith("start_teach_mode"):
            self.teach_active = True
            self.manual_mode = True
            return {"success": True}
        if service.endswith("end_teach_mode"):
            self.teach_active = False
            self.manual_mode = False
            return {"success": True}
        if service.endswith("get_manual_mode"):
            return {"success": True, "response": self.manual_mode}
        if service.endswith("set_manual_mode"):
            self.manual_mode = bool(args.get("request", args.get("data", False)))
            return {"success": True}
        if service.endswith("activate_programming"):
            if self.ability is not None and self.ability.state_name == "Entity Error Active":
                return {
                    "success": False,
                    "error_message": "couldn't process ActivateProgramming",
                }
            return {"success": True, "response": "fake-token"}
        if service.endswith("delete_program"):
            name = str(args.get("program_name") or "")
            self.deleted_programs.append(name)
            if self.ability is not None and name in self.ability.program_list:
                self.ability.program_list.remove(name)
            return {"success": True}
        return {"success": True}


class FakeMir:
    """The MiR's own REST API, in memory."""

    def __init__(
        self,
        *,
        battery: float = 95.0,
        ros: FakeRos | None = None,
        ability: FakeAbility | None = None,
        mode_key: str = "auto",
        state_text: str = "Pause",
        mission_text: str = "Waiting for new missions ...",
        errors: list[Any] | None = None,
    ) -> None:
        self.battery = battery
        self.ros = ros
        #: Read so a stalled drive can be reported as one: the MiR knows it is executing a
        #: mission and getting no closer, which is precisely what Ability does not say.
        self.ability = ability
        self.mode_key = mode_key
        self.state_text = state_text
        self.mission_text = mission_text
        self.errors = list(errors or [])
        self.authenticated = True
        self.reachable = True
        #: Persisted MiR setting 2137. Independent of Ability's ROS mute bit, matching
        #: the live cell: ROS unmute can succeed while this stays true.
        self.setting_2137 = False
        self.setting_writes: list[tuple[int, str]] = []
        self.map_id = "fake-map"
        #: How far a stalled drive says it still has to go. Never falls, which is the whole
        #: signal.
        self.stalled_distance = 2.4
        #: A collision closes on the target first and only then stops getting closer, because
        #: the real impact detector arms itself once a drive has been seen making progress.
        #: A fake that stalled from the first sample would pass a test the cell would fail.
        self.collision_closing = (3.2, 2.8)
        #: Wheels still turning while the target does not get closer. The one reading that
        #: separates driving into something from failing to set off.
        self.colliding_speed = 0.18
        self._collision_samples = 0
        self.created_positions: list[dict[str, Any]] = []

    def status(self) -> dict[str, Any]:
        if not self.reachable:
            raise RobotApiError("the MiR did not answer", status=None)
        pose = FAKE_POSES.get(
            self.ros.base_position() if self.ros else "Charging", FAKE_POSES["Charging"]
        )
        stalled = bool(self.ability is not None and self.ability.stalled)
        colliding = bool(self.ability is not None and self.ability.colliding)
        return {
            "battery_percentage": self.battery,
            "mode_key_state": self.mode_key,
            "state_text": "Executing" if stalled else self.state_text,
            "state_id": 5 if stalled else 4,
            "mission_text": (
                f"Trying to reach {self.ability.driving_to}" if stalled else self.mission_text
            ),
            "errors": self.errors,
            "safety_system_muted": bool(self.setting_2137)
            or bool(self.ros.muted if self.ros else False),
            "distance_to_next_target": self._distance(stalled, colliding),
            # A stalled drive is standing still: the MiR is waiting for a path it will not
            # find. A colliding one is not, and that is the difference the watchdog reads.
            "velocity": {
                "linear": self.colliding_speed if colliding else 0.0,
                "angular": 0.0,
            },
            "map_id": self.map_id,
            "footprint": "[[0.54,-0.38],[0.54,0.38],[-0.54,0.38],[-0.54,-0.38]]",
            # The MiR reports its own centre, which sits a fixed distance from the arm base
            # Ability reports. Preflight cross-checks the two against exactly that offset,
            # so a fake that returned the same numbers twice would defeat the check.
            "position": {
                "x": pose.x + ARM_MOUNT_OFFSET_M,
                "y": pose.y,
                "orientation": pose.yaw_deg,
            },
        }

    def _distance(self, stalled: bool, colliding: bool) -> float:
        """What the drive says is left to run, closing first when it is a collision."""
        if not colliding:
            self._collision_samples = 0
            return self.stalled_distance if stalled else 0.0
        step = self._collision_samples
        self._collision_samples += 1
        if step < len(self.collision_closing):
            return float(self.collision_closing[step])
        return float(self.stalled_distance)

    def create_position(
        self,
        name: str,
        x: float,
        y: float,
        orientation: float = 0.0,
        *,
        map_id: str | None = None,
        type_id: int = 0,
    ) -> dict[str, Any]:
        record = {
            "name": name,
            "pos_x": float(x),
            "pos_y": float(y),
            "orientation": float(orientation),
            "type_id": int(type_id),
            "map_id": map_id or self.map_id,
        }
        self.created_positions.append(record)
        return record

    def battery_percentage(self) -> float:
        return float(self.battery)

    def guid(self, kind: str, guid: str) -> dict[str, Any]:
        for station in load_registry().stations.values():
            if station.mir_guid == guid:
                return {
                    "name": station.mir_position or station.mir_charging_station,
                    "guid": guid,
                    "pos_x": 0.0,
                    "pos_y": 0.0,
                    "orientation": 0.0,
                }
        raise RobotApiError(f"no such position {guid}", status=404)

    def setting(self, setting_id: int) -> dict[str, Any]:
        if setting_id == 2137:
            return {
                "id": 2137,
                "name": "Mute protective fields",
                "value": "true" if self.setting_2137 else "false",
            }
        return {"id": setting_id, "value": ""}

    def put_setting(self, setting_id: int, value: str) -> dict[str, Any]:
        self.setting_writes.append((int(setting_id), str(value)))
        if int(setting_id) == 2137:
            self.setting_2137 = str(value).lower() in ("true", "1")
        return {"id": setting_id, "value": value}

    def set_protective_fields_muted(self, muted: bool) -> None:
        self.put_setting(2137, "true" if muted else "false")

    def close(self) -> None:
        pass


class MockMiR250(MiR250MobileManipulator):
    """The real driver with a fake cell underneath it.

    Everything except the three clients is the production object, so a test of cancellation
    or of the battery policy runs the same `run_mission`, the same retry policy and the same
    mute pairing the robot does.
    """

    def __init__(
        self,
        *,
        tmp_path: Any = None,
        hold_path: Any = None,
        battery: float = 95.0,
        base_position: str = "Charging",
        charging: bool = True,
        executing_polls: int = 2,
        fail_on: dict[int, str] | None = None,
        stall_at: set[str] | None = None,
        collide_at: set[str] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        ability = FakeAbility(
            executing_polls=executing_polls,
            fail_on=fail_on,
            stall_at=stall_at,
            collide_at=collide_at,
            battery=battery,
        )
        ability.base_position_hint = base_position
        ros = FakeRos(base_position=base_position, charging=charging)
        ros.ability = ability
        super().__init__(
            registry=load_registry(),
            poses=StationPoses(
                runtime_path=(tmp_path / "runtime_poses.json") if tmp_path else None
            ),
            log=log or (lambda _message: None),
            # An imaginary robot has no business writing to the hold a real mission would be
            # resumed from, and a leftover hold in the user's home would fail every test run
            # after the first. A caller rehearsing the operator's side of a hold can name a
            # scratch file to be read back from another process.
            hold_path=hold_path or ((tmp_path / "hold.json") if tmp_path else None),
            ability=ability,
            ros=ros,
            mir=FakeMir(battery=battery, ros=ros, ability=ability),
        )
        # The fakes advance on being read, so there is nothing to wait for. A test that
        # waited on real clocks would soon stop being run.
        self.engine.poll = 0.0
        self.mute_settle = 0.0
        #: Recorded so tests can assert nothing waited on a real clock.
        self.slept: list[float] = []
        #: One second of imaginary time per reading, so a twenty-second stall grace is
        #: twenty polls rather than twenty seconds of a test suite's life.
        self._ticks = 0.0
        self.clock = self._tick

    def _tick(self) -> float:
        self._ticks += 1.0
        return self._ticks

    # Time is the one thing the fakes cannot make instant, so it is replaced outright.
    def _recover_for(self, kind: str, leg: Any, *, attempt: int = 1) -> None:
        real_sleep = None
        import alab_control.mobile_robot_mir250.driver as driver_module

        real_sleep = driver_module.time.sleep
        driver_module.time.sleep = lambda seconds: self.slept.append(seconds)
        try:
            super()._recover_for(kind, leg, attempt=attempt)
        finally:
            driver_module.time.sleep = real_sleep

    def _confirm_charging(self, station: str) -> None:
        """`settle_on_charge` waits 25 seconds by design; the fake asserts the shape instead."""
        self.ros.charging = True
        self.confirmed_charging = getattr(self, "confirmed_charging", [])
        self.confirmed_charging.append(station)

    def set_battery(self, value: float) -> None:
        self.ability.battery = value
        self.mir.battery = value

    @property
    def legs_started(self) -> list[dict[str, str]]:
        """The Main argument sets the controller was actually asked to run."""
        return self.ability.started

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
        battery: float = 95.0,
    ) -> None:
        self.executing_polls = executing_polls
        #: Leg number (1-based, in the order started) to the controller message it fails with.
        self.fail_on = dict(fail_on or {})
        self.battery = battery

        self.loaded: dict[str, Any] | None = None
        self.started: list[dict[str, str]] = []
        self.state_name = "Idle"
        self.message = ""
        self.polls = 0
        self.stops = 0
        self.load_attempts = 0

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
        return ["Main"]

    def start(self) -> dict[str, Any]:
        assert self.loaded is not None, "start() before load_program()"
        self.started.append(dict(self.loaded["arguments"]))
        self.state_name = "Executing"
        self.message = ""
        self.polls = 0
        return {"state": "Executing"}

    def stop(self) -> dict[str, Any]:
        self.stops += 1
        if self.state_name == "Idle":
            raise RobotApiError("nothing to stop", status=400)
        self.state_name = "Idle"
        self.message = ""
        return {"state": "Idle"}

    def state(self) -> str:
        return self.state_name

    def status(self) -> dict[str, Any]:
        self.polls += 1
        if self.state_name == "Executing" and self.polls > self.executing_polls:
            failure = self.fail_on.get(len(self.started))
            if failure:
                self.state_name = "Execution Error"
                self.message = failure
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

    def base_position(self) -> str:
        return str(self.variables["BasePosition"])

    def robot_pose(self) -> str:
        return str(self.variables["RobotPose"])

    def is_charging(self) -> bool:
        return self.charging

    def system_stop(self) -> dict[str, Any]:
        self.stops += 1
        return {"success": True}

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

    def call_service(self, service: str, payload: Any = None) -> dict[str, Any]:
        if service.endswith("mute_protective_fields"):
            wanted = bool((payload or {}).get("mute"))
            self.mute_calls.append(wanted)
            if not wanted and self.refuse_unmute:
                return {"success": False, "error_message": "refused"}
            self.muted = wanted
            return {"success": True}
        return {"success": True}


class FakeMir:
    """The MiR's own REST API, in memory."""

    def __init__(
        self,
        *,
        battery: float = 95.0,
        ros: FakeRos | None = None,
        mode_key: str = "auto",
        state_text: str = "Pause",
        mission_text: str = "Waiting for new missions ...",
        errors: list[Any] | None = None,
    ) -> None:
        self.battery = battery
        self.ros = ros
        self.mode_key = mode_key
        self.state_text = state_text
        self.mission_text = mission_text
        self.errors = list(errors or [])
        self.authenticated = True
        self.reachable = True

    def status(self) -> dict[str, Any]:
        if not self.reachable:
            raise RobotApiError("the MiR did not answer", status=None)
        pose = FAKE_POSES.get(
            self.ros.base_position() if self.ros else "Charging", FAKE_POSES["Charging"]
        )
        return {
            "battery_percentage": self.battery,
            "mode_key_state": self.mode_key,
            "state_text": self.state_text,
            "mission_text": self.mission_text,
            "errors": self.errors,
            "safety_system_muted": bool(self.ros.muted) if self.ros else False,
            # The MiR reports its own centre, which sits a fixed distance from the arm base
            # Ability reports. Preflight cross-checks the two against exactly that offset,
            # so a fake that returned the same numbers twice would defeat the check.
            "position": {
                "x": pose.x + ARM_MOUNT_OFFSET_M,
                "y": pose.y,
                "orientation": pose.yaw_deg,
            },
        }

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
        battery: float = 95.0,
        base_position: str = "Charging",
        charging: bool = True,
        executing_polls: int = 2,
        fail_on: dict[int, str] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        ability = FakeAbility(
            executing_polls=executing_polls, fail_on=fail_on, battery=battery
        )
        ability.base_position_hint = base_position
        ros = FakeRos(base_position=base_position, charging=charging)
        super().__init__(
            registry=load_registry(),
            poses=StationPoses(
                runtime_path=(tmp_path / "runtime_poses.json") if tmp_path else None
            ),
            log=log or (lambda _message: None),
            ability=ability,
            ros=ros,
            mir=FakeMir(battery=battery, ros=ros),
        )
        # The fakes advance on being read, so there is nothing to wait for. A test that
        # waited on real clocks would soon stop being run.
        self.engine.poll = 0.0
        self.mute_settle = 0.0
        #: Recorded so tests can assert nothing waited on a real clock.
        self.slept: list[float] = []

    # Time is the one thing the fakes cannot make instant, so it is replaced outright.
    def _recover_for(self, kind: str, leg: Any) -> None:
        real_sleep = None
        import alab_control.mobile_robot_mir250.driver as driver_module

        real_sleep = driver_module.time.sleep
        driver_module.time.sleep = lambda seconds: self.slept.append(seconds)
        try:
            super()._recover_for(kind, leg)
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

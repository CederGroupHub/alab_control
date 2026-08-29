import logging
import time
from enum import Enum
from functools import wraps

import requests

logger = logging.getLogger(__name__)

MRA_POLL_LOG_INTERVAL_SECONDS = 30.0
MOBILE_ROBOT_DEVICE_NAME = "MOBILE_arm_ALFRED"


def _should_trace_mobile_robot() -> bool:
    try:
        from alab_management.utils.device_verbose_logging import (
            should_trace_mobile_robot,
        )

        return should_trace_mobile_robot()
    except ImportError:
        return False


def _mra_trace(message: str, *args) -> None:
    if not _should_trace_mobile_robot():
        return
    try:
        from alab_management.utils.device_verbose_logging import log_verbose_device

        log_verbose_device(MOBILE_ROBOT_DEVICE_NAME, message, *args)
    except ImportError:
        logger.info("[mobile-robot] " + message, *args)


class MRAState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    SAFEGUARD_STOP = "safeguard_stop"


#: Controller states, as reported by http://<ip>:8082/v2/status. See
#: https://docs.alabos.com/alabOS/api/mobile-robot-arm/. Anything not listed here is treated as an
#: error, because acting on a state the driver does not understand is worse than stopping.
IDLE_STATES = {"Idle", "Ready"}
RUNNING_STATES = {"Executing", "Finishing Execution"}
SAFEGUARD_STATES = {"Safeguard Stop Active"}
#: "Entity Error Active" is what the controller reports when a component it owns -- typically the
#: manipulator failing its healthcheck -- is faulted.
ERROR_STATES = {"Execution Error Active", "Emergency Stop Active", "Entity Error Active"}


def ability_cell_snapshot(ip: str) -> dict:
    """Read REST + ROS together. This is what the 8082 status page does not show."""
    from alab_control.mobile_robot_mir250.clients import AbilityClient, AbilityRosClient

    ability = AbilityClient(host=ip)
    ros = AbilityRosClient(host=ip)
    status = ability.status() or {}
    program = status.get("current_program") or {}
    snap = {
        "rest_state": status.get("state"),
        "rest_message": status.get("message") or "",
        "battery": status.get("battery"),
        "program_name": program.get("name"),
        "program_started_at": program.get("started_at"),
        "program_state": program.get("state"),
        "robot_pose": None,
        "base_position": None,
        "ros_program_state": None,
    }
    try:
        snap["robot_pose"] = ros.robot_pose()
    except Exception as exc:
        snap["robot_pose"] = f"<error: {exc}>"
    try:
        snap["base_position"] = ros.base_position()
    except Exception as exc:
        snap["base_position"] = f"<error: {exc}>"
    try:
        snap["ros_program_state"] = ros.program_state()
    except Exception as exc:
        snap["ros_program_state"] = {"error": str(exc)}
    return snap


def format_cell_snapshot(snap: dict) -> str:
    ros = snap.get("ros_program_state") or {}
    executing = ros.get("executing_name") if isinstance(ros, dict) else None
    return (
        f"REST={snap.get('rest_state')!r} RobotPose={snap.get('robot_pose')!r} "
        f"BasePosition={snap.get('base_position')!r} program={snap.get('program_name')!r} "
        f"started_at={snap.get('program_started_at')!r} executing={executing!r}"
    )


def retry_request(max_retries=3, timeout=10):
    """
    Decorator to retry HTTP requests with timeout.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        timeout: Request timeout in seconds (default: 10)
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    if hasattr(self, "_make_request_with_timeout"):
                        return self._make_request_with_timeout(
                            func, timeout, *args, **kwargs
                        )
                    return func(self, *args, **kwargs)
                except (requests.exceptions.RequestException, ValueError) as e:
                    last_exception = e
                    if attempt < max_retries:
                        _mra_trace(
                            "%s failed (attempt %d/%d, timeout=%ss): %s; retrying",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            timeout,
                            e,
                        )
                        time.sleep(1)
                        continue
                    _mra_trace(
                        "%s failed after %d attempts (timeout=%ss): %s",
                        func.__name__,
                        max_retries + 1,
                        timeout,
                        e,
                    )
                    raise last_exception

            return None

        return wrapper

    return decorator


class MobileRobotArm():
    """
    Mobile Robot Arm.
    """

    def __init__(self, ip: str = "192.168.1.207", timeout: int = 10, max_retries: int = 3):
        self.ip = ip
        self.timeout = timeout
        self.max_retries = max_retries
        self._trace_last_state = None
        self._trace_last_battery = None
        _mra_trace("connected to Ability at %s", ip)
        self.state, self.message = self.get_state_and_message()
        self.battery_level = self.get_battery_level()

    def _make_request_with_timeout(self, func, timeout, *args, **kwargs):
        """Helper method to make requests with timeout."""
        return func(self, *args, **kwargs)

    @retry_request(max_retries=3, timeout=10)
    def request_status(self) -> dict:
        """
        Request the status of the MRA.
        """
        url = f"http://{self.ip}:8082/v2/status"
        started_at = time.monotonic()
        response = requests.get(url, timeout=self.timeout)
        duration = time.monotonic() - started_at
        if response.status_code != 200:
            raise ValueError(
                f"Failed to get status. Status code: {response.status_code}. Response: {response.text}"
            )
        payload = response.json()
        if duration >= 1.0:
            _mra_trace(
                "status poll slow (%.2fs) state=%s battery=%s",
                duration,
                payload.get("state"),
                payload.get("battery"),
            )
        return payload

    def _trace_state_change(self, state: MRAState, message: str, battery: float | None = None) -> None:
        state_changed = state != self._trace_last_state
        battery_changed = (
            battery is not None
            and self._trace_last_battery is not None
            and abs(battery - self._trace_last_battery) >= 5
        )
        if state_changed or battery_changed or self._trace_last_state is None:
            if battery is None:
                _mra_trace("state=%s message=%r", state, message)
            else:
                _mra_trace(
                    "state=%s battery=%s%% message=%r",
                    state,
                    battery,
                    message,
                )
            self._trace_last_state = state
            if battery is not None:
                self._trace_last_battery = battery

    def get_state_and_message(self) -> tuple[MRAState, str]:
        """
        Return the state of the MRA and the message if there is any.
        This is the API documentation:
        https://docs.alabos.com/alabOS/api/mobile-robot-arm/
        """
        response = self.request_status()
        state = response["state"]
        message = response.get("message") or ""
        if state in IDLE_STATES:
            parsed = MRAState.IDLE, message
        elif state in RUNNING_STATES:
            parsed = MRAState.RUNNING, message
        elif state in SAFEGUARD_STATES:
            parsed = MRAState.SAFEGUARD_STOP, message
        elif state in ERROR_STATES:
            # The controller's own message is the only description of what actually failed, so it
            # is kept and labelled with the state rather than replaced.
            parsed = MRAState.ERROR, f"{state}: {message}" if message else state
        else:
            parsed = (
                MRAState.ERROR,
                f"{state}: {message}" if message else
                f"Unrecognised state {state!r}. See "
                "https://docs.alabos.com/alabOS/api/mobile-robot-arm/ for the full list of states.",
            )
        self._trace_state_change(
            parsed[0],
            parsed[1],
            float(response.get("battery", 0)),
        )
        return parsed

    @retry_request(max_retries=3, timeout=10)
    def acknowledge_error(self):
        raw = self.request_status()
        state = raw.get("state")
        if state in IDLE_STATES:
            # PUT Ready from Idle is rejected as "couldn't process event: Stop".
            _mra_trace("acknowledge_error skipped; controller is already %s", state)
            return
        _mra_trace("acknowledging error")
        time.sleep(5)
        response = requests.put(
            f"http://{self.ip}:8082/v2/status",
            json={"state": "Ready"},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise ValueError(
                f"Failed to acknowledge error. Status code: {response.status_code}. Response: {response.text}"
            )
        _mra_trace("error acknowledged")

    def get_battery_level(self) -> float:
        response = self.request_status()
        return float(response["battery"])

    def get_current_program(self) -> dict:
        response = self.request_status()
        return response["current_program"]

    @retry_request(max_retries=3, timeout=10)
    def load_program(self, program_name: str, arguments: list[dict]):
        _mra_trace("loading program %s (%d args)", program_name, len(arguments))
        response = requests.put(
            f"http://{self.ip}:8082/v2/programs/current",
            json={"name": program_name, "arguments": arguments},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            if response.status_code == 400 and "ActivateProgramming" in response.text:
                _mra_trace(
                    "load_program ActivateProgramming response; acknowledging error and retrying"
                )
                try:
                    self.acknowledge_error()
                except Exception:
                    pass
                finally:
                    time.sleep(5)
                    self.load_program(program_name, arguments)
                    return
            raise ValueError(
                f"Failed to load program. Status code: {response.status_code}. Response: {response.text}"
            )
        _mra_trace("loaded program %s", program_name)

    @retry_request(max_retries=3, timeout=10)
    def start_program(self):
        current_state = self.get_state_and_message()[0]
        if current_state != MRAState.IDLE:
            if self.is_running():
                _mra_trace(
                    "start_program waiting up to 30s for MRA to stop (current_state=%s)",
                    current_state,
                )
                patience = 30
                while self.is_running() and patience > 0:
                    patience -= 1
                    time.sleep(1)
                if patience == 0:
                    raise ValueError(
                        f"The MRA is still running after 30 seconds. Current state: {self.get_state_and_message()[0]}"
                    )
            else:
                raise ValueError(
                    f"The MRA must be in IDLE state to start a program. Current state: {current_state}"
                )
        _mra_trace("starting program")
        response = requests.put(
            f"http://{self.ip}:8082/v2/status",
            json={"state": "Executing"},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise ValueError(
                f"Failed to start program. Status code: {response.status_code}. Response: {response.text}"
            )
        _mra_trace("program started")

    def wait_until_running(self, timeout: float = 10.0) -> None:
        """Fail if Ability accepted start but never entered Executing.

        A 200 from PUT Executing is not enough: Main can stay Idle when the
        loaded program is a no-op (target already equals BasePosition) or when
        start did not take. The logs then look like a successful 8s move.
        """
        deadline = time.monotonic() + timeout
        last_state = None
        last_message = ""
        while time.monotonic() < deadline:
            last_state, last_message = self.get_state_and_message()
            if last_state == MRAState.RUNNING:
                _mra_trace("wait_until_running saw %s", last_state)
                return
            if last_state == MRAState.ERROR:
                raise ValueError(
                    f"Program entered error before it started running. Message: {last_message}"
                )
            time.sleep(0.25)
        program = None
        try:
            program = self.get_current_program()
        except Exception:
            pass
        extra = ""
        try:
            extra = " " + format_cell_snapshot(ability_cell_snapshot(self.ip))
        except Exception:
            pass
        raise ValueError(
            f"Main was told to start but the controller stayed "
            f"{last_state.name if last_state is not None else 'unknown'} "
            f"(message={last_message!r}, program={program!r}). "
            "The robot did not move."
            f"{extra}"
        )

    @retry_request(max_retries=3, timeout=10)
    def stop_program(self):
        _mra_trace("stopping program")
        response = requests.put(
            f"http://{self.ip}:8082/v2/status",
            json={"state": "Ready"},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise ValueError(
                f"Failed to stop program. Status code: {response.status_code}. Response: {response.text}"
            )
        _mra_trace("program stopped")

    def load_main_program(
        self,
        target_base_position: str,
        source_region: str,
        source_slot: str,
        destination_region: str,
        destination_slot: str,
    ):
        arguments = [
            {"name": "target_base_position", "type": 0, "value": target_base_position},
            {"name": "source_region", "type": 0, "value": source_region},
            {"name": "source_slot", "type": 0, "value": source_slot},
            {"name": "destination_region", "type": 0, "value": destination_region},
            {"name": "destination_slot", "type": 0, "value": destination_slot},
        ]
        _mra_trace(
            "load_main_program base=%s src=%s/%s dst=%s/%s",
            target_base_position,
            source_region,
            source_slot,
            destination_region,
            destination_slot,
        )
        self.load_program("Main", arguments)

    def is_running(self) -> bool:
        """
        Return True if the MRA is running.
        Safety stop is also considered as running.
        """
        self.state, self.message = self.get_state_and_message()
        if self.state == MRAState.SAFEGUARD_STOP:
            _mra_trace("is_running safeguard stop active; waiting up to 30s")
            for attempt in range(3):
                time.sleep(10)
                self.state, self.message = self.get_state_and_message()
                if self.state != MRAState.SAFEGUARD_STOP:
                    _mra_trace(
                        "is_running safeguard stop cleared after attempt %d state=%s",
                        attempt + 1,
                        self.state,
                    )
                    break
        return self.state == MRAState.RUNNING or self.state == MRAState.SAFEGUARD_STOP

    def is_error(self) -> bool:
        """
        Return True if the MRA is in error state.
        """
        return self.get_state_and_message()[0] == MRAState.ERROR

    def wait_for_program_to_finish(self):
        started_at = time.monotonic()
        poll_count = 0
        last_logged_state = None

        while self.is_running():
            poll_count += 1
            if (
                _should_trace_mobile_robot()
                and poll_count % int(MRA_POLL_LOG_INTERVAL_SECONDS) == 0
            ):
                state, message = self.state, self.message
                if state != last_logged_state:
                    _mra_trace(
                        "wait_for_program state=%s message=%r (%.0fs elapsed)",
                        state,
                        message,
                        time.monotonic() - started_at,
                    )
                    last_logged_state = state
            time.sleep(1)

        while self.is_running():
            poll_count += 1
            time.sleep(1)

        self.state, self.message = self.get_state_and_message()
        if self.state == MRAState.SAFEGUARD_STOP:
            _mra_trace("wait_for_program finished with safeguard stop; waiting up to 30s")
            for _ in range(3):
                time.sleep(10)
                self.state, self.message = self.get_state_and_message()
                if self.state != MRAState.SAFEGUARD_STOP:
                    break
            if self.state == MRAState.SAFEGUARD_STOP:
                raise ValueError(
                    f"Program finished with safeguard stop. Message: {self.message}"
                )
        if self.state == MRAState.ERROR:
            raise ValueError(f"Program finished with error. Message: {self.message}")
        elif self.state == MRAState.IDLE:
            _mra_trace(
                "wait_for_program complete state=%s (%.2fs total)",
                self.state,
                time.monotonic() - started_at,
            )
        else:
            raise ValueError(
                f"Unknown state: {self.state}. Please check the API documentation for the full list of states."
            )

    def _reject_stale_base_position(self, claimed: str | None, live, ros=None) -> str | None:
        """Align BasePosition with the live pose, or refuse Main if we cannot.

        BasePosition is a persisted Ability variable. Main writes it when a station
        approach finishes, and never again until the next one. A pendant dock or a
        cancelled move leaves the last station name in place. Main then retreats
        as if it were still there.

        The charging dock is uniquely identifiable from the live pose, so a stale
        station name there is rewritten to Charging. Any other mismatch is still
        refused: we do not guess a workstation.
        """
        from alab_control.mobile_robot_mir250.poses import StationPoses

        if not claimed or claimed in ("Unknown", "None"):
            return None
        poses = StationPoses()
        on_recorded_charger = poses.charger is not None and not poses.check_charger(live)
        on_recorded_charging = (
            poses.known("Charging") is not None and not poses.check("Charging", live)
        )
        on_charger = on_recorded_charger or on_recorded_charging
        if on_charger and claimed not in ("Charging", "ChargingNoWait"):
            if ros is None:
                raise ValueError(
                    f"BasePosition is {claimed!r} but the live pose is the charging dock "
                    f"(Ability Base x={live.x:.3f} y={live.y:.3f}, "
                    f"yaw={live.yaw_deg:.1f} deg). Main last wrote {claimed} when it "
                    "arrived at that station and never updated the variable after the "
                    "robot was docked. Starting Main now would retreat as if leaving "
                    f"{claimed}. Update BasePosition to Charging to match the dock; "
                    "do not start a base move until it does."
                )
            logger.warning(
                "BasePosition is %r but the live pose is the charging dock "
                "(Ability Base x=%.3f y=%.3f, yaw=%.1f deg); persisting Charging",
                claimed,
                live.x,
                live.y,
                live.yaw_deg,
            )
            ros.edit_variable("BasePosition", "Charging")
            written = str(ros.base_position())
            if written not in ("Charging", "ChargingNoWait"):
                raise ValueError(
                    f"BasePosition is {claimed!r} but the live pose is the charging dock "
                    f"(Ability Base x={live.x:.3f} y={live.y:.3f}, "
                    f"yaw={live.yaw_deg:.1f} deg). Tried to persist Charging but it "
                    f"reads {written!r}. Do not start a base move until it matches."
                )
            return written
        mismatch = poses.check(claimed, live)
        if mismatch:
            raise ValueError(
                f"BasePosition is {claimed!r} but {mismatch}. "
                "Main would drive the retreat for a station the robot is not in."
            )
        return None

    def _prepare_for_main(self, target_base_position: str) -> dict:
        """Settle Ability to Idle and refuse a base move Main cannot run."""
        snap: dict = {}
        try:
            from alab_control.mobile_robot_mir250.clients import (
                AbilityClient,
                AbilityRosClient,
            )

            ability = AbilityClient(host=self.ip)
            ros = AbilityRosClient(host=self.ip)
            state = str((ability.status() or {}).get("state", ""))
            if state == "Recovery":
                logger.warning(
                    "Ability is in Recovery; releasing the stranded programming token"
                )
                ros.force_token_release()
                time.sleep(3)
            try:
                settled = ability.wait_until_loadable()
                logger.info("Ability settled to %s before loading Main", settled)
            except Exception as exc:
                logger.warning("Ability did not settle to Idle before load: %s", exc)
            snap = ability_cell_snapshot(self.ip)
        except Exception as exc:
            logger.warning("Could not snapshot Ability before Main: %s", exc)
            return snap

        logger.info("Ability before Main: %s", format_cell_snapshot(snap))
        try:
            live = ability.transform()
            corrected = self._reject_stale_base_position(
                snap.get("base_position"), live, ros
            )
            if corrected:
                snap["base_position"] = corrected
        except ValueError:
            raise
        except Exception as exc:
            logger.warning("Could not reconcile BasePosition with the live pose: %s", exc)
        base_move = target_base_position not in (None, "None", "none", "")
        pose = snap.get("robot_pose")
        if (
            base_move
            and pose not in (None, "Home")
            and not str(pose).startswith("<error")
        ):
            raise ValueError(
                f"Main will not move the base: RobotPose is {pose!r} (need Home), "
                f"BasePosition is {snap.get('base_position')!r}, "
                f"Ability is {snap.get('rest_state')!r}. "
                "The arm is not at Home. Run HomeRobotArm so the arm actually "
                "folds, then retry. Do not mark RobotPose=Home unless the fold finished."
            )
        return snap

    def run_main_program(
        self,
        target_base_position: str,
        source_region: str,
        source_slot: str,
        destination_region: str,
        destination_slot: str,
    ):
        _mra_trace(
            "run_main_program start base=%s src=%s/%s dst=%s/%s",
            target_base_position,
            source_region,
            source_slot,
            destination_region,
            destination_slot,
        )
        started_at = time.monotonic()
        while self.is_running():
            patience = 30
            while self.is_running() and patience > 0:
                patience -= 1
                time.sleep(1)
            if patience == 0:
                raise ValueError(
                    f"The MRA is still running after 30 seconds. Current state: {self.get_state_and_message()[0]}"
                )
        self._prepare_for_main(target_base_position)
        self.load_main_program(
            target_base_position,
            source_region,
            source_slot,
            destination_region,
            destination_slot,
        )
        try:
            loaded = self.get_current_program()
            _mra_trace("run_main_program loaded Main current_program=%r", loaded)
        except Exception:
            _mra_trace("run_main_program loaded Main; could not read current_program")
        _mra_trace("run_main_program loaded Main; waiting 3s")
        time.sleep(3)
        self.start_program()
        self.wait_until_running()
        running_started_at = time.monotonic()
        self.wait_for_program_to_finish()
        ran_for = time.monotonic() - running_started_at
        arm_only = target_base_position in (None, "None", "none") and source_region not in (
            None,
            "None",
            "none",
        )
        if arm_only and ran_for < 5.0:
            raise ValueError(
                f"Main returned to idle after {ran_for:.1f}s for an arm move "
                f"{source_region}/{source_slot} -> {destination_region}/{destination_slot}. "
                "A real pick or place takes much longer; the robot did not move."
            )
        _mra_trace(
            "run_main_program complete (%.2fs total, %.2fs after running)",
            time.monotonic() - started_at,
            ran_for,
        )

    def charge(self):
        self.run_main_program("Charging", "None", "None", "None", "None")

    def charge_no_waiting(self):
        self.run_main_program("ChargingNoWait", "None", "None", "None", "None")

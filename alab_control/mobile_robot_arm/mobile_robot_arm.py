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
        if state == "Idle" or state == "Ready":
            parsed = MRAState.IDLE, response["message"]
        elif state == "Executing":
            parsed = MRAState.RUNNING, response["message"]
        elif state == "Execution Error Active":
            parsed = MRAState.ERROR, response["message"]
        elif state == "Finishing Execution":
            parsed = MRAState.RUNNING, response["message"]
        elif state == "Emergency Stop Active":
            parsed = MRAState.ERROR, response["message"]
        elif state == "Safeguard Stop Active":
            parsed = MRAState.SAFEGUARD_STOP, response["message"]
        else:
            parsed = (
                MRAState.ERROR,
                f"Unknown state: {state}. Please check the API documentation for the full list of states.",
            )
        self._trace_state_change(
            parsed[0],
            parsed[1],
            float(response.get("battery", 0)),
        )
        return parsed

    @retry_request(max_retries=3, timeout=10)
    def acknowledge_error(self):
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
        self.load_main_program(
            target_base_position,
            source_region,
            source_slot,
            destination_region,
            destination_slot,
        )
        _mra_trace("run_main_program loaded Main; waiting 3s")
        time.sleep(3)
        self.start_program()
        _mra_trace("run_main_program started; waiting 3s before polling")
        time.sleep(3)
        self.wait_for_program_to_finish()
        _mra_trace(
            "run_main_program complete (%.2fs total)",
            time.monotonic() - started_at,
        )

    def charge(self):
        self.run_main_program("Charging", "None", "None", "None", "None")

    def charge_no_waiting(self):
        self.run_main_program("ChargingNoWait", "None", "None", "None", "None")

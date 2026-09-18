import json
import time
from enum import Enum
from functools import wraps

import requests

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
                    # Add timeout to requests if it's a requests call
                    if hasattr(self, '_make_request_with_timeout'):
                        return self._make_request_with_timeout(func, timeout, *args, **kwargs)
                    else:
                        return func(self, *args, **kwargs)
                except (requests.exceptions.RequestException, ValueError) as e:
                    last_exception = e
                    if attempt < max_retries:
                        time.sleep(1)  # Wait 1 second before retry
                        continue
                    else:
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
        response = requests.get(f"http://{self.ip}:8082/v2/status", timeout=self.timeout)
        if response.status_code != 200:
            raise ValueError(f"Failed to get status. Status code: {response.status_code}. Response: {response.text}")
        return response.json()

    def get_state_and_message(self) -> tuple[MRAState, str]:
        """
        Return the state of the MRA and the message if there is any.
        This is the API documentation:
        https://docs.alabos.com/alabOS/api/mobile-robot-arm/
        """
        # send a get request to http://192.168.1.207:8082/v2/status
        # this is an example response:
        # {
        #     "state": "Idle",
        #     "current_program": {
        #         "name": "Initialize",
        #         "id": "",
        #         "arguments": [],
        #         "started_at": "",
        #         "completed_at": "",
        #         "state": 0,
        #         "state_text": "",
        #         "message": "",
        #         "in_line_program": "",
        #         "webhook": {
        #             "uri": "",
        #             "context": ""
        #         }
        #     },
        #     "battery": 100,
        #     "message": ""
        # }
        response = self.request_status()
        state = response["state"]
        if state == "Idle" or state == "Ready":
            return MRAState.IDLE, response["message"]
        elif state == "Executing":
            return MRAState.RUNNING, response["message"]
        elif state == "Execution Error Active":
            return MRAState.ERROR, response["message"]
        elif state == "Finishing Execution":
            return MRAState.RUNNING, response["message"]
        elif state == "Emergency Stop Active":
            return MRAState.ERROR, response["message"]
        elif state == "Safeguard Stop Active":
            return MRAState.SAFEGUARD_STOP, response["message"]
        else:
            return MRAState.ERROR, f"Unknown state: {state}. Please check the API documentation for the full list of states."
        
    @retry_request(max_retries=3, timeout=10)
    def acknowledge_error(self):
        """Clear a latched Ability error.

        The Ability UI clears many faults by flipping Automatic on then immediately
        back to Manual. Do that first, then request Ready over REST.
        """
        self.clear_error_with_auto_manual_handshake()
        time.sleep(5)  # wait for the MRA to accept the Ready transition
        response = requests.put(
            f"http://{self.ip}:8082/v2/status", json={"state": "Ready"}, timeout=self.timeout
        )
        if response.status_code != 200:
            raise ValueError(
                f"Failed to acknowledge error. Status code: {response.status_code}. "
                f"Response: {response.text}"
            )
        self.ensure_manual_mode()        
    def get_battery_level(self) -> float:
        # send a get request to http://192.168.1.207:8082/v2/status
        # this is an example response:
        # {
        #     "battery": 100
        # }
        response = self.request_status()
        return float(response["battery"])
    
    def get_current_program(self) -> dict:
        # send a get request to http://192.168.1.207:8082/v2/status
        response = self.request_status()
        return response["current_program"]
    
    @retry_request(max_retries=3, timeout=10)
    def load_program(self, program_name: str, arguments: list[dict]):
        # send a put request to http://192.168.1.207:8082/v2/programs/current with the following body example:
        # {
        #     "name": "string",
        #     "arguments": [
        #         {
        #             "name": "string",
        #             "type": 0,
        #             "value": "string"
        #         }
        #     ]
        # }
        response = requests.put(f"http://{self.ip}:8082/v2/programs/current", json={"name": program_name, "arguments": arguments}, timeout=self.timeout)
        if response.status_code != 200:
            # if status code is 400 and response contains "ActivateProgramming", try again after acknowledging the error
            if response.status_code == 400 and "ActivateProgramming" in response.text:
                try:
                    self.acknowledge_error()
                except Exception as e:
                    pass
                finally:
                    time.sleep(5) # wait for 5 seconds to make sure the MRA is ready to load the program
                    self.load_program(program_name, arguments)
                    return
            raise ValueError(f"Failed to load program. Status code: {response.status_code}. Response: {response.text}")
        
    @retry_request(max_retries=3, timeout=10)
    def start_program(self):
        # send a put request to http://192.168.1.207:8082/v2/status with the following body:
        # {
        #     "state": "Executing"
        # }
        # check the state before sending the request. The state must be IDLE.
        if self.get_state_and_message()[0] != MRAState.IDLE:
            if self.is_running():
                # if it is still running, wait for maximum 30 seconds and try again
                patience = 30
                while self.is_running() and patience > 0:
                    patience -= 1
                    time.sleep(1)
                if patience == 0:
                    raise ValueError(f"The MRA is still running after 30 seconds. Current state: {self.get_state_and_message()[0]}")
            else:
                raise ValueError(f"The MRA must be in IDLE state to start a program. Current state: {self.get_state_and_message()[0]}")
        response = requests.put(f"http://{self.ip}:8082/v2/status", json={"state": "Executing"}, timeout=self.timeout)
        if response.status_code != 200:
            raise ValueError(f"Failed to start program. Status code: {response.status_code}. Response: {response.text}")
        
    @retry_request(max_retries=3, timeout=10)
    def stop_program(self):
        # send a put request to http://192.168.1.207:8082/v2/status with the following body:
        # {
        #     "state": "Ready"
        # }
        response = requests.put(f"http://{self.ip}:8082/v2/status", json={"state": "Ready"}, timeout=self.timeout)
        if response.status_code != 200:
            raise ValueError(f"Failed to stop program. Status code: {response.status_code}. Response: {response.text}")
        
    def load_main_program(self, target_base_position: str, source_region: str, source_slot: str, destination_region: str, destination_slot: str):
        # use self.load_program to load the robot_arm_program with the following arguments template:
        # arguments =[{"name": "target_base_position", "type": 0, "value": target_base_position}, 
        # {"name": "robot_arm_job", "type": 0, "value": robot_arm_job},
        # {"name": "robot_arm_region", "type": 0, "value": robot_arm_region},
        # {"name": "robot_arm_slot", "type": 0, "value": robot_arm_slot}]
        arguments = [{"name": "target_base_position", "type": 0, "value": target_base_position}, 
                     {"name": "source_region", "type": 0, "value": source_region},
                     {"name": "source_slot", "type": 0, "value": source_slot},
                     {"name": "destination_region", "type": 0, "value": destination_region},
                     {"name": "destination_slot", "type": 0, "value": destination_slot}]
        self.load_program("Main", arguments)

    def is_running(self) -> bool:
        """
        Return True if the MRA is running.
        Safety stop is also considered as running.
        """
        # if the state is SAFEGUARD_STOP, wait for 10 seconds and try check again, try 3 times
        self.state, self.message = self.get_state_and_message()
        if self.state == MRAState.SAFEGUARD_STOP:
            for _ in range(3):
                time.sleep(10)
                self.state, self.message = self.get_state_and_message()
                if self.state != MRAState.SAFEGUARD_STOP:
                    break
        return self.state == MRAState.RUNNING or self.state == MRAState.SAFEGUARD_STOP
    
    def is_error(self) -> bool:
        """
        Return True if the MRA is in error state.
        """
        return self.get_state_and_message()[0] == MRAState.ERROR

    def wait_for_program_to_finish(self):
        # wait for the program to finish.
        while self.is_running():
            time.sleep(1)
        # sometimes somehow the program is not finished yet but the is_running suddenly returns False.
        # so we need to check again and wait until the program is finished.
        while self.is_running():
            time.sleep(1)
        self.state, self.message = self.get_state_and_message()
        # if the state is SAFEGUARD_STOP, wait for 10 seconds and try check again, try 3 times
        if self.state == MRAState.SAFEGUARD_STOP:
            for _ in range(3):
                time.sleep(10)
                self.state, self.message = self.get_state_and_message()
                if self.state != MRAState.SAFEGUARD_STOP:
                    break
            if self.state == MRAState.SAFEGUARD_STOP:
                raise ValueError(f"Program finished with safeguard stop. Message: {self.message}")
        # if the state is ERROR, raise an error
        if self.state == MRAState.ERROR:
            raise ValueError(f"Program finished with error. Message: {self.message}")
        elif self.state == MRAState.IDLE:
            pass
        else:
            raise ValueError(f"Unknown state: {self.state}. Please check the API documentation for the full list of states.")
        
    def wait_until_loadable(self):
        """Wait until a previous run has finished so the next load can be accepted.

        Ability rejects ``ActivateProgramming`` while stuck in ``Ready`` with a
        stranded programming token. Release the token once, then wait for Idle.
        Also ensures Ability stays in Manual (Automatic off). Code-driven control runs
        with Automatic off; the Auto→Manual toggle is only used to clear latched errors.
        """
        patience = 30
        while self.is_running() and patience > 0:
            patience -= 1
            time.sleep(1)
        if patience == 0:
            raise ValueError(
                f"The MRA is still running after 30 seconds. "
                f"Current state: {self.get_state_and_message()[0]}"
            )
        state, _ = self.get_state_and_message()
        if state == MRAState.IDLE:
            # Ready is also mapped to IDLE by get_state_and_message; distinguish via REST.
            raw = self.request_status().get("state")
            if raw == "Ready":
                self._force_token_release()
                time.sleep(1)
        self.ensure_manual_mode()

    def _call_ros_service(self, service: str, args: dict | None = None) -> dict | None:
        """Call one Ability rosbridge service; return the response values or None."""
        try:
            import websocket
        except ImportError:
            return None
        sid = "mra"
        try:
            ws = websocket.create_connection(f"ws://{self.ip}:9090", timeout=self.timeout)
            ws.send(
                json.dumps(
                    {
                        "op": "call_service",
                        "id": sid,
                        "service": service,
                        "args": args or {},
                    }
                )
            )
            while True:
                msg = json.loads(ws.recv())
                if msg.get("op") == "service_response" and msg.get("id") == sid:
                    values = msg.get("values")
                    ws.close()
                    return values if isinstance(values, dict) else {}
        except Exception:
            return None
        return None

    def _force_token_release(self) -> None:
        """Clear a stranded programming token that leaves the controller in Ready."""
        self._call_ros_service("/ability_backend/program/force_token_release")

    def _system_region(self) -> str:
        """Current Ability ``system.region`` from ``/ability_backend/system_state``."""
        try:
            import websocket
        except ImportError:
            return ""
        try:
            ws = websocket.create_connection(f"ws://{self.ip}:9090", timeout=self.timeout)
            ws.send(
                json.dumps(
                    {
                        "op": "subscribe",
                        "id": "sys",
                        "topic": "/ability_backend/system_state",
                        "type": "state_machine_controller/SystemState",
                        "queue_length": 1,
                    }
                )
            )
            deadline = time.time() + min(float(self.timeout), 8.0)
            region = ""
            while time.time() < deadline:
                ws.settimeout(2)
                try:
                    msg = json.loads(ws.recv())
                except Exception:
                    continue
                if msg.get("op") == "publish" and msg.get("topic") == "/ability_backend/system_state":
                    system = (msg.get("msg") or {}).get("system") or {}
                    region = str(system.get("region") or "")
                    break
            try:
                ws.send(
                    json.dumps(
                        {
                            "op": "unsubscribe",
                            "id": "sys",
                            "topic": "/ability_backend/system_state",
                        }
                    )
                )
            except Exception:
                pass
            ws.close()
            return region
        except Exception:
            return ""

    def is_automatic_mode(self) -> bool:
        """True when the Ability dashboard Automatic switch would show as on."""
        return self._system_region() == "queue"

    def is_manual_mode(self) -> bool:
        """True when Automatic is off — the mode code-driven control should stay in."""
        return not self.is_automatic_mode()

    def set_automatic_mode(self, enabled: bool, *, release_token: bool = True) -> bool:
        """Match the Ability UI Automatic toggle via activate/deactivate_queue."""
        if enabled:
            if release_token:
                self._force_token_release()
            self._call_ros_service("/ability_backend/system/activate_queue")
        else:
            self._call_ros_service("/ability_backend/system/deactivate_queue")
        deadline = time.time() + min(float(self.timeout), 10.0)
        while time.time() < deadline:
            if self.is_automatic_mode() is bool(enabled):
                return True
            time.sleep(0.2)
        return self.is_automatic_mode() is bool(enabled)

    def ensure_manual_mode(self) -> bool:
        """Leave Ability in Manual (Automatic off). No-op when already Manual."""
        try:
            if self.is_manual_mode():
                return True
            return self.set_automatic_mode(False)
        except Exception:
            return False

    def clear_error_with_auto_manual_handshake(self) -> bool:
        """Flip Automatic on, then immediately back to Manual — clears many latched faults.

        Code control must end in Manual. Returns True when Manual is restored.
        """
        try:
            self.set_automatic_mode(True)
            time.sleep(0.3)
            return self.set_automatic_mode(False)
        except Exception:
            try:
                return self.ensure_manual_mode()
            except Exception:
                return False

    def run_program(self, program_name: str, arguments: dict[str, str] | None = None):
        """Load a program by name, run it, and wait for it to finish.

        Used by the split programs, where each movement is its own program rather than a
        branch inside Main. Arguments are named and all string typed (type 0).
        """
        self.wait_until_loadable()
        self.load_program(
            program_name,
            [
                {"name": name, "type": 0, "value": str(value)}
                for name, value in (arguments or {}).items()
            ],
        )
        time.sleep(3)
        self.start_program()
        time.sleep(3)
        self.wait_for_program_to_finish()

    def run_main_program(self, target_base_position: str, source_region: str, source_slot: str, destination_region: str, destination_slot: str):
        self.wait_until_loadable()
        self.load_main_program(target_base_position, source_region, source_slot, destination_region, destination_slot)
        time.sleep(3)
        self.start_program()
        time.sleep(3)
        self.wait_for_program_to_finish()

    def is_actually_charging(self) -> bool | None:
        """Whether the MiR is drawing charge (``/mobile/is_charging``).

        Returns ``None`` when rosbridge is unreachable so callers can fall back.
        """
        values = self._call_ros_service("/mobile/is_charging")
        if values is None:
            return None
        if "response" in values:
            return bool(values.get("response"))
        if "data" in values:
            return bool(values.get("data"))
        return bool(values) if values else None

    def _charging_station_guid(self) -> str:
        """First charging-station GUID from Ability, or empty if none."""
        values = self._call_ros_service("/er/mobile/get_charging_stations")
        if not values:
            return ""
        stations = values.get("stations") or values.get("data") or values.get("response")
        if isinstance(stations, list) and stations:
            first = stations[0]
            if isinstance(first, dict):
                return str(first.get("guid") or first.get("id") or first.get("data") or "")
            return str(first)
        if isinstance(stations, dict):
            for value in stations.values():
                if isinstance(value, str) and value:
                    return value
                if isinstance(value, dict):
                    guid = value.get("guid") or value.get("id")
                    if guid:
                        return str(guid)
        for key in ("guid", "data", "id"):
            if values.get(key):
                return str(values[key])
        return ""

    def redock_on_charger(self) -> bool:
        """Dock via MiR's own charging mission (survives Ability program teardown)."""
        guid = self._charging_station_guid()
        if not guid:
            return False
        self._call_ros_service("/er/mobile/move_to_charging_station", {"data": guid})
        deadline = time.time() + 150.0
        while time.time() < deadline:
            if self.is_actually_charging() is True:
                return True
            time.sleep(3.0)
        return self.is_actually_charging() is True

    def settle_on_charge(
        self, *, settle_s: float = 25.0, redock_attempts: int = 1
    ) -> bool:
        """Confirm charging holds after a dock; redock over ROS if Ability aborts it.

        Ability often tears down the MiR docking mission after the program ends, so a
        single ``is_charging`` read right after ``charge_no_waiting`` can pass and then
        flip to Pause / not charging within ~30 s.
        """
        for attempt in range(redock_attempts + 1):
            stable_until = time.time() + max(0.0, float(settle_s))
            dropped = False
            while time.time() < stable_until:
                live = self.is_actually_charging()
                if live is False:
                    dropped = True
                    break
                time.sleep(2.0)
            if not dropped:
                live = self.is_actually_charging()
                if live is False:
                    dropped = True
                else:
                    return True
            if attempt >= redock_attempts:
                break
            if not self.redock_on_charger():
                break
        return self.is_actually_charging() is True

    def charge(self):
        self.run_main_program("Charging", "None", "None", "None", "None")

    def charge_no_waiting(self):
        self.run_main_program("ChargingNoWait", "None", "None", "None", "None")

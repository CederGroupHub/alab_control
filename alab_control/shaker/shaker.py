import time
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice


class ShakerState(Enum):
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    ON = "ON"
    OFF = "OFF"

class SystemState(Enum):
    RUNNING = "RUNNING"
    IDLE = "IDLE"
    ERROR = "ERROR"

class GripperState(Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"

class ShakerError(Exception):
    """
    Errors returned from shaker APIs
    """

class Shaker(BaseArduinoDevice):
    """
    Shaker machine for ball milling
    """

    FREQUENCY = 25 # the frequency of the shaker, user should set it in the ball milling machine manually for now.

    ENDPOINTS = {
        "close gripper": "/gripper-close",
        "open gripper": "/gripper-open",
        "start": "/start",
        "stop": "/stop",
        "state": "/state",
        "reset": "/reset",
    }

    def get_state(self) -> ShakerState:
        """
        Get current status of the shaker machine and the grabber
        """
        response = self.send_request(self.ENDPOINTS["state"], suppress_error=True, timeout=10, max_retries=5)
        if response["system_status"] == "ERROR":
            raise ShakerError("Shaker machine is in error state.")
        return response
    
    def is_gripper_closed(self) -> bool:
        """
        Check if the gripper is closed
        """
        state = self.get_state()
        if GripperState(state["gripper_status"]) == GripperState.CLOSE:
            return True
        return False

    def is_shaker_on(self) -> bool:
        """
        Check if the shaker machine is on
        """
        state = self.get_state()
        if ShakerState(state["shaker_status"]) == ShakerState.ON:
            return True
        return False

    def is_running(self) -> bool:
        """
        Check if the shaker machine is running
        """
        state = self.get_state()  # refresh the state
        if SystemState(state["system_status"]) == SystemState.RUNNING or \
        ShakerState(state["shaker_status"]) == ShakerState.ON:
            return True
        return False

    def close_gripper(self):
        """
        Close the gripper to hold the container
        """
        state = self.get_state()
        print(f"{self.get_current_time()} Grabbing the container")
        self.send_request(self.ENDPOINTS["close gripper"], suppress_error=True, timeout=10, max_retries=3)
        while not (GripperState(state["gripper_status"]) == GripperState.CLOSE):
            time.sleep(0.1)

    def open_gripper(self):
        """
        Open the gripper to release the container
        """
        state = self.get_state()
        print(f"{self.get_current_time()} Releasing the grabber")
        self.send_request(self.ENDPOINTS["open gripper"], suppress_error=True, timeout=10, max_retries=3)
        while GripperState(state["gripper_status"]) != GripperState.OPEN:
            time.sleep(0.1)

    def shaking(self, duration_sec: float, gripper_closed: bool = False):
        """
        Start the shaker machine for a given duration (seconds)

        Args:
            duration_sec: duration of shaking in seconds
        """
        start_time = time.time()
        print(f"{self.get_current_time()} Starting the shaker machine for {duration_sec} seconds")
        try:
            while time.time() - start_time < duration_sec:
                state=self.get_state()
                if GripperState(self.get_state()["gripper_status"]) != GripperState.CLOSE and gripper_closed:
                    if state["force_reading"] > 200:
                        self.stop()
                        raise ShakerError("Gripper is not closed or has lost grip.")
                if SystemState(state["system_status"]) == SystemState.ERROR:
                    self.stop()
                    raise ShakerError("Shaker machine is in error state.")
                self.start()
                time.sleep(5)
        finally:
            self.stop()

    def close_gripper_and_shake(self, duration_sec: int):
        """
        Grip the container, shake it and then release it.

        Args:
            duration_sec: duration of shaking in seconds
        """
        self.close_gripper()
        time.sleep(2)
        self.shaking(duration_sec=duration_sec, gripper_closed=True)
        time.sleep(3)
        self.open_gripper()

    def start(self):
        """
        Send a start command to the shaker machine
        """
        self.send_request(self.ENDPOINTS["start"], timeout=10, max_retries=3)

    def stop(self):
        """
        Send a stop command to the shaker machine
        """
        self.send_request(self.ENDPOINTS["stop"], timeout=10, max_retries=3)
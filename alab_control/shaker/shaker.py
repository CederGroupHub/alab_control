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

    def get_state(self):
        """
        Get current status of the shaker machine and the gripper
        """
        response = self.send_request(self.ENDPOINTS["state"], suppress_error=True, timeout=10, max_retries=5)
        time.sleep(1)
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
        state=self.get_state()
        print(f"{self.get_current_time()} Gripping the container")
        self.send_request(self.ENDPOINTS["close gripper"], suppress_error=True, timeout=10, max_retries=3)
        while not (GripperState(state["gripper_status"]) == GripperState.CLOSE):
            state = self.get_state()
            if SystemState(state["system_status"]) == SystemState.ERROR:
                raise ShakerError("Shaker machine is in error state. Failed to grip.")
            time.sleep(1)
        if int(state["force_reading"]) > 200:
            raise ShakerError("Gripper is not fully closed or has lost grip.")

    def open_gripper(self):
        """
        Open the gripper to release the container
        """
        state=self.get_state()
        print(f"{self.get_current_time()} Releasing the gripper")
        self.send_request(self.ENDPOINTS["open gripper"], suppress_error=True, timeout=10, max_retries=3)
        while not (GripperState(state["gripper_status"]) == GripperState.OPEN):
            state = self.get_state()
            if SystemState(state["system_status"]) == SystemState.ERROR:
                raise ShakerError("Shaker machine is in error state. Failed to release.")
            time.sleep(1)
        if int(state["force_reading"]) < 200:
            raise ShakerError("Gripper is not fully open or something is attached to the upper part.")

    def shaking(self, duration_sec: float):
        """
        Start the shaker machine for a given duration (seconds).
        This will initiate the stop command first to ensure the shaker is not running and to de-saturate the clicker.

        Args:
            duration_sec: duration of shaking in seconds
            gripper_closed: flag whether the gripper is expected to be closed gripping something or not.
                it is used to check if the gripper is gripping something while shaking.
        """
        self.stop()
        time.sleep(6)
        start_time = time.time()
        print(f"{self.get_current_time()} Starting the shaker machine for {duration_sec} seconds")
        try:
            while time.time() - start_time < duration_sec:
                state=self.get_state()
                if ShakerState(state["shaker_status"]) != ShakerState.STARTING:
                    if GripperState(self.get_state()["gripper_status"]) == GripperState.CLOSE:
                        if int(state["force_reading"]) > 200:
                            self.stop()
                            raise ShakerError("Gripper is not closed or has lost grip.")
                    if SystemState(state["system_status"]) == SystemState.ERROR:
                        self.stop()
                        raise ShakerError("Shaker machine is in error state.")
                    self.start()
                time.sleep(6)
        finally:
            while ShakerState(state["shaker_status"]) == ShakerState.STARTING:
                state=self.get_state()
                if SystemState(state["system_status"]) == SystemState.ERROR:
                    raise ShakerError("Shaker machine is in error state.")
                time.sleep(1)
            self.stop()

    def close_gripper_and_shake(self, duration_sec: int):
        """
        Grip the container, shake it and then release it.

        Args:
            duration_sec: duration of shaking in seconds
        """
        self.close_gripper()
        time.sleep(3)
        self.shaking(duration_sec=duration_sec)
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

    def reset(self):
        """
        Reset the shaker machine
        """
        self.send_request(self.ENDPOINTS["reset"], timeout=10, max_retries=3)
        time.sleep(8)
import time
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice


class EnderCapperRelayState(Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"

class EnderCapperRelay(BaseArduinoDevice):
    ENDPOINTS = {
        "state": "/state",
        "open-top-gripper": "/open-top-gripper",
        "close-top-gripper": "/close-top-gripper",
        "open-bottom-gripper": "/open-bottom-gripper",
        "close-bottom-gripper": "/close-bottom-gripper",
        "cw-motor": "/cw-motor",
        "ccw-motor": "/ccw-motor",
    }

    def __init__(self, ip_address: str, port: int = 80):
        super().__init__(ip_address, port)

    def get_state(self) -> EnderCapperRelayState:
        """
        Get the current state of the cap dispenser
        whether it is running or not.
        """
        state=str(self.send_request(self.ENDPOINTS["state"], method="GET", suppress_error=True, max_retries=10, timeout=10)["system_status"].upper())
        if state=="RUNNING":
            return EnderCapperRelayState.RUNNING
        elif state=="IDLE":
            return EnderCapperRelayState.STOPPED
        
    def open_top_gripper(self):
        """
        Open the top gripper
        """
        for i in range(3):
            self.send_request(self.ENDPOINTS["open-top-gripper"], method="GET", suppress_error=True, max_retries=10, timeout=10)

    def close_top_gripper(self):
        """
        Close the top gripper
        """
        for i in range(3):
            self.send_request(self.ENDPOINTS["close-top-gripper"], method="GET", suppress_error=True, max_retries=10, timeout=10)

    def open_bottom_gripper(self):
        """
        Open the bottom gripper
        """
        for i in range(3):
            self.send_request(self.ENDPOINTS["open-bottom-gripper"], method="GET", suppress_error=True, max_retries=10, timeout=10)

    def close_bottom_gripper(self):
        """
        Close the bottom gripper
        """
        for i in range(3):
            self.send_request(self.ENDPOINTS["close-bottom-gripper"], method="GET", suppress_error=True, max_retries=10, timeout=10)

    def cw_motor(self, rpm: int, revolutions: float):
        """
        Rotate the motor clockwise for a given speed and number of revolutions.
        rpm: the speed of the motor in rpm
        revolutions: the number of revolutions to rotate the motor
        """
        params = {"rpm": rpm, "rev": revolutions}
        self.send_request(
            self.ENDPOINTS["cw-motor"],
            method="GET",
            params=params,
            suppress_error=True,
            max_retries=10,
            timeout=10
        )
        # wait until state is IDLE
        while self.get_state() == EnderCapperRelayState.RUNNING:
            time.sleep(0.1)
        
    def ccw_motor(self, rpm: int, revolutions: float):
        """
        Rotate the motor counterclockwise for a given speed and number of revolutions.
        rpm: the speed of the motor in rpm
        revolutions: the number of revolutions to rotate the motor
        """
        params = {"rpm": rpm, "rev": revolutions}
        self.send_request(
            self.ENDPOINTS["ccw-motor"],
            method="GET",
            params=params,
            suppress_error=True,
            max_retries=10,
            timeout=10
        )
        # wait until state is IDLE
        while self.get_state() == EnderCapperRelayState.RUNNING:
            time.sleep(0.1)
        
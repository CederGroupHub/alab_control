from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice


class CapperState(Enum):
    OPEN = "open"
    CLOSE = "closed"


class Capper(BaseArduinoDevice):
    ENDPOINTS = {
        "state": "/state",
        "open": "/open",
        "close": "/close",
    }

    def get_state(self):
        """
        Get the current state of the capper
        """
        return CapperState[self.send_request(self.ENDPOINTS["state"], suppress_error=True, method="GET", max_retries=5, timeout=10)["state"].upper()]

    def open(self):
        """
        Open the capper
        """
        if self.get_state() == CapperState.OPEN:
            return
        self.send_request("/open", suppress_error=True, method="GET", timeout=30, max_retries=3)
        print(f"{self.get_current_time()} Opening Capping Gripper")

    def close(self):
        """
        Close the capper
        """
        if self.get_state() == CapperState.CLOSE:
            return
        self.send_request("/close", suppress_error=True, method="GET", timeout=30, max_retries=3)
        print(f"{self.get_current_time()} Closing Capping Gripper")
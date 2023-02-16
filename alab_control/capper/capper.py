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
        return CapperState[self.send_request(self.ENDPOINTS["state"], method="GET")["state"].upper()]

    def open(self):
        """
        Open the capper
        """
        if self.get_state() == CapperState.OPEN:
            return
        self.send_request("/open", method="GET", timeout=30, max_retries=3)

    def close(self):
        """
        Close the capper
        """
        if self.get_state() == CapperState.CLOSE:
            return
        self.send_request("/close", method="GET", timeout=30, max_retries=3)

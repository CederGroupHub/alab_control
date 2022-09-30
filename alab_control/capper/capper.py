from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice


class CapperState(Enum):
    OPEN = "open"
    CLOSED = "closed"


class Capper(BaseArduinoDevice):
    ENDPOINTS = {
        "state": "/state",
        "open": "/open",
        "close": "/close",
    }

    def __init__(self, ip_address: str, port: int = 80):
        super().__init__(ip_address, port)

    def get_state(self):
        """
        Get the current state of the capper
        """
        return CapperState(self.send_request(self.ENDPOINTS["state"], method="GET")["state"].upper())

    def open(self):
        """
        Open the capper
        """
        if self.get_state() == CapperState.OPEN:
            return
        self.send_request("/open", method="GET")
        self.state = CapperState.OPEN

    def close(self):
        """
        Close the capper
        """
        if self.get_state() == CapperState.CLOSED:
            return
        self.send_request("/close", method="GET")
        self.state = CapperState.CLOSED

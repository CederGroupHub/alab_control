from enum import Enum
import time
from alab_control._base_arduino_device import BaseArduinoDevice


class CapperState(Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"

class Capper(BaseArduinoDevice):
    ENDPOINTS = {
        "state": "/state",
        "open": "/open",
        "close": "/close",
    }
    def __init__(self, ip_address: str, port: int = 80):
        super().__init__(ip_address, port)
        self.is_open = True

    def get_state(self):
        """
        Get the current state of the capper
        """
        return CapperState[self.send_request(self.ENDPOINTS["state"], method="GET", suppress_error=True, max_retries=3, timeout=1)["state"].upper()]

    def open(self):
        """
        Open the capper
        """
        if self.get_state() == CapperState.RUNNING:
            raise RuntimeError("Cannot open the capper while it is running")
        if self.is_open:
            raise RuntimeError("Cannot open the capper while it is open")
        self.send_request(self.ENDPOINTS["open"], method="GET", suppress_error=True, max_retries=3, timeout=1)
        while self.get_state() == CapperState.RUNNING:
            time.sleep(0.2)
        self.is_open = True

    def close(self):
        """
        Close the capper
        """
        if self.get_state() == CapperState.RUNNING:
            raise RuntimeError("Cannot open the capper while it is running")
        if not self.is_open:
            raise RuntimeError("Cannot close the capper while it is closed")
        self.send_request(self.ENDPOINTS["close"], method="GET", suppress_error=True, max_retries=3, timeout=1)
        while self.get_state() == CapperState.RUNNING:
            time.sleep(0.2)
        self.is_open = False

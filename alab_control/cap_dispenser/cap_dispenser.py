import time
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice


class CapDispenserState(Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"

class CapDispenser(BaseArduinoDevice):
    MAP ={
        "A":1,
        "B":2,
        "C":3,
        "D":4
    }
    ENDPOINTS = {
        "state": "/state",
        "open n=1": "/open?n=1",
        "open n=2": "/open?n=2",
        "open n=3": "/open?n=3",
        "open n=4": "/open?n=4",
        "close n=1": "/close?n=1",
        "close n=2": "/close?n=2",
        "close n=3": "/close?n=3",
        "close n=4": "/close?n=4",
    }

    def __init__(self, ip_address: str, port: int = 80):
        super().__init__(ip_address, port)
        self.names=["A","B","C","D"]

    def get_state(self) -> CapDispenserState:
        """
        Get the current state of the cap dispenser
        whether it is running or not.
        """
        return CapDispenserState[self.send_request(self.ENDPOINTS["state"], method="GET", suppress_error=True, max_retries=10, timeout=10)["state"].upper()]

    def open(self, name: str):
        """
        Open the cap dispenser
        """
        if name not in self.names:
            raise ValueError("name must be one of the specified names in the initialization"+str(self.names))
        if self.get_state() == CapDispenserState.RUNNING:
            raise RuntimeError("Cannot open the cap dispenser while it is running")
        print(f"{self.get_current_time()} Opening a cap dispenser")
        self.send_request(self.ENDPOINTS[f"open n={self.MAP[name]}"], method="GET", suppress_error=True, max_retries=10, timeout=10)
        time.sleep(0.2)
        while self.get_state() == CapDispenserState.RUNNING:
            time.sleep(0.2)

    def close(self, name: str):
        """
        Close the cap dispenser
        """
        if name not in self.names:
            raise ValueError("name must be one of the specified names in the initialization"+str(self.names))
        if self.get_state() == CapDispenserState.RUNNING:
            raise RuntimeError("Cannot open the cap dispenser while it is running")
        print(f"{self.get_current_time()} Closing a cap dispenser")
        self.send_request(self.ENDPOINTS[f"close n={self.MAP[name]}"], method="GET", suppress_error=True, max_retries=10, timeout=10)
        time.sleep(0.2)
        while self.get_state() == CapDispenserState.RUNNING:
            time.sleep(0.2)

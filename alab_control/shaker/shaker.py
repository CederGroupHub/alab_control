import time
from enum import IntEnum

from alab_control._base_arduino_device import BaseArduinoDevice


class ShakerState(IntEnum):
    OPEN_STOPPED = 0  # 00
    OPEN_RUNNING = 1  # 01
    CLOSE_STOPPED = 2  # 10
    CLOSE_RUNNING = 3  # 11

    def is_grabber_closed(self) -> bool:
        return self.value & 1 == 1

    def is_shaker_running(self) -> bool:
        return self.value & 2 == 2


class ShakerError(Exception):
    """
    Errors returned from shaker APIs
    """


class Sheaker(BaseArduinoDevice):
    """
    Shaker machine for ball milling
    """

    # TODO: edit this after Bernard finishes
    ENDPOINTS = {
        "grab": "/open",
        "release": "/close",
        "start": "/start",
        "stop": "/stop",
        "state": "/state",
    }

    def __init__(self, ip_address, port: int = 80):
        super().__init__(ip_address, port)
        self.state: ShakerState = ShakerState.OPEN_STOPPED

    def is_running(self) -> bool:
        """
        Check if the shaker machine is running
        """
        self.get_state()  # refresh the state
        return self.state.is_shaker_running()

    def get_state(self) -> ShakerState:
        """
        Get current status of the shaker machine and the grabber
        """
        response = self.send_request(self.ENDPOINTS["state"])
        self.state = ShakerState(f"{response['grabber']}_{response['state']}")
        return self.state

    def grab(self):
        self.get_state()
        if self.state.is_grabber_closed():
            raise ShakerError("Grabber is already closed")
        self.send_request(self.ENDPOINTS["grab"])
        time.sleep(3)  # wait for the grabber to close
        self.get_state()

    def release(self):
        self.get_state()
        if not self.state.is_grabber_closed():
            raise ShakerError("Grabber is already open")
        self.send_request(self.ENDPOINTS["grab"])
        time.sleep(2)  # wait for the grabber to open
        self.get_state()

    def start(self):
        self.send_request(self.ENDPOINTS["start"])
        self.get_state()

    def stop(self):
        self.send_request(self.ENDPOINTS["stop"])
        self.get_state()

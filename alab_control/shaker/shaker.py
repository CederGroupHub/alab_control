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


class Shaker(BaseArduinoDevice):
    """
    Shaker machine for ball milling
    """

    FREQUENCY = 30  # the frequency of the shaker, user should set it in the ball milling machine manually for now.

    ENDPOINTS = {
        "grab": "/grabber-open",
        "release": "/grabber-close",
        "start": "/start",
        "stop": "/stop",
        "state": "/state",
    }

    def is_running(self) -> bool:
        """
        Check if the shaker machine is running
        """
        state = self.get_state()  # refresh the state
        return state.is_shaker_running()

    def get_state(self) -> ShakerState:
        """
        Get current status of the shaker machine and the grabber
        """
        response = self.send_request(self.ENDPOINTS["state"])
        self.state = ShakerState(f"{response['grabber'].upper()}_{response['state'].upper()}")
        return self.state

    def grab(self):
        """
        Close the grabber to hold the container
        """
        state = self.get_state()
        if state.is_grabber_closed():
            raise ShakerError("Grabber is already closed")
        self.send_request(self.ENDPOINTS["grab"])
        time.sleep(3)  # wait for the grabber to close
        while not self.get_state().is_grabber_closed():
            time.sleep(1)

    def release(self):
        """
        Open the grabber to release the container
        """
        state = self.get_state()
        if not state.is_grabber_closed():
            raise ShakerError("Grabber is already open")
        self.send_request(self.ENDPOINTS["grab"])
        time.sleep(1)  # wait for the grabber to open
        while self.get_state().is_grabber_closed():
            time.sleep(1)

    def shaking(self, duration_sec: int):
        """
        Start the shaker machine for a given duration (seconds)

        Args:
            duration_sec: duration of shaking in seconds
        """
        start_time = time.time()
        try:
            while time.time() - start_time < duration_sec:
                self.start()
                time.sleep(5)
        finally:
            stop()

    def start(self):
        """
        Send a start command to the shaker machine
        """
        self.send_request(self.ENDPOINTS["start"])

    def stop(self):
        """
        Send a stop command to the shaker machine
        """
        self.send_request(self.ENDPOINTS["stop"])

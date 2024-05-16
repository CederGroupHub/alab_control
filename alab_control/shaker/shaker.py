import time
from enum import IntEnum

from alab_control._base_arduino_device import BaseArduinoDevice


class ShakerState(IntEnum):
    OPEN_STOPPED = 0  # 00
    OPEN_RUNNING = 1  # 01
    CLOSE_STOPPED = 2  # 10
    CLOSE_RUNNING = 3  # 11

    def is_grabber_closed(self) -> bool:
        return self.value & 2 == 2

    def is_shaker_running(self) -> bool:
        return self.value & 1 == 1


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
        "grab": "/grabber-close",
        "release": "/grabber-open",
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
        response = self.send_request(self.ENDPOINTS["state"], suppress_error=True, timeout=10, max_retries=5)
        state = ShakerState[f"{response['grabber'].upper()}_{response['state'].upper()}"]
        return state

    def grab(self):
        """
        Close the grabber to hold the container
        """
        state = self.get_state()
        print(f"{self.get_current_time()} Grabbing the container")
        self.send_request(self.ENDPOINTS["grab"], suppress_error=True, timeout=10, max_retries=3)
        while not self.get_state().is_grabber_closed():
            time.sleep(0.1)

    def release(self):
        """
        Open the grabber to release the container
        """
        state = self.get_state()
        print(f"{self.get_current_time()} Releasing the grabber")
        self.send_request(self.ENDPOINTS["release"], suppress_error=True, timeout=10, max_retries=3)
        while self.get_state().is_grabber_closed():
            time.sleep(0.1)

    def shaking(self, duration_sec: float):
        """
        Start the shaker machine for a given duration (seconds)

        Args:
            duration_sec: duration of shaking in seconds
        """
        start_time = time.time()
        print(f"{self.get_current_time()} Starting the shaker machine for {duration_sec} seconds")
        try:
            while time.time() - start_time < duration_sec:
                self.start()
                time.sleep(5 if duration_sec >= 20 else 2)
        finally:
            self.stop()

    def grab_and_shaking(self, duration_sec: int):
        """
        Grab the container, shake it and then release it.

        Args:
            duration_sec: duration of shaking in seconds
        """
        self.grab()
        time.sleep(2)
        self.shaking(duration_sec=duration_sec)
        time.sleep(3)
        self.release()

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
        time.sleep(9)
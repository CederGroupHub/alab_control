from __future__ import annotations

import time
from contextlib import contextmanager
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice


class MotorState(Enum):
    RUNNING = "running"
    STOPPED = "stopped"


class GripperShaker(BaseArduinoDevice):
    ENDPOINTS = {
        "start": "/start",
        "stop": "/stop",
        "repeat": "/repeat",
        "state": "/state",
    }

    def start_motor(self):
        if self.get_state()["state"] == MotorState.RUNNING:
            raise RuntimeError("Motor is already running")
        self.send_request(
            self.ENDPOINTS["start"], method="GET", max_retries=10, timeout=5
        )

    def stop_motor(self):
        self.send_request(
            self.ENDPOINTS["stop"], method="GET", timeout=5, max_retries=10
        )

    @contextmanager
    def motor_on(self):
        """
        Context manager to turn on the motor and turn it off after the block is done.
        """
        try:
            self.start_motor()
            yield
        finally:
            self.stop_motor()

    def repeat_motor(self, repeat_count=2, delay_time=1000):
        if self.get_state()["state"] == MotorState.RUNNING:
            raise RuntimeError("Motor is already running")
        self.send_request(
            f"/repeat?count={repeat_count}&time={delay_time}",
            method="GET",
        )
        time.sleep(1)
        start_time = time.time()
        while (
            self.get_state()["state"] != MotorState.RUNNING
            and time.time() - start_time < 5
        ):
            time.sleep(0.1)
        while self.get_state()["state"] != MotorState.STOPPED:
            time.sleep(0.1)

    def get_state(self):
        response = self.send_request(
            self.ENDPOINTS["state"], method="GET", max_retries=10, timeout=5
        )
        return {
            "state": MotorState[response["state"]],
        }

    def __del__(self):
        try:
            self.stop_motor()
        except:  # noqa
            pass


# Example usage
if __name__ == "__main__":
    # Update the port based on your setup
    motor = GripperShaker("192.168.0.39")
    try:
        print("Starting motor...")
        motor.start_motor()
        time.sleep(2)

        print("Stopping motor...")
        motor.stop_motor()
        time.sleep(1)

        print("Current state:", motor.get_state())

    except Exception as e:
        print(f"An error occurred: {e}")

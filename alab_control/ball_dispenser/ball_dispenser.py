import time
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice


class BallDispenserState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"


class BallDispenser(BaseArduinoDevice):
    """
    Dispensing Al2O3 balls to the crucibles.
    """

    # TODO: add state endpoint to the dispenser code
    ENDPOINTS = {
        "start": "/start",
        "change_number": "/change",
        "state": "/state",
        "stop": "/stop",
    }

    def dispense_balls(self):
        """
        Dispense balls
        """
        if self.get_state() == BallDispenserState.RUNNING:
            raise RuntimeError("Dispenser is still running")
        self.send_request(self.ENDPOINTS["start"], method="GET")
        time.sleep(5)

        # wait until finishes
        while self.get_state() == BallDispenserState.RUNNING:
            time.sleep(1)

    def stop(self):
        """
        Stop the dispenser
        """
        if self.get_state() == BallDispenserState.STOPPED:
            return
        self.send_request(self.ENDPOINTS["stop"], method="GET")

    def change_number(self, n: int):
        """
        Change the number of balls to dispense

        Args:
            n: number of balls to dispense
        """
        if not 0 <= n <= 100:
            raise ValueError("n must be between 0 and 100")
        self.send_request(self.ENDPOINTS["change_number"], data={"n": n}, method="GET")

    def get_state(self) -> BallDispenserState:
        """
        Get the current state of the dispenser
        """
        return BallDispenserState(self.send_request(self.ENDPOINTS["state"], method="GET")["state"].upper())

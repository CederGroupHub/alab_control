import logging
import time
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice

logger = logging.getLogger(__name__)


class BallDispenserState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"


class EmptyError(Exception):
    """An error that is raised when the ball dispenser is empty"""

    pass


class BallDispenser(BaseArduinoDevice):
    """
    Dispensing Al2O3 balls to the crucibles.
    """

    EMPTY_TIMEOUT = 120  # hard cap across a multi-ball request
    PER_BALL_TIMEOUT = 15  # seconds allowed per requested ball before we force-stop
    ENDPOINTS = {
        "start": "/start",
        "change_number": "/change",
        "state": "/state",
        "stop": "/stop",
        "number": "/num",
    }

    def dispense_balls(self, n: int = 1):
        """
        Dispense ``n`` balls (default 1).

        The Arduino only stops when its IR sensor counts ``n`` balls. It also
        keeps whatever count was last set on the board (default 8). This always
        sets the count first, then force-stops if the sensor never reports done.
        """
        if not 1 <= n <= 100:
            raise ValueError("n must be between 1 and 100")

        try:
            already_running = self.get_state() == BallDispenserState.RUNNING
        except Exception as exc:
            logger.warning("Could not read dispenser state before start: %s", exc)
            already_running = False
        if already_running:
            raise RuntimeError("Dispenser is still running")

        self.change_number(n)
        self.send_request(
            self.ENDPOINTS["start"],
            method="GET",
            suppress_error=True,
            timeout=10,
            max_retries=5,
        )
        logger.info("%s Dispensing %s ball(s)", self.get_current_time(), n)
        start_time = time.time()
        timeout = min(self.PER_BALL_TIMEOUT * n, self.EMPTY_TIMEOUT)

        while True:
            try:
                running = self.get_state() == BallDispenserState.RUNNING
            except Exception as exc:
                logger.warning("Could not read dispenser state: %s", exc)
                running = True
            if not running:
                return
            if time.time() - start_time > timeout:
                self.stop()
                raise EmptyError("Dispenser is empty")
            time.sleep(0.2)

    def stop(self):
        """
        Stop the dispenser. Always send /stop; the board ignores it if idle.
        """
        self.send_request(
            self.ENDPOINTS["stop"],
            method="GET",
            suppress_error=True,
            timeout=10,
            max_retries=5,
        )

    def change_number(self, n: int):
        """
        Change the number of balls to dispense

        Args:
            n: number of balls to dispense
        """
        if not 1 <= n <= 100:
            raise ValueError("n must be between 1 and 100")
        self.send_request(self.ENDPOINTS["change_number"] + f"?n={n}", method="GET")

    def get_state(self) -> BallDispenserState:
        """
        Get the current state of the dispenser
        """
        return BallDispenserState[
            self.send_request(
                self.ENDPOINTS["state"],
                suppress_error=True,
                method="GET",
                max_retries=5,
                timeout=10,
            )["state"].upper()
        ]

    def is_running(self) -> bool:
        """Return whether the dispenser motor is running."""
        return self.get_state() == BallDispenserState.RUNNING

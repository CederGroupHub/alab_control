"""Legacy servo open/close gripper (not used by ALab One DASH)."""

from __future__ import annotations

import logging
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice

logger = logging.getLogger(__name__)


class LegacyServoCapperState(Enum):
    OPEN = "open"
    CLOSE = "closed"


class LegacyServoCapper(BaseArduinoDevice):
    ENDPOINTS = {
        "state": "/state",
        "open": "/open",
        "close": "/close",
    }

    def get_state(self):
        return LegacyServoCapperState[
            self.send_request(
                self.ENDPOINTS["state"],
                suppress_error=True,
                method="GET",
                max_retries=5,
                timeout=10,
            )["state"].upper()
        ]

    def open(self):
        if self.get_state() == LegacyServoCapperState.OPEN:
            return
        self.send_request(
            "/open", suppress_error=True, method="GET", timeout=30, max_retries=3
        )
        logger.info(f"{self.get_current_time()} Opening Capping Gripper")

    def close(self):
        if self.get_state() == LegacyServoCapperState.CLOSE:
            return
        self.send_request(
            "/close", suppress_error=True, method="GET", timeout=30, max_retries=3
        )
        logger.info(f"{self.get_current_time()} Closing Capping Gripper")

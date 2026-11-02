"""DASH vial capper: pneumatic grippers + spin motor (P1AM / HTTP API)."""

from __future__ import annotations

import time
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice


class CapperState(Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class Capper(BaseArduinoDevice):
    ENDPOINTS = {
        "state": "/state",
        "open-top-gripper": "/open-top-gripper",
        "close-top-gripper": "/close-top-gripper",
        "open-bottom-gripper": "/open-bottom-gripper",
        "close-bottom-gripper": "/close-bottom-gripper",
        "cw-motor": "/cw-motor",
        "ccw-motor": "/ccw-motor",
    }

    def __init__(self, ip_address: str, port: int = 80):
        super().__init__(ip_address, port)

    def get_state(self) -> CapperState:
        """Return whether the capper motor/command loop is running or idle."""
        state = str(
            self.send_request(
                self.ENDPOINTS["state"],
                method="GET",
                suppress_error=True,
                max_retries=10,
                timeout=10,
            )["system_status"].upper()
        )
        if state == "RUNNING":
            return CapperState.RUNNING
        if state == "IDLE":
            return CapperState.STOPPED
        raise ValueError(f"Unknown capper system_status: {state!r}")

    def open_top_gripper(self):
        for _ in range(3):
            self.send_request(
                self.ENDPOINTS["open-top-gripper"],
                method="GET",
                suppress_error=True,
                max_retries=10,
                timeout=10,
            )

    def close_top_gripper(self):
        for _ in range(3):
            self.send_request(
                self.ENDPOINTS["close-top-gripper"],
                method="GET",
                suppress_error=True,
                max_retries=10,
                timeout=10,
            )

    def open_bottom_gripper(self):
        for _ in range(3):
            self.send_request(
                self.ENDPOINTS["open-bottom-gripper"],
                method="GET",
                suppress_error=True,
                max_retries=10,
                timeout=10,
            )

    def close_bottom_gripper(self):
        for _ in range(3):
            self.send_request(
                self.ENDPOINTS["close-bottom-gripper"],
                method="GET",
                suppress_error=True,
                max_retries=10,
                timeout=10,
            )

    def cw_motor(self, rpm: int, revolutions: float):
        params = {"rpm": rpm, "rev": revolutions}
        self.send_request(
            self.ENDPOINTS["cw-motor"],
            method="GET",
            params=params,
            suppress_error=True,
            max_retries=10,
            timeout=10,
        )
        while self.get_state() == CapperState.RUNNING:
            time.sleep(0.1)

    def ccw_motor(self, rpm: int, revolutions: float):
        params = {"rpm": rpm, "rev": revolutions}
        self.send_request(
            self.ENDPOINTS["ccw-motor"],
            method="GET",
            params=params,
            suppress_error=True,
            max_retries=10,
            timeout=10,
        )
        while self.get_state() == CapperState.RUNNING:
            time.sleep(0.1)

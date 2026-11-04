"""DASH vial capper: pneumatic grippers + spin motor (P1AM / HTTP API)."""

from __future__ import annotations

import time
from enum import Enum
from typing import Union

import requests

from alab_control._base_arduino_device import BaseArduinoDevice

# (connect, read). Short connect so a half-closed keep-alive / dead socket
# fails in a fraction of a second instead of hanging the Device Control button
# for the full read timeout before the motor or gripper even starts.
_DEFAULT_TIMEOUT = (0.4, 2.0)


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
        # Prefer Connection: close. The P1AM Ethernet stack only services one
        # client at a time; a keep-alive Session that outlives the PLC's idle
        # window leaves the next GUI click blocked on a dead socket.
        self._reset_http()

    def _reset_http(self) -> None:
        old = getattr(self, "_http", None)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self._http = requests.Session()
        self._http.headers["Connection"] = "close"

    @staticmethod
    def _timeout_pair(timeout: Union[float, tuple]) -> tuple[float, float]:
        if isinstance(timeout, tuple):
            return float(timeout[0]), float(timeout[1])
        value = float(timeout)
        return min(0.4, value), value

    def send_request(
        self,
        endpoint: str,
        data=None,
        method: str = "GET",
        jsonify: bool = True,
        suppress_error: bool = False,
        timeout=_DEFAULT_TIMEOUT,
        max_retries: int = 2,
        params=None,
    ):
        url = f"http://{self.ip_address}:{self.port}{endpoint}"
        connect_t, read_t = self._timeout_pair(timeout)
        last_error: Exception | None = None
        response = None
        attempts = max(1, int(max_retries))
        for attempt in range(attempts):
            try:
                response = self._http.request(
                    method=method,
                    url=url,
                    data=data,
                    timeout=(connect_t, read_t),
                    params=params,
                )
                break
            except requests.RequestException as error:
                last_error = error
                self._reset_http()
                if attempt + 1 >= attempts:
                    raise
        if response is None:
            assert last_error is not None
            raise last_error
        if not suppress_error:
            response.raise_for_status()
        if jsonify:
            payload = response.json()
            response.close()
            return payload
        return response

    def get_state(self, *, max_retries: int = 2, timeout: float | tuple = _DEFAULT_TIMEOUT) -> CapperState:
        """Return whether the capper motor/command loop is running or idle."""
        state = str(
            self.send_request(
                self.ENDPOINTS["state"],
                method="GET",
                suppress_error=True,
                max_retries=max_retries,
                timeout=timeout,
            )["system_status"].upper()
        )
        if state == "RUNNING":
            return CapperState.RUNNING
        if state == "IDLE":
            return CapperState.STOPPED
        raise ValueError(f"Unknown capper system_status: {state!r}")

    def _pulse_gripper(self, endpoint: str) -> None:
        # One shot is enough; the PLC ignores further hits while still RUNNING.
        # The old 3× / 10s pattern made every dead-socket click wait up to 30s.
        self.send_request(
            endpoint,
            method="GET",
            suppress_error=True,
            max_retries=2,
            timeout=_DEFAULT_TIMEOUT,
        )

    def open_top_gripper(self):
        self._pulse_gripper(self.ENDPOINTS["open-top-gripper"])

    def close_top_gripper(self):
        self._pulse_gripper(self.ENDPOINTS["close-top-gripper"])

    def open_bottom_gripper(self):
        self._pulse_gripper(self.ENDPOINTS["open-bottom-gripper"])

    def close_bottom_gripper(self):
        self._pulse_gripper(self.ENDPOINTS["close-bottom-gripper"])

    def cw_motor(self, rpm: int, revolutions: float):
        params = {"rpm": rpm, "rev": revolutions}
        self.send_request(
            self.ENDPOINTS["cw-motor"],
            method="GET",
            params=params,
            suppress_error=True,
            max_retries=2,
            timeout=_DEFAULT_TIMEOUT,
        )
        # Sparse polls so the PLC can step the motor between HTTP hits.
        while self.get_state(max_retries=1, timeout=_DEFAULT_TIMEOUT) == CapperState.RUNNING:
            time.sleep(0.5)

    def ccw_motor(self, rpm: int, revolutions: float):
        params = {"rpm": rpm, "rev": revolutions}
        self.send_request(
            self.ENDPOINTS["ccw-motor"],
            method="GET",
            params=params,
            suppress_error=True,
            max_retries=2,
            timeout=_DEFAULT_TIMEOUT,
        )
        while self.get_state(max_retries=1, timeout=_DEFAULT_TIMEOUT) == CapperState.RUNNING:
            time.sleep(0.5)

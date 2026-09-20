"""Drive the mobile robot arm through the station-scoped split programs.

``MobileRobotArm`` still speaks ``Main``. This drives the same robot the other way:
each movement is its own small program, and choosing which one is a table lookup in
:mod:`alab_control.mobile_robot_arm.programs`.

A base move can be two programs (out, then go). A transfer is one ``robotarm_*``
program with both source and destination filled. Where the base is comes from the
controller's persisted ``BasePosition`` over rosbridge — it is not on REST.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Protocol

from . import programs as P
from .mobile_robot_arm import MobileRobotArm

logger = logging.getLogger(__name__)

DEFAULT_IP = "192.168.1.207"
ROSBRIDGE_PORT = 9090


class Transport(Protocol):
    """Whatever can load a named program and wait for it to finish."""

    def run_program(
        self, program_name: str, arguments: dict[str, str] | None = None
    ) -> None:
        ...


class PositionSource(Protocol):
    """Whatever can say where the controller believes the base is parked."""

    def base_position(self) -> str:
        ...


class RosBasePosition:
    """Read ``BasePosition`` over Ability's rosbridge websocket."""

    def __init__(self, host: str = DEFAULT_IP, port: int = ROSBRIDGE_PORT, timeout: float = 15.0) -> None:
        self.url = f"ws://{host}:{port}"
        self.timeout = timeout

    def call_service(self, service: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            import websocket
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "websocket-client is required to read BasePosition: pip install websocket-client"
            ) from exc

        connection = websocket.create_connection(self.url, timeout=self.timeout)
        try:
            request_id = "1"
            connection.send(
                json.dumps(
                    {
                        "op": "call_service",
                        "id": request_id,
                        "service": service,
                        "args": args or {},
                    }
                )
            )
            while True:
                message = json.loads(connection.recv())
                if message.get("op") == "service_response" and message.get("id") == request_id:
                    if not message.get("result", True):
                        raise RuntimeError(f"rosbridge call failed: {message}")
                    values = message.get("values")
                    return values if isinstance(values, dict) else {"data": values}
        finally:
            connection.close()

    def variable(self, name: str) -> Any:
        reply = self.call_service(
            "/ability_backend/persistent/global/get_variable", {"data": name}
        )
        if not reply.get("success", True):
            raise RuntimeError(
                f"could not read variable {name!r}: {reply.get('error_message')}"
            )
        raw = reply.get("data")
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return raw

    def base_position(self) -> str:
        return str(self.variable("BasePosition"))


class SplitProgramRobot:
    """The mobile robot arm, driven one program per movement."""

    def __init__(
        self,
        ip: str = DEFAULT_IP,
        transport: Transport | None = None,
        positions: PositionSource | None = None,
    ) -> None:
        self.ip = ip
        self._transport = transport
        self._positions = positions
        self._lock = threading.RLock()

    @property
    def transport(self) -> Transport:
        if self._transport is None:
            self._transport = MobileRobotArm(ip=self.ip)
        return self._transport

    @property
    def positions(self) -> PositionSource:
        if self._positions is None:
            self._positions = RosBasePosition(host=self.ip)
        return self._positions

    def base_position(self) -> str:
        """Where the controller believes the base is parked."""
        return self.positions.base_position()

    def run(self, program: str, arguments: dict[str, str]) -> None:
        """Run one entry program. Prefer the movement methods below."""
        logger.info("running %s with %s", program, arguments)
        self.transport.run_program(program, arguments)

    def move_base_to(self, target: str, current: str | None = None) -> list[str]:
        """Drive the base to ``target``, returning the programs that were run."""
        with self._lock:
            if current is None:
                current = self.base_position()
            steps = P.resolve_base_move(current, target)
            if not steps:
                logger.info("base is already at %s, nothing to run", target)
            for program, arguments in steps:
                self.run(program, arguments)
            return [program for program, _ in steps]

    def charge(self) -> list[str]:
        return self.move_base_to("Charging")

    def charge_no_waiting(self) -> list[str]:
        return self.move_base_to("ChargingNoWait")

    def home_base(self) -> list[str]:
        return self.move_base_to(P.HOME)

    def pick(self, region: str, slot: str) -> str:
        with self._lock:
            program, arguments = P.resolve_pick(region, slot)
            self.run(program, arguments)
            return program

    def place(self, region: str, slot: str) -> str:
        with self._lock:
            program, arguments = P.resolve_place(region, slot)
            self.run(program, arguments)
            return program

    def transfer(
        self,
        source_region: str,
        source_slot: str,
        destination_region: str,
        destination_slot: str,
    ) -> list[str]:
        """Pick and place in one ``robotarm_*`` program when both sides fit.

        Falls back to pick-then-place if a single program cannot cover both ends.
        """
        with self._lock:
            try:
                program, arguments = P.resolve_transfer(
                    source_region, source_slot, destination_region, destination_slot
                )
                self.run(program, arguments)
                return [program]
            except P.UnsupportedRoute:
                pick = P.resolve_pick(source_region, source_slot)
                place = P.resolve_place(destination_region, destination_slot)
                for program, arguments in (pick, place):
                    self.run(program, arguments)
                return [pick[0], place[0]]

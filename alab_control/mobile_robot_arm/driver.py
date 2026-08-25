"""Drive the mobile robot arm through the split programs.

The controller used to hold one program, ``Main``, and every movement was a branch inside
it chosen from five string arguments. :class:`MobileRobotArm` still speaks that way, and
still can. This drives the same robot the other way: each movement is its own small
program on the controller, and choosing which one is a table lookup here rather than 4000
lines of string matching there. See :mod:`alab_control.mobile_robot_arm.programs` for the
table and ``scripts/mobile_robot_program_split`` for how the programs were made.

What this class is for is the part that is neither the table nor the transport: a base
move can be two programs rather than one, a transfer is a pick program then a place
program, and both need to know where the base actually is. It deliberately does not
retry, prompt anyone, or recover -- that belongs with whoever owns the operators and the
database, which in this lab is the AlabOS device.

Where the base is comes from the controller, not from memory::

    robot = SplitProgramRobot(ip="192.168.1.207")
    robot.base_position()                    # 'LABMAN', straight from the controller
    robot.move_base_to("BFT")                # ['Run_OutFrom_Labman', 'Run_GoTo_BFT']
    robot.transfer("BFT", "3", "ROBOT_BASE/SubRackA", "1")

``BasePosition`` is the variable ``Main``'s own ladders steered by, and the generated
programs maintain it exactly as ``Main`` did, so reading it is reading the truth rather
than a guess that a manual jog or a restart could have invalidated.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from . import programs as P
from .mobile_robot_arm import MobileRobotArm

logger = logging.getLogger(__name__)

DEFAULT_IP = "192.168.1.207"


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


class SplitProgramRobot:
    """The mobile robot arm, driven one program per movement.

    Both collaborators are built on first use and can be supplied instead, which is how
    the tests drive this without hardware. The position source is the ROS interface
    rather than REST because ``BasePosition`` is not exposed over REST at all.
    """

    def __init__(
        self,
        ip: str = DEFAULT_IP,
        transport: Transport | None = None,
        positions: PositionSource | None = None,
    ) -> None:
        self.ip = ip
        self._transport = transport
        self._positions = positions
        # Guards a whole movement, not a single program: a base move can be two legs,
        # and another thread starting a program between them would drive from a station
        # the first leg had already left.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ plumbing

    @property
    def transport(self) -> Transport:
        if self._transport is None:
            # Constructing this talks to the robot, so it waits until something is
            # actually being run.
            self._transport = MobileRobotArm(ip=self.ip)
        return self._transport

    @property
    def positions(self) -> PositionSource:
        if self._positions is None:
            # Imported here, not at module scope: it lives in the MiR250 package and
            # brings a websocket dependency that the REST path does not otherwise need.
            from ..mobile_robot_mir250.clients import AbilityRosClient

            self._positions = AbilityRosClient(host=self.ip)
        return self._positions

    def base_position(self) -> str:
        """Where the controller believes the base is parked."""
        return self.positions.base_position()

    def run(self, program: str, arguments: dict[str, str]) -> None:
        """Run one entry program. Prefer the movement methods below."""
        logger.info("running %s with %s", program, arguments)
        self.transport.run_program(program, arguments)

    # ------------------------------------------------------------- base movement

    def move_base_to(self, target: str, current: str | None = None) -> list[str]:
        """Drive the base to ``target``, returning the programs that were run.

        Two programs when the robot has to back out of a station first, one when it is
        already at Home, none when it is already there. Pass ``current`` to say where the
        base is instead of asking the controller.

        A failure to read the position is raised rather than worked around. The tempting
        fallback -- drive Home and start again from there -- is not safe: ``Main`` only
        ever reached its Home branch after the station's retreat had run, so driving Home
        from inside a station is a movement no ladder branch ever performed.
        """
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
        """Dock at the charger and wait for the charge to finish."""
        return self.move_base_to("Charging")

    def charge_no_waiting(self) -> list[str]:
        """Dock at the charger without waiting for the charge to finish."""
        return self.move_base_to("ChargingNoWait")

    def home_base(self) -> list[str]:
        """Bring the base back to Home from wherever it is."""
        return self.move_base_to(P.HOME)

    # -------------------------------------------------------------- arm movement

    def pick(self, region: str, slot: str) -> str:
        """Pick ``slot`` out of ``region``, returning the program that was run."""
        with self._lock:
            program, arguments = P.resolve_pick(region, slot)
            self.run(program, arguments)
            return program

    def place(self, region: str, slot: str) -> str:
        """Place into ``slot`` of ``region``, returning the program that was run."""
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
        """One pick and one place, the transfer ``Main`` did in a single program.

        Safe to split in two because the state the halves share -- the pick/place stage
        counters and the tag-calibration flags -- is written before it is read on both
        sides of the seam, so neither carries anything across. Both routes are resolved
        before either runs, so an unroutable destination fails before the arm has picked
        something up and has nowhere to put it.
        """
        with self._lock:
            pick = P.resolve_pick(source_region, source_slot)
            place = P.resolve_place(destination_region, destination_slot)
            for program, arguments in (pick, place):
                self.run(program, arguments)
            return [pick[0], place[0]]

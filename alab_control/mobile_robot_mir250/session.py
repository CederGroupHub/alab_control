"""Run individual Ability actions from Python, without changing the controller.

``Main`` stays exactly as the vendor shipped it. The route in is a service the Ability
editor itself uses::

    /ability_backend/program/execute_instruction (token_id, er_xml)

It takes the backend XML as an argument, so the payload comes from Python. A
``CallFunctionBlock`` naming one of ``Main``'s 125 function blocks by UID runs that
function, which means every action in the block program is individually callable.
``BaseHandler``'s dispatch -- the choice of which retreat to run and which approach to
follow it with -- moves into the two tables below; the actions themselves stay the
vendor's, including their ``BasePosition`` bookkeeping.

Two neighbouring services look like they should do this and do not:

- ``execute_function(token_id, er_xml_function, er_xml)`` returns success and executes
  nothing. Verified with a function whose body was an 8 second wait and a variable write:
  the wait did not happen and the variable was never written.
- ``execute_program(token_id, er_xml)`` is untested, since instructions already cover the
  need and a whole-program payload is the riskier thing to get wrong.

Before running anything, clear any webhook left registered by an earlier REST run: a dead
listener makes every execution fail with "Unable to connect to program webhook server",
including instructions that have nothing to do with it. :func:`clear_stale_webhook` does
that.

A programming token is held for the duration of a session and released afterwards. If a
process is killed mid-way the token is stranded and the controller sits in ``Recovery``;
:meth:`AbilityRosClient.force_token_release` is the only way out.
"""

from __future__ import annotations

import logging
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable

logger = logging.getLogger(__name__)
from .ability_xml import (
    ProgramArchive,
    assign_instruction,
    call_instruction,
    compact,
    save_variable_instruction,
    sequence_instruction,
    wait_instruction,
)
from .clients import (
    ATTENDED_STATES,
    IDLE_STATES,
    RUNNING_STATES,
    AbilityClient,
    AbilityRosClient,
    RobotApiError,
    is_error_state,
    main_arguments,
)

# Main's dispatch, re-expressed in Python. Reading these two tables against the
# extracted BaseHandler is the whole of what the block program decided.
APPROACH = {
    "Home": "HomeBase",
    "Charging": "Charging",
    "ChargingNoWait": "Charging",
    "LABMAN": "Go to Labman",
    "BFT": "Go To Furnace Station",
    "DASH": "Go To DASH",
    "SRS": "Go To SubRackStorage Station",
    "IXRD": "GoToIXRDStation",
    "SEMEDS": "GoToSEMEDS",
}
RETREAT = {
    "Charging": "HomeBase",
    "ChargingNoWait": "HomeBase",
    "LABMAN": "Out from Labman",
    "BFT": "Out From Furnace Station",
    "DASH": "OutFromDASH_New",
    "SRS": "Out From SubRackStorageStation",
    "IXRD": "Out from IXRD",
    "SEMEDS": "Out from SEMEDS",
}

# Functions that command no motion, read off the extracted program rather than guessed.
# `Charging` waits for the battery, so only Main's dispatch should call it directly.
NO_MOTION_FUNCTIONS = ("LoadAllVariables", "ResetTagCalibrations")

EXECUTE_INSTRUCTION = "/ability_backend/program/execute_instruction"


class BridgeError(RuntimeError):
    """A failure while driving the controller through the programming interface."""


def clear_stale_webhook(ability: AbilityClient, ros: AbilityRosClient) -> bool:
    """Reload Main with no webhook, so a dead listener cannot fail every execution.

    A webhook registered by an earlier REST run outlives that run. The controller then
    faults with "Unable to connect to program webhook server" on the next execution of
    anything at all, which reads as a fault in whatever you were doing instead.

    Reloading with the station the program already believes it is at means even an
    accidental start is a no-op: Main's dispatch returns immediately when the target
    equals ``BasePosition``.
    """
    state = ability.state()
    if is_error_state(state):
        ability.stop()
        time.sleep(2.0)
    ability.wait_until_loadable()
    ability.load_program(
        "Main", main_arguments(target_base_position=ros.base_position())
    )
    ability.wait_until_loadable()
    return True


class ProgrammingSession:
    """Holds the programming token, with the heartbeat the controller expects.

    Ability treats programming as an exclusive session: one holder at a time, refreshed
    by a heartbeat. Another client asking for the token puts this one into a release
    request, hence ``cancel_token_release`` in the service list. Dropping the session
    without deactivating leaves the controller in ``Recovery``.
    """

    def __init__(
        self,
        ros: AbilityRosClient | None = None,
        heartbeat_s: float = 5.0,
    ) -> None:
        self.ros = ros or AbilityRosClient(timeout=120.0)
        self.heartbeat_s = heartbeat_s
        self.token = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "ProgrammingSession":
        reply = self.ros.call_service("/ability_backend/program/activate_programming")
        if not reply.get("success", False):
            raise BridgeError(
                f"could not acquire the programming token: {reply.get('error_message')!r}. "
                "If the controller is in Recovery, force_token_release clears a stranded one"
            )
        self.token = str(reply.get("response") or "")
        if not self.token:
            raise BridgeError(
                "activate_programming succeeded but returned an empty token"
            )
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._beat, name="ability-heartbeat", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.heartbeat_s + 1.0)
        try:
            self.ros.call_service(
                "/ability_backend/program/deactivate_programming",
                {"request": self.token},
            )
        except RobotApiError:
            # A held token is the one failure worth shouting about: the next run cannot
            # acquire one, and the controller sits in Recovery until it is released.
            logger.error(
                "the Ability programming token was not released; call force_token_release"
            )
        self.token = ""

    def _beat(self) -> None:
        while not self._stop.wait(self.heartbeat_s):
            try:
                self.ros.call_service(
                    "/ability_backend/program/heartbeat", {"request": self.token}
                )
            except RobotApiError:
                pass

    def checked(self, service: str, args: dict[str, Any]) -> dict[str, Any]:
        reply = self.ros.call_service(service, args)
        if not reply.get("success", True):
            raise BridgeError(
                f"{service}: {reply.get('error_message') or 'reported failure'}"
            )
        return reply


class PyBridge:
    """One method per Ability action, executed straight from Python.

    Pass ``should_abort`` to make every wait cooperative: it is polled while an execution
    is in flight, and when it returns a reason the wait raises :class:`BridgeError` with
    that reason instead of sitting out the timeout. This is what lets a cancel or a
    battery suspend land during a long move rather than after it.
    """

    def __init__(
        self,
        session: ProgrammingSession,
        archive: ProgramArchive | None = None,
        ability: AbilityClient | None = None,
        log: Callable[[str], None] | None = None,
        should_abort: Callable[[], str] | None = None,
    ) -> None:
        self.session = session
        self.archive = archive or ProgramArchive()
        self.ability = ability or AbilityClient()
        self.ros = session.ros
        self.log = log or logger.info
        self.should_abort = should_abort or (lambda: "")

    # -- the one primitive -------------------------------------------------

    def run(self, instruction: ET.Element, *, timeout: float = 120.0) -> None:
        """Execute a single instruction and wait for it to finish."""
        self.session.checked(
            EXECUTE_INSTRUCTION,
            {"token_id": self.session.token, "er_xml": compact(instruction)},
        )
        self._await_finish(timeout, what=instruction.tag)

    # -- named actions -----------------------------------------------------

    def call(self, function_name: str, *, timeout: float = 600.0) -> None:
        """Run one of Main's function blocks by name."""
        if function_name not in self.archive.functions:
            raise BridgeError(
                f"{function_name!r} is not a function of the exported program"
            )
        self.log(f"call {function_name}")
        self.run(call_instruction(self.archive, function_name), timeout=timeout)

    def wait(self, seconds: float = 1.0) -> None:
        """The no-op probe: proves the interface executes without moving anything."""
        self.run(wait_instruction(seconds), timeout=seconds + 60.0)

    def sequence(self, instructions: list[ET.Element], *, timeout: float = 600.0) -> None:
        """Run several instructions in one call, as one execution.

        A step that must not be interleaved with anyone else's -- assign then save, or
        retreat then approach -- becomes a single execution rather than a series the
        controller could be interrupted between.
        """
        self.run(sequence_instruction(instructions), timeout=timeout)

    def set_variable(
        self,
        name: str,
        value: str,
        type_name: str = "String",
        persist: bool = True,
    ) -> None:
        """Assign a variable, and persist it the way Main does.

        Assign alone lives only as long as the programming session. SaveVariable is
        what makes it survive, and is how ``BasePosition`` outlives a program run.
        """
        self.run(assign_instruction(name, value, type_name), timeout=60.0)
        if persist:
            self.run(save_variable_instruction(name), timeout=60.0)

    def home_base(self, *, timeout: float = 600.0) -> None:
        self.call("HomeBase", timeout=timeout)

    def dock(self, *, timeout: float = 900.0) -> None:
        """Dock on the charger. Note ``Charging`` alone does not wait for the battery."""
        self.call("Charging", timeout=timeout)

    def approach(self, station: str, *, timeout: float = 600.0) -> None:
        if station not in APPROACH:
            raise BridgeError(
                f"no approach known for {station!r}; one of {sorted(APPROACH)}"
            )
        self.call(APPROACH[station], timeout=timeout)

    def retreat(self, from_station: str, *, timeout: float = 600.0) -> None:
        """Run the retreat for wherever the robot is. Home needs none."""
        if from_station == "Home":
            return
        if from_station not in RETREAT:
            raise BridgeError(
                f"no retreat known for {from_station!r}; one of {sorted(RETREAT)}"
            )
        self.call(RETREAT[from_station], timeout=timeout)

    def move_base(self, target: str, *, timeout: float = 600.0) -> None:
        """BaseHandler's dispatch, in Python: retreat from here, then approach there."""
        here = self.ros.base_position()
        if here == target:
            self.log(f"already at {target}, nothing to do")
            return
        self.log(f"moving base {here} -> {target}")
        self.retreat(here, timeout=timeout)
        self.approach(target, timeout=timeout)
        reached = self.ros.base_position()
        if reached != target:
            raise BridgeError(
                f"finished the approach but BasePosition is {reached!r}"
            )

    # -- state -------------------------------------------------------------

    def _await_finish(self, timeout: float, *, what: str, grace: float = 4.0) -> None:
        """Wait out an execution started through the programming interface.

        The service replies as soon as the instruction is accepted, so completion has to
        be read from the controller state. There is no webhook on this path: the webhook
        belongs to a loaded program and nothing is loaded here. A short instruction can
        be finished before the first poll, hence the grace period: if nothing has been
        seen running by then, the instruction was too quick to catch rather than
        silently ignored.
        """
        deadline = time.monotonic() + timeout
        started = time.monotonic()
        observed_running = False
        last = ""
        while time.monotonic() < deadline:
            abort = self.should_abort()
            if abort:
                raise BridgeError(f"{what} was interrupted: {abort}")
            status = self.ability.status()
            state = str(status.get("state", ""))
            message = status.get("message") or ""
            if f"{state}|{message}" != last:
                self.log(f"  {what}: state={state!r} message={message!r}")
                last = f"{state}|{message}"
            if is_error_state(state):
                raise BridgeError(f"{what} failed: {state} {message!r}")
            if state in ATTENDED_STATES:
                raise BridgeError(
                    f"{what}: controller went to {state!r}, someone has taken control"
                )
            if state in RUNNING_STATES:
                observed_running = True
            elif state in IDLE_STATES and (
                observed_running or time.monotonic() - started > grace
            ):
                return
            time.sleep(0.5)
        raise BridgeError(
            f"{what} did not finish within {timeout:.0f}s, last state {last!r}"
        )

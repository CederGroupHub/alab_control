"""Deploy a Python-authored Ability program and run it over documented REST.

The rest of this package drives the robot through ``Main``, or through
``execute_instruction``, which is an editor-internal service. This closes the gap: a
program written in Python, saved to the controller, then loaded and started through
``PUT /v2/programs/current`` and ``PUT /v2/status`` like any other program. Python control
then rests on the documented interface and on entry points of our own design, rather than
on the argument contract of a block program someone else wrote.

Deploying needs the programming token; running does not. That split is why
:func:`deploy` takes a session and :func:`run_over_rest` takes only a REST client.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from .clients import (
    ATTENDED_STATES,
    IDLE_STATES,
    TYPE_STRING,
    AbilityClient,
    AbilityRosClient,
    is_error_state,
)
from .session import BridgeError, ProgrammingSession

logger = logging.getLogger(__name__)

# A Blockly canvas the UI will open without complaint. The backend runs `er_xml` and
# ignores this, but `save_program_as` requires the field, and a program with no canvas
# at all would be impossible for anyone to inspect in the editor afterwards.
EMPTY_CANVAS = '<xml xmlns="https://developers.google.com/blockly/xml"></xml>'


def programming(
    ros: AbilityRosClient, ability: AbilityClient
) -> ProgrammingSession:
    """A programming session, once the controller will grant one.

    A program that has just finished sits in ``Ready``, and ``Ready`` rejects
    ``ActivateProgramming`` exactly as it rejects a program load. Waiting for ``Idle``
    first turns an intermittent failure into no failure.
    """
    ability.wait_until_loadable()
    return ProgrammingSession(ros)


def deploy(session: ProgrammingSession, name: str, er_xml: str) -> None:
    """Save a program archive to the controller under a name of our choosing."""
    session.checked(
        "/ability_backend/program/save_program_as",
        {
            "token_id": session.token,
            "program_name": name,
            "frontend_code": EMPTY_CANVAS,
            "er_xml": er_xml,
            "overwrite": True,
        },
    )


def undeploy(
    session: ProgrammingSession,
    names: list[str],
    *,
    close_first: bool = True,
) -> None:
    """Remove authored programs.

    When ``Main`` is already loaded in ``Idle``, ``close_program`` is refused; skip it
    and delete the leftover archives directly.
    """
    if close_first:
        try:
            session.checked(
                "/ability_backend/program/close_program", {"token_id": session.token}
            )
        except BridgeError as error:
            if "UnloadProgram" not in str(error):
                raise
    for name in names:
        session.checked(
            "/ability_backend/program/delete_program",
            {"token_id": session.token, "program_name": name},
        )


def run_over_rest(
    ability: AbilityClient,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    timeout: float = 180.0,
    log: Callable[[str], None] | None = None,
    should_abort: Callable[[], str] | None = None,
) -> str:
    """Load and start a program the documented way, and wait for it to finish.

    Returns the last state seen. Raises if the controller latches an error, if someone
    takes control from the pendant, or if ``should_abort`` reports a reason to stop --
    which is how a cancel or a battery suspend interrupts a long program instead of
    waiting it out.
    """
    say = log or logger.info
    abort = should_abort or (lambda: "")

    ability.wait_until_loadable()
    ability.load_program(name, arguments or {}, arg_type=TYPE_STRING)
    loaded = ability.program_current() or {}
    if str(loaded.get("name", "")) != name:
        raise BridgeError(
            f"asked for {name!r} but the controller loaded {loaded.get('name')!r}"
        )
    say(f"  loaded {name} with {len(arguments or {})} argument(s)")
    ability.start()

    deadline = time.monotonic() + timeout
    started = time.monotonic()
    seen_executing = False
    last = ""
    while time.monotonic() < deadline:
        reason = abort()
        if reason:
            raise BridgeError(f"{name} was interrupted: {reason}")
        status = ability.status()
        state = str(status.get("state", ""))
        message = status.get("message") or ""
        if f"{state}|{message}" != last:
            say(f"  state={state!r} message={message!r}")
            last = f"{state}|{message}"
        if is_error_state(state):
            raise BridgeError(f"{name} failed: {state} {message!r}")
        if state in ATTENDED_STATES:
            raise BridgeError(
                f"{name}: controller went to {state!r}, someone has taken control"
            )
        if state not in IDLE_STATES:
            seen_executing = True
        elif seen_executing or time.monotonic() - started > 5.0:
            return state
        time.sleep(0.5)
    raise BridgeError(f"{name} did not finish within {timeout:.0f}s, last state {last!r}")

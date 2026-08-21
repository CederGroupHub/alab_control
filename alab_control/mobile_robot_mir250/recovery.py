"""Bring the cell back to Idle without a person at the HMI, when software can.

Preflight still refuses motion until this has worked. The recoveries here are the ones
that do not command the base or the arm:

- leftover protective-field mute (ROS unmute, then MiR setting 2137)
- latched ``Execution Error Active`` (a stop request)
- stranded ``Recovery`` (force-token-release)
- stale ``Entity Error Active`` whose healthcheck now passes (restart that docker module)
- leftover ``PyAuthored*`` programs (close, delete, load ``Main``)

The true MiR API wedge -- ``Entity Error Active`` *and* the MiR unreachable -- has no
software recovery. Emergency and safeguard stops are physical. Ability's Automatic
selector and the MiR key switch are physical. Those still raise
:class:`MaintenanceRequired`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from .authored_program import undeploy
from .clients import (
    STATE_IDLE,
    STATE_RECOVERY,
    AbilityClient,
    AbilityRosClient,
    MirClient,
    RobotApiError,
    is_error_state,
    mir_pause_reason,
)
from .errors import MaintenanceRequired
from .safety import (
    MUTE_SETTLE_S,
    ensure_fields_unmuted,
    fields_muted,
    mir_is_wedged,
    wedge_prompt,
)
from .session import BridgeError, ProgrammingSession

logger = logging.getLogger(__name__)

ABILITY_HMI_URL = "http://192.168.1.207/"
AUTHORED_PREFIX = "PyAuthored"

#: After restarting a docker module, wait this long for Ability to come back Idle.
MODULE_RESTART_WAIT_S = 45.0

PHYSICAL_STOP_STATES = ("Emergency Stop Active", "Safeguard Stop Active")

ENTITY_NEEDLES = {
    "manipulator": ("manipulator", "ur", "arm"),
    "mobile": ("mobile", "mir", "hwl"),
}


@dataclass
class RecoveryAction:
    name: str
    ok: bool
    detail: str = ""

    def __str__(self) -> str:
        return f"{'ok' if self.ok else 'FAILED'} {self.name}: {self.detail}"


@dataclass
class RecoveryReport:
    """What recovery tried, and whether the cell is Idle with live scanners afterwards."""

    actions: list[RecoveryAction] = field(default_factory=list)
    ability_state: str = ""
    ability_message: str = ""
    fields_muted: bool | None = None
    wedged: bool = False
    needs_hmi_ack: bool = False
    needs_maintenance: bool = False
    prompt: str = ""

    @property
    def ok(self) -> bool:
        return (
            not self.needs_maintenance
            and not self.wedged
            and self.ability_state in (STATE_IDLE, "No Program")
            and self.fields_muted is not True
            and all(action.ok for action in self.actions)
        )

    def summary(self) -> str:
        if self.ok:
            return (
                f"recovery passed: state={self.ability_state!r} "
                f"fields_muted={self.fields_muted}"
            )
        failed = [action for action in self.actions if not action.ok]
        return "recovery failed: " + "; ".join(
            f"{action.name} -- {action.detail}" for action in failed
        ) or (
            f"recovery failed: state={self.ability_state!r} "
            f"message={self.ability_message!r}"
        )


def leftover_programs(ability: AbilityClient) -> list[str]:
    """Authored leftovers that should not sit next to ``Main``."""
    return [
        name
        for name in ability.programs()
        if name != "Main" and str(name).startswith(AUTHORED_PREFIX)
    ]


def entity_from_message(message: str) -> str:
    """Which Ability entity the latched error names, or empty if unknown."""
    text = (message or "").lower()
    if "manipulator" in text:
        return "manipulator"
    if "mobiledevice" in text or "mobile device" in text or "mobile" in text:
        return "mobile"
    return ""


def match_docker_module(entity: str, modules: list[str]) -> str:
    """Pick the docker module to restart for a failed entity.

    Exact and whole-word matches beat substrings so ``ur`` does not select
    ``Operator UI``. Falls back to the entity name itself if the topic is quiet.
    """
    needles = ENTITY_NEEDLES.get(entity, (entity,))
    lowered = [(name, name.lower()) for name in modules]
    for needle in needles:
        for name, lower in lowered:
            if lower == needle:
                return name
    for needle in needles:
        for name, lower in lowered:
            words = [part for part in lower.replace("_", " ").replace("-", " ").split() if part]
            if needle in words:
                return name
    hits = [
        name
        for needle in needles
        for name, lower in lowered
        if needle in lower
    ]
    if hits:
        return min(hits, key=len)
    return entity


def recover_cell(
    ability: AbilityClient,
    ros: AbilityRosClient,
    mir: MirClient,
    *,
    unmute: bool = True,
    clear_errors: bool = True,
    cleanup_programs: bool = True,
    execute: bool = True,
    unmute_settle: float = MUTE_SETTLE_S,
    restart_wait: float = MODULE_RESTART_WAIT_S,
    log: Callable[[str], None] | None = None,
) -> RecoveryReport:
    """Attempt every software recovery that does not move the robot.

    ``execute=False`` only reports what it would do. Docker-module restart and
    program deletion are skipped unless ``execute`` is true.
    """
    say = log or logger.info
    report = RecoveryReport()
    add = report.actions.append

    status = ability.status()
    report.ability_state = str(status.get("state", ""))
    report.ability_message = str(status.get("message") or "")
    report.fields_muted = fields_muted(mir)
    say(
        f"recovery: state={report.ability_state!r} "
        f"message={report.ability_message!r} fields_muted={report.fields_muted}"
    )

    if not execute:
        add(
            RecoveryAction(
                "dry_run",
                True,
                "would unmute, clear errors and delete leftover programs; pass --execute",
            )
        )
        return report

    # Errors first: a stale Entity Error makes Ability's mute service report success
    # without changing the MiR. Unmute after the latch is gone.
    if report.ability_state == STATE_RECOVERY and clear_errors:
        _recover_token(ability, ros, report, log=say)

    if clear_errors and is_error_state(report.ability_state):
        _recover_error(
            ability,
            ros,
            mir,
            report,
            restart_wait=restart_wait,
            log=say,
        )

    _recover_mir_pause(mir, report, log=say)

    if unmute:
        _recover_mute(ros, mir, report, ability=ability, settle=unmute_settle, log=say)

    if cleanup_programs and report.ability_state in (STATE_IDLE, "No Program"):
        _cleanup_programs(ability, ros, report, log=say)

    status = ability.status()
    report.ability_state = str(status.get("state", ""))
    report.ability_message = str(status.get("message") or "")
    report.fields_muted = fields_muted(mir)
    if report.needs_hmi_ack and not report.prompt:
        report.prompt = (
            f"Ability is still {report.ability_state!r} "
            f"({report.ability_message!r}). On the Ability dashboard at "
            f"{ABILITY_HMI_URL} click Retry on the Entity Error dialog (and check the "
            "UR ethernet cable if it asks). Then re-run recovery."
        )
    return report


def _recover_mir_pause(
    mir: MirClient,
    report: RecoveryReport,
    *,
    log: Callable[[str], None],
) -> None:
    try:
        status = mir.status()
    except RobotApiError as exc:
        report.actions.append(
            RecoveryAction("mir_pause", False, f"could not read MiR status: {exc}")
        )
        return
    problem = mir_pause_reason(status)
    if not problem:
        return
    log(f"MiR pause is blocking work: {problem}")
    resume = getattr(mir, "resume_ready", None)
    if resume is None:
        report.actions.append(
            RecoveryAction(
                "mir_pause",
                False,
                "MiR client cannot resume; press Continue on the MiR web interface or redock",
            )
        )
        return
    try:
        resume()
    except RobotApiError as exc:
        report.actions.append(RecoveryAction("mir_pause", False, str(exc)))
        return
    time.sleep(2.0)
    try:
        status = mir.status()
    except RobotApiError as exc:
        report.actions.append(
            RecoveryAction("mir_pause", False, f"resumed but status unreadable: {exc}")
        )
        return
    cleared = not mir_pause_reason(status)
    report.actions.append(
        RecoveryAction(
            "mir_pause",
            cleared,
            f"MiR is {status.get('state_text')!r} "
            f"({status.get('mission_text')!r})"
            if cleared
            else problem,
        )
    )


def _recover_mute(
    ros: AbilityRosClient,
    mir: MirClient,
    report: RecoveryReport,
    *,
    ability: AbilityClient,
    settle: float,
    log: Callable[[str], None],
) -> None:
    try:
        ensure_fields_unmuted(ros, mir, ability=ability, settle=settle, log=log)
    except MaintenanceRequired as exc:
        report.actions.append(
            RecoveryAction("unmute", False, str(exc))
        )
        report.needs_maintenance = True
        report.prompt = exc.prompt
        report.fields_muted = True
        return
    report.fields_muted = fields_muted(mir)
    report.actions.append(
        RecoveryAction(
            "unmute",
            report.fields_muted is not True,
            "protective fields are live"
            if report.fields_muted is not True
            else "fields still muted",
        )
    )


def _recover_token(
    ability: AbilityClient,
    ros: AbilityRosClient,
    report: RecoveryReport,
    *,
    log: Callable[[str], None],
) -> None:
    log("Ability is in Recovery; releasing the stranded programming token")
    try:
        ros.force_token_release()
    except RobotApiError as exc:
        report.actions.append(
            RecoveryAction("recovery_token", False, str(exc))
        )
        report.needs_maintenance = True
        return
    time.sleep(2.0)
    status = ability.status()
    report.ability_state = str(status.get("state", ""))
    report.ability_message = str(status.get("message") or "")
    report.actions.append(
        RecoveryAction(
            "recovery_token",
            report.ability_state != STATE_RECOVERY,
            f"state after releasing the token: {report.ability_state!r}",
        )
    )


def _recover_error(
    ability: AbilityClient,
    ros: AbilityRosClient,
    mir: MirClient,
    report: RecoveryReport,
    *,
    restart_wait: float,
    log: Callable[[str], None],
) -> None:
    state = report.ability_state
    message = report.ability_message

    if state in PHYSICAL_STOP_STATES:
        report.actions.append(
            RecoveryAction(
                "physical_stop",
                False,
                f"controller is {state!r}; reset the e-stop or safeguard on the hardware",
            )
        )
        report.needs_maintenance = True
        report.prompt = (
            f"Ability is in {state!r}. Software cannot clear this. Reset the physical "
            "e-stop or safeguard, confirm the Ability selector is Automatic, then "
            "re-run recovery."
        )
        return

    mir_reachable = True
    try:
        mir.status()
    except RobotApiError:
        mir_reachable = False

    if mir_is_wedged(state, mir_reachable, message):
        report.wedged = True
        report.needs_maintenance = True
        report.actions.append(
            RecoveryAction(
                "mir_wedge",
                False,
                "Entity Error Active and the MiR API is not answering",
            )
        )
        report.prompt = wedge_prompt(message)
        return

    log(f"clearing latched {state!r} with a stop request")
    stopped = _try_stop(ability, ros, log)
    time.sleep(2.0)
    status = ability.status()
    report.ability_state = str(status.get("state", ""))
    report.ability_message = str(status.get("message") or "")
    if not is_error_state(report.ability_state):
        report.actions.append(
            RecoveryAction(
                "clear_error",
                True,
                f"stop request left the controller in {report.ability_state!r}",
            )
        )
        return

    entity = entity_from_message(message)
    if entity and _entity_healthcheck_ok(ros, entity):
        log(
            f"healthcheck for {entity} is green but the latch remains; "
            f"restarting the {entity} docker module"
        )
        restarted = _restart_entity_module(ros, entity, log)
        report.actions.append(
            RecoveryAction(
                "restart_module",
                restarted.ok,
                restarted.detail,
            )
        )
        if restarted.ok:
            _wait_for_idle(ability, ros, timeout=restart_wait, log=log)
            if _idle_holds(ability, hold_s=10.0, log=log):
                status = ability.status()
                report.ability_state = str(status.get("state", ""))
                report.ability_message = str(status.get("message") or "")
                if not is_error_state(report.ability_state):
                    report.actions.append(
                        RecoveryAction(
                            "clear_error",
                            True,
                            f"module restart left the controller in {report.ability_state!r}",
                        )
                    )
                    return

    report.needs_hmi_ack = True
    report.needs_maintenance = True
    report.actions.append(
        RecoveryAction(
            "clear_error",
            False,
            f"still {report.ability_state!r} after stop"
            + (" and module restart" if entity else "")
            + f"; acknowledge on the Ability HMI at {ABILITY_HMI_URL}",
        )
    )
    if not stopped:
        log("both stop paths refused; this is expected for a stale Entity Error")


def _try_stop(
    ability: AbilityClient,
    ros: AbilityRosClient,
    log: Callable[[str], None],
) -> bool:
    try:
        ability.stop()
        return True
    except RobotApiError as exc:
        log(f"REST stop was rejected ({exc.status}); trying the ROS stop")
        try:
            ros.system_stop()
            return True
        except RobotApiError:
            return False


def _entity_healthcheck_ok(ros: AbilityRosClient, entity: str) -> bool:
    try:
        reply = ros.healthcheck(entity)
    except RobotApiError:
        return False
    return bool(reply.get("success", False))


def _restart_entity_module(
    ros: AbilityRosClient, entity: str, log: Callable[[str], None]
) -> RecoveryAction:
    try:
        modules = ros.docker_modules()
    except RobotApiError as exc:
        modules = []
        log(f"could not list docker modules ({exc}); trying the entity name {entity!r}")
    name = match_docker_module(entity, modules)
    try:
        reply = ros.restart_docker_module(name)
    except RobotApiError as exc:
        return RecoveryAction("restart_module", False, str(exc))
    ok = bool(reply.get("success", True))
    return RecoveryAction(
        "restart_module",
        ok,
        f"restarted {name!r}"
        if ok
        else f"restart of {name!r} failed: {reply.get('error_message')}",
    )


def _wait_for_idle(
    ability: AbilityClient,
    ros: AbilityRosClient,
    *,
    timeout: float,
    log: Callable[[str], None],
) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            status = ability.status()
        except RobotApiError:
            time.sleep(2.0)
            continue
        state = str(status.get("state", ""))
        message = str(status.get("message") or "")
        if f"{state}|{message}" != last:
            log(f"  waiting after module restart: state={state!r} message={message!r}")
            last = f"{state}|{message}"
        if state in (STATE_IDLE, "No Program") or not is_error_state(state):
            return
        time.sleep(2.0)


def _idle_holds(
    ability: AbilityClient,
    *,
    hold_s: float,
    log: Callable[[str], None],
) -> bool:
    """True if the controller stays non-error for ``hold_s`` after a module restart.

    A UR restart can pass through Idle and then re-latch Entity Error once the
    healthcheck runs again. Treating the first Idle as success is how that flicker
    gets reported as a recovery.
    """
    deadline = time.monotonic() + hold_s
    while time.monotonic() < deadline:
        try:
            status = ability.status()
        except RobotApiError:
            return False
        state = str(status.get("state", ""))
        if is_error_state(state):
            log(f"  Idle did not hold; latched again as {state!r} {status.get('message')!r}")
            return False
        time.sleep(1.0)
    return True


def _cleanup_programs(
    ability: AbilityClient,
    ros: AbilityRosClient,
    report: RecoveryReport,
    *,
    log: Callable[[str], None],
) -> None:
    leftovers = leftover_programs(ability)
    if not leftovers:
        report.actions.append(
            RecoveryAction("cleanup_programs", True, "no leftover PyAuthored programs")
        )
        return
    log(f"deleting leftover programs: {leftovers}")
    try:
        with ProgrammingSession(ros=ros) as session:
            undeploy(session, leftovers)
        ability.load_program("Main", {})
    except (RobotApiError, BridgeError) as exc:
        report.actions.append(
            RecoveryAction("cleanup_programs", False, str(exc))
        )
        return
    remaining = leftover_programs(ability)
    report.actions.append(
        RecoveryAction(
            "cleanup_programs",
            not remaining,
            f"deleted {leftovers}; remaining {remaining}"
            if remaining
            else f"deleted {leftovers} and loaded Main",
        )
    )

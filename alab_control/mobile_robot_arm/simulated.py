"""An in-memory Ability controller for the split-program mobile robot.

``SimulatedMobileRobotArm`` answers the same calls ``MobileRobotArm`` does, so AlabOS
simulation mode can run ``RobotArmMobile`` / ``SplitProgramRobot`` end to end without a
controller: base position follows the ``base_*`` programs, battery drains and charges,
programs take real seconds, and faults can be staged from a small JSON script that is
re-read before every program. It also implements the ``PositionSource`` protocol, so one
object stands in for both the REST transport and the rosbridge ``BasePosition`` read.

Script (all keys optional; path from the constructor or ``ALFRED_SIM_SCRIPT``)::

    {
      "seconds_per_program": 2.0,
      "seconds": {"base_*": 3.0, "robotarm_*": 4.0, "Main": 5.0},
      "battery": 95.0,
      "battery_drain_per_program": 0.5,
      "charge_rate_per_s": 0.2,
      "fail": [
        {"program": "base_BFT", "action": "go", "nth": 1,
         "message": "The Move action timed out after being blocked"}
      ],
      "hang": [{"program": "robotarm_LABMAN", "nth": 1, "seconds": 600}],
      "release_hang": false,
      "charge_drops": {"after_dock_s": 3.0, "times": 1},
      "redock_succeeds": true
    }

``nth`` counts matching runs since the driver was created (1-based); ``"always"`` fires on
every match. ``program`` accepts ``fnmatch`` globs. ``action`` / ``source_region`` /
``destination_region`` narrow the match on the program arguments.

Every program run, fault and dock is appended as one JSON line to the event log
(constructor argument or ``ALFRED_SIM_EVENT_LOG``), which is what the tests read back.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from . import programs as P
from .mobile_robot_arm import MRAState

logger = logging.getLogger(__name__)

SCRIPT_ENV = "ALFRED_SIM_SCRIPT"
EVENT_LOG_ENV = "ALFRED_SIM_EVENT_LOG"

DEFAULT_SECONDS_PER_PROGRAM = 2.0
DEFAULT_BATTERY_DRAIN_PER_PROGRAM = 0.5
DEFAULT_CHARGE_RATE_PER_S = 0.2
DEFAULT_HANG_SECONDS = 600.0
POLL_S = 0.25

#: The controller message the real cell reports when a program fails without more detail.
DEFAULT_FAULT_MESSAGE = "Simulated program failure"


def default_event_log_path() -> Path:
    raw = os.environ.get(EVENT_LOG_ENV)
    if raw:
        return Path(raw)
    return Path(tempfile.gettempdir()) / "alfred_sim_events.jsonl"


class SimulatedMobileRobotArm:
    """The mobile robot arm, pretending. Same surface as ``MobileRobotArm``."""

    def __init__(
        self,
        ip: str = "simulated",
        *,
        script_path: str | os.PathLike | None = None,
        event_log_path: str | os.PathLike | None = None,
        base_position: str = "Charging",
        robot_pose: str = "Home",
        battery: float = 95.0,
        charging: bool = True,
        timeout: int = 10,
        max_retries: int = 3,
    ) -> None:
        self.ip = ip
        self.timeout = timeout
        self.max_retries = max_retries
        raw_script = script_path if script_path is not None else os.environ.get(SCRIPT_ENV)
        self.script_path = Path(raw_script) if raw_script else None
        self.event_log_path = (
            Path(event_log_path) if event_log_path is not None else default_event_log_path()
        )
        self._lock = threading.RLock()
        self._script: dict[str, Any] = {}
        self._script_mtime: float | None = None

        self.state = MRAState.IDLE
        self.message = ""
        self._base_position = base_position
        self._robot_pose = robot_pose
        self._battery = float(battery)
        self._battery_updated_at = time.monotonic()
        self._charging = bool(charging)
        self._charge_drop_at: float | None = None
        self._charge_drops_done = 0
        self._automatic = False
        self._current_program: dict[str, Any] | None = None
        self._program_ends_at: float | None = None
        self._program_hung = False
        self._pending_fault: dict[str, Any] | None = None
        self._run_counts: Counter[str] = Counter()
        self.programs_run: list[tuple[str, dict[str, str]]] = []
        self.acknowledged = 0
        self.redocks = 0
        self.battery_level = self._battery
        self._event("created", base_position=base_position, battery=battery, charging=charging)

    # ------------------------------------------------------------------ script

    def script(self) -> dict[str, Any]:
        """The staged behavior, re-read when the file changes."""
        path = self.script_path
        if path is None:
            return self._script
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._script = {}
            self._script_mtime = None
            return self._script
        if mtime != self._script_mtime:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8") or "{}")
                self._script = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError) as exc:
                logger.warning("sim script %s unreadable: %s", path, exc)
                self._script = {}
            self._script_mtime = mtime
        return self._script

    def _seconds_for(self, program: str) -> float:
        script = self.script()
        for pattern, seconds in (script.get("seconds") or {}).items():
            if fnmatch.fnmatchcase(program, str(pattern)):
                try:
                    return max(0.0, float(seconds))
                except (TypeError, ValueError):
                    break
        try:
            return max(0.0, float(script.get("seconds_per_program", DEFAULT_SECONDS_PER_PROGRAM)))
        except (TypeError, ValueError):
            return DEFAULT_SECONDS_PER_PROGRAM

    @staticmethod
    def _matches(rule: dict[str, Any], program: str, arguments: dict[str, str]) -> bool:
        pattern = str(rule.get("program", "*"))
        if not fnmatch.fnmatchcase(program, pattern):
            return False
        for key in ("action", "source_region", "destination_region", "source_slot", "destination_slot"):
            wanted = rule.get(key)
            if wanted is None:
                continue
            if str(wanted) not in str(arguments.get(key, "")):
                return False
        return True

    def _nth_applies(self, rule: dict[str, Any], count: int) -> bool:
        nth = rule.get("nth", 1)
        if isinstance(nth, str) and nth.lower() in ("always", "*", "any"):
            return True
        if isinstance(nth, list):
            return count in {int(n) for n in nth}
        try:
            return count == int(nth)
        except (TypeError, ValueError):
            return count == 1

    def _staged(self, kind: str, program: str, arguments: dict[str, str]) -> dict[str, Any] | None:
        rules = self.script().get(kind) or []
        if not isinstance(rules, list):
            return None
        for rule in rules:
            if not isinstance(rule, dict) or not self._matches(rule, program, arguments):
                continue
            key = self._rule_key(rule, program)
            count = self._run_counts[key]
            if self._nth_applies(rule, count):
                return rule
        return None

    @staticmethod
    def _rule_key(rule: dict[str, Any], program: str) -> str:
        parts = [program]
        for key in ("action", "source_region", "destination_region", "source_slot", "destination_slot"):
            if rule.get(key) is not None:
                parts.append(f"{key}={rule[key]}")
        return "|".join(parts)

    def _count_run(self, program: str, arguments: dict[str, str]) -> None:
        keys = {program}
        for kind in ("fail", "hang"):
            for rule in self.script().get(kind) or []:
                if isinstance(rule, dict) and self._matches(rule, program, arguments):
                    keys.add(self._rule_key(rule, program))
        for key in keys:
            self._run_counts[key] += 1

    # ------------------------------------------------------------------ events

    def _event(self, event: str, **fields: Any) -> None:
        record = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "event": event,
            "base_position": self._base_position,
            "robot_pose": self._robot_pose,
            "battery": round(self._battery_now(), 2),
            "charging": self._charging_now(),
            "state": self.state.value,
        }
        record.update(fields)
        try:
            self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.event_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=str) + "\n")
        except OSError as exc:
            logger.warning("could not write sim event log %s: %s", self.event_log_path, exc)

    # ------------------------------------------------------------------ battery / charge

    def _battery_now(self) -> float:
        script = self.script()
        pinned = script.get("battery")
        if pinned is not None:
            try:
                return float(pinned)
            except (TypeError, ValueError):
                pass
        now = time.monotonic()
        if self._charging_now():
            try:
                rate = float(script.get("charge_rate_per_s", DEFAULT_CHARGE_RATE_PER_S))
            except (TypeError, ValueError):
                rate = DEFAULT_CHARGE_RATE_PER_S
            self._battery = min(100.0, self._battery + rate * (now - self._battery_updated_at))
        self._battery_updated_at = now
        return self._battery

    def _charging_now(self) -> bool:
        if self._charging and self._charge_drop_at is not None and time.monotonic() >= self._charge_drop_at:
            self._charging = False
            self._charge_drop_at = None
            self._charge_drops_done += 1
            self._event("charge_dropped")
        return self._charging

    def _arrive_on_charger(self) -> None:
        self._charging = True
        self._battery_updated_at = time.monotonic()
        drops = self.script().get("charge_drops") or {}
        try:
            times = int(drops.get("times", 0)) if isinstance(drops, dict) else 0
            after = float(drops.get("after_dock_s", 0.0)) if isinstance(drops, dict) else 0.0
        except (TypeError, ValueError):
            times, after = 0, 0.0
        if times > self._charge_drops_done:
            self._charge_drop_at = time.monotonic() + max(0.0, after)
        self._event("docked")

    def set_battery(self, value: float) -> None:
        with self._lock:
            self._battery = float(value)
            self._battery_updated_at = time.monotonic()

    # ------------------------------------------------------------------ REST-ish surface

    def request_status(self) -> dict:
        with self._lock:
            self._tick()
            return {
                "state": {
                    MRAState.IDLE: "Idle",
                    MRAState.RUNNING: "Executing",
                    MRAState.ERROR: "Execution Error Active",
                    MRAState.SAFEGUARD_STOP: "Safeguard Stop Active",
                }[self.state],
                "current_program": dict(self._current_program or {"name": "", "arguments": []}),
                "battery": self._battery_now(),
                "message": self.message,
            }

    def get_state_and_message(self) -> tuple[MRAState, str]:
        with self._lock:
            self._tick()
            return self.state, self.message

    def get_battery_level(self) -> float:
        with self._lock:
            self.battery_level = self._battery_now()
            return self.battery_level

    def get_current_program(self) -> dict:
        return self.request_status()["current_program"]

    def is_running(self) -> bool:
        return self.get_state_and_message()[0] == MRAState.RUNNING

    def is_error(self) -> bool:
        return self.get_state_and_message()[0] == MRAState.ERROR

    def acknowledge_error(self) -> None:
        with self._lock:
            self.acknowledged += 1
            was = self.state
            if self.state == MRAState.ERROR:
                self.state = MRAState.IDLE
                self.message = ""
            self._automatic = False
            self._event("acknowledge_error", was=was.value)

    def stop_program(self) -> None:
        with self._lock:
            if self.state == MRAState.RUNNING:
                self._finish_program(stopped=True)

    def wait_until_loadable(self) -> None:
        deadline = time.monotonic() + 30.0
        while self.is_running() and time.monotonic() < deadline:
            time.sleep(POLL_S)
        if self.is_running():
            raise ValueError(
                "The MRA is still running after 30 seconds. "
                f"Current state: {self.get_state_and_message()[0]}"
            )
        self.ensure_manual_mode()

    def wait_until_running(self, timeout: float = 10.0) -> None:
        """``start_program`` flips to Executing synchronously here, so this only reports
        a program that already failed before anyone looked."""
        state, message = self.get_state_and_message()
        if state == MRAState.ERROR:
            raise ValueError(f"Program entered error before it started running. Message: {message}")

    def wait_for_program_to_finish(self) -> None:
        while self.is_running():
            time.sleep(POLL_S)
        state, message = self.get_state_and_message()
        if state == MRAState.ERROR:
            raise ValueError(f"Program finished with error. Message: {message}")
        if state != MRAState.IDLE:
            raise ValueError(f"Unknown state: {state}. Please check the API documentation for the full list of states.")

    # ------------------------------------------------------------------ Manual / Automatic

    def is_automatic_mode(self) -> bool:
        return bool(self._automatic)

    def is_manual_mode(self) -> bool:
        return not self._automatic

    def set_automatic_mode(self, enabled: bool, *, release_token: bool = True) -> bool:
        with self._lock:
            self._automatic = bool(enabled)
        return True

    def ensure_manual_mode(self) -> bool:
        with self._lock:
            self._automatic = False
        return True

    def clear_error_with_auto_manual_handshake(self) -> bool:
        with self._lock:
            self._automatic = True
            self._automatic = False
            self._event("auto_manual_handshake")
        return True

    # ------------------------------------------------------------------ programs

    def load_program(self, program_name: str, arguments: list[dict]) -> None:
        with self._lock:
            if self.state == MRAState.ERROR:
                raise ValueError(
                    "Failed to load program. Status code: 400. Response: controller is in "
                    f"Execution Error Active ({self.message}); acknowledge the error first"
                )
            self._current_program = {
                "name": program_name,
                "arguments": [dict(a) for a in arguments],
                "started_at": "",
                "state": 0,
            }

    def start_program(self) -> None:
        with self._lock:
            state, _ = self.get_state_and_message()
            if state != MRAState.IDLE:
                raise ValueError(
                    f"The MRA must be in IDLE state to start a program. Current state: {state}"
                )
            if not self._current_program:
                raise ValueError("start() before load_program()")
            program = str(self._current_program["name"])
            arguments = {
                str(a.get("name")): str(a.get("value"))
                for a in self._current_program.get("arguments", [])
            }
            self._begin_program(program, arguments)

    def run_program(self, program_name: str, arguments: dict[str, str] | None = None) -> None:
        """Load, start and wait, the way ``MobileRobotArm.run_program`` does."""
        self.wait_until_loadable()
        self.load_program(
            program_name,
            [{"name": name, "type": 0, "value": str(value)} for name, value in (arguments or {}).items()],
        )
        self.start_program()
        self.wait_for_program_to_finish()

    def run_main_program(
        self,
        target_base_position: str,
        source_region: str,
        source_slot: str,
        destination_region: str,
        destination_slot: str,
    ) -> None:
        self.run_program(
            "Main",
            {
                "target_base_position": target_base_position,
                "source_region": source_region,
                "source_slot": source_slot,
                "destination_region": destination_region,
                "destination_slot": destination_slot,
            },
        )

    def _begin_program(self, program: str, arguments: dict[str, str]) -> None:
        self._count_run(program, arguments)
        fault = self._staged("fail", program, arguments)
        hang = self._staged("hang", program, arguments)
        seconds = self._seconds_for(program)
        if hang is not None:
            try:
                seconds = float(hang.get("seconds", DEFAULT_HANG_SECONDS))
            except (TypeError, ValueError):
                seconds = DEFAULT_HANG_SECONDS
        self._program_hung = hang is not None
        self._pending_fault = dict(fault) if fault is not None else None
        self.state = MRAState.RUNNING
        self.message = ""
        self._program_ends_at = time.monotonic() + seconds
        self.programs_run.append((program, dict(arguments)))
        self._event(
            "program_start",
            program=program,
            arguments=arguments,
            seconds=round(seconds, 2),
            staged_fault=(fault or {}).get("message") if fault else None,
            hang=bool(hang),
        )

    def _tick(self) -> None:
        """Advance the running program if its time is up (or a hang was released)."""
        if self.state != MRAState.RUNNING or self._program_ends_at is None:
            return
        released = bool(self._program_hung and self.script().get("release_hang"))
        if time.monotonic() >= self._program_ends_at or released:
            self._finish_program(released=released)

    def _finish_program(self, *, stopped: bool = False, released: bool = False) -> None:
        program, arguments = self.programs_run[-1] if self.programs_run else ("", {})
        fault = self._pending_fault
        self._pending_fault = None
        self._program_ends_at = None
        self._program_hung = False
        if stopped:
            self.state = MRAState.IDLE
            self.message = ""
            self._event("program_stopped", program=program, arguments=arguments)
            return
        if fault is not None:
            self.state = MRAState.ERROR
            self.message = str(fault.get("message") or DEFAULT_FAULT_MESSAGE)
            self._apply_fault_side_effects(program, arguments, fault)
            self._event("program_failed", program=program, arguments=arguments, message=self.message)
            return
        self._apply_program_effects(program, arguments)
        try:
            drain = float(self.script().get("battery_drain_per_program", DEFAULT_BATTERY_DRAIN_PER_PROGRAM))
        except (TypeError, ValueError):
            drain = DEFAULT_BATTERY_DRAIN_PER_PROGRAM
        self._battery = max(0.0, self._battery_now() - drain)
        self.state = MRAState.IDLE
        self.message = ""
        self._event("program_end", program=program, arguments=arguments, released=released)

    def _apply_fault_side_effects(self, program: str, arguments: dict[str, str], fault: dict[str, Any]) -> None:
        """A failed base move leaves ``BasePosition`` as it was (the program never wrote
        the new station), the way the cell behaves; the script can override it."""
        where = fault.get("base_position_after")
        if where is not None:
            self._base_position = str(where)
        if program.startswith("base_") or (
            program == "Main" and arguments.get("target_base_position") not in (None, "", P.NONE)
        ):
            self._charging = False
            self._charge_drop_at = None

    def _apply_program_effects(self, program: str, arguments: dict[str, str]) -> None:
        if program == "Main":
            target = arguments.get("target_base_position", P.NONE)
            if target not in (None, "", P.NONE):
                self._move_base(target)
            return
        if program == "base_Home":
            self._move_base(P.HOME)
        elif program == "base_Charging":
            self._move_base("Charging")
        elif program.startswith("base_"):
            station = program[len("base_"):]
            action = arguments.get("action", "")
            if action == "go":
                self._move_base(station)
            elif action == "out":
                self._move_base(P.HOME)
        elif program.startswith("robotarm_"):
            self._robot_pose = "Home"

    def _move_base(self, target: str) -> None:
        before = self._base_position
        if target in P.CHARGER_POSITIONS:
            self._base_position = "Charging"
            self._arrive_on_charger()
        else:
            self._base_position = target
            if before in P.CHARGER_POSITIONS or self._charging:
                self._charging = False
                self._charge_drop_at = None
        self._event("base_moved", frm=before, to=self._base_position)

    # ------------------------------------------------------------------ charging helpers

    def is_actually_charging(self) -> bool | None:
        with self._lock:
            return self._charging_now()

    def redock_on_charger(self) -> bool:
        with self._lock:
            self.redocks += 1
            ok = bool(self.script().get("redock_succeeds", True))
            if ok:
                self._base_position = "Charging"
                self._charging = True
                self._charge_drop_at = None
                self._battery_updated_at = time.monotonic()
            self._event("redock", success=ok)
            return ok

    def settle_on_charge(self, *, settle_s: float = 25.0, redock_attempts: int = 1) -> bool:
        for attempt in range(redock_attempts + 1):
            stable_until = time.monotonic() + max(0.0, float(settle_s))
            dropped = False
            while time.monotonic() < stable_until:
                if self.is_actually_charging() is False:
                    dropped = True
                    break
                time.sleep(min(POLL_S, 2.0))
            if not dropped and self.is_actually_charging() is not False:
                self._event("charge_settled", attempt=attempt)
                return True
            if attempt >= redock_attempts:
                break
            if not self.redock_on_charger():
                break
        return self.is_actually_charging() is True

    def charge(self) -> None:
        self.run_main_program("Charging", P.NONE, P.NONE, P.NONE, P.NONE)

    def charge_no_waiting(self) -> None:
        self.run_main_program("ChargingNoWait", P.NONE, P.NONE, P.NONE, P.NONE)

    # ------------------------------------------------------------------ rosbridge-ish surface

    def base_position(self) -> str:
        """``PositionSource``: where the (simulated) controller believes the base is."""
        with self._lock:
            return self._base_position

    def robot_pose(self) -> str:
        with self._lock:
            return self._robot_pose

    def set_base_position(self, where: str) -> None:
        """Stage a stale / manual-jog BasePosition, like a pendant move would."""
        with self._lock:
            self._base_position = where
            self._event("base_position_set", to=where)

    def home_robot_arm(self) -> None:
        """Stand-in for Main's HomeRobotArm: fold the arm, RobotPose=Home."""
        with self._lock:
            if self.state == MRAState.ERROR:
                self.acknowledge_error()
        self.run_program("HomeRobotArm", {})
        with self._lock:
            self._robot_pose = "Home"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._tick()
            return {
                "state": self.state.value,
                "message": self.message,
                "base_position": self._base_position,
                "robot_pose": self._robot_pose,
                "battery": round(self._battery_now(), 2),
                "charging": self._charging_now(),
                "automatic": self._automatic,
                "programs_run": len(self.programs_run),
                "script_path": str(self.script_path) if self.script_path else None,
                "event_log_path": str(self.event_log_path),
            }

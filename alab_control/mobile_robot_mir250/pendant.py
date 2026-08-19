"""Operational teach-pendant equivalents that do not edit ``Main``.

Play / Stop / Pause already live on :class:`AbilityClient`. This module wraps the
HMI buttons that take and release joystick and UR freedrive, and a deadman jog of
the arm or base. It does not teach waypoints, write TCP or payload, or touch Setup.

Jogging publishes a velocity for a bounded duration and always publishes a zero
command afterwards. Callers must pass ``execute=True``; a dry run only reports the
topic it would use. Someone stays at the e-stop for any executed jog, the same as
for any other motion.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .clients import AbilityRosClient, RobotApiError
from .session import ProgrammingSession

logger = logging.getLogger(__name__)

JOYSTICK_START = "/ability_backend/system/start_joystick"
JOYSTICK_STOP = "/ability_backend/system/stop_joystick"
TEACH_START_SYSTEM = "/ability_backend/system/start_teach_mode"
TEACH_START_MANIP = "/manipulator/start_teach_mode"
TEACH_END = "/manipulator/end_teach_mode"
MANUAL_GET = "/manipulator/get_manual_mode"
MANUAL_SET = "/manipulator/set_manual_mode"

ARM_AXES_TOPIC = "/ability_backend/system/manipulator_axes_velocity_command"
ARM_TOOL_TOPIC = "/ability_backend/system/manipulator_tool_velocity_command"
BASE_JOG_TOPIC = "/ability_backend/system/mobile_joystick_command"

#: Conservative caps. The HMI can go faster; software jogging must not.
MAX_ARM_AXIS_VEL = 0.2
MAX_ARM_TOOL_VEL = 0.05
MAX_BASE_VEL = 0.15
MAX_BASE_YAW = 0.3

DEFAULT_ARM_AXES_TYPE = "system_backend/ManipulatorAxesVelocityCommand"
DEFAULT_ARM_TOOL_TYPE = "system_backend/ManipulatorToolVelocityCommand"
DEFAULT_BASE_JOG_TYPE = "system_backend/MobileJoystickCommand"


@dataclass
class PendantAction:
    name: str
    ok: bool
    detail: str = ""
    reply: dict[str, Any] | None = None


class Pendant:
    """Joystick, UR freedrive, and deadman jogging through Ability ROS."""

    def __init__(
        self,
        ros: AbilityRosClient,
        *,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.ros = ros
        self.log = log or logger.info

    def probe(self) -> dict[str, str]:
        """Read-only: service and topic types the HMI uses. Safe on a live cell."""
        services = (
            JOYSTICK_START,
            JOYSTICK_STOP,
            TEACH_START_SYSTEM,
            TEACH_START_MANIP,
            TEACH_END,
            MANUAL_GET,
            MANUAL_SET,
        )
        topics = (ARM_AXES_TOPIC, ARM_TOOL_TOPIC, BASE_JOG_TOPIC)
        types: dict[str, str] = {}
        for service in services:
            try:
                types[service] = self.ros.service_type(service)
            except RobotApiError as exc:
                types[service] = f"error: {exc}"
        for topic in topics:
            try:
                types[topic] = self.ros.topic_type(topic)
            except RobotApiError as exc:
                types[topic] = f"error: {exc}"
        return types

    def start_joystick(self) -> PendantAction:
        return self._call("start_joystick", JOYSTICK_START)

    def stop_joystick(self) -> PendantAction:
        return self._call("stop_joystick", JOYSTICK_STOP)

    def start_teach_mode(self) -> PendantAction:
        """UR freedrive. Tries the manipulator service first, then the system one."""
        action = self._call("start_teach_mode", TEACH_START_MANIP)
        if action.ok:
            return action
        self.log(f"manipulator teach-mode refused ({action.detail}); trying the system service")
        return self._call("start_teach_mode", TEACH_START_SYSTEM)

    def end_teach_mode(self) -> PendantAction:
        return self._call("end_teach_mode", TEACH_END)

    def manual_mode(self) -> bool:
        reply = self.ros.call_service(MANUAL_GET) or {}
        return bool(reply.get("response"))

    def set_manual_mode(self, enabled: bool) -> PendantAction:
        """UR pendant manual/freedrive bit, not the Ability Automatic selector."""
        return self._call(
            "set_manual_mode",
            MANUAL_SET,
            {"request": bool(enabled)},
        )

    def jog_arm_axes(
        self,
        velocities: Sequence[float],
        *,
        duration: float,
        execute: bool = False,
        max_abs: float = MAX_ARM_AXIS_VEL,
        rate: float = 10.0,
        type_name: str = DEFAULT_ARM_AXES_TYPE,
    ) -> PendantAction:
        if len(velocities) != 6:
            raise ValueError(f"arm axis jog wants 6 velocities, got {len(velocities)}")
        clipped = _clip(velocities, max_abs)
        stop = _axes_command("", [0.0] * 6)
        live = _axes_command("", clipped)
        return self._jog(
            "jog_arm_axes",
            ARM_AXES_TOPIC,
            live,
            type_name=type_name,
            duration=duration,
            execute=execute,
            rate=rate,
            stop_message=stop,
            needs_token=True,
        )

    def jog_arm_tool(
        self,
        linear: Sequence[float],
        angular: Sequence[float] | None = None,
        *,
        duration: float,
        execute: bool = False,
        max_linear: float = MAX_ARM_TOOL_VEL,
        max_angular: float = MAX_ARM_AXIS_VEL,
        rate: float = 10.0,
        type_name: str = DEFAULT_ARM_TOOL_TYPE,
    ) -> PendantAction:
        lin = _clip(_pad3(linear), max_linear)
        ang = _clip(_pad3(angular or (0.0, 0.0, 0.0)), max_angular)
        live = _tool_command("", _twist(lin, ang))
        stop = _tool_command("", _twist((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
        return self._jog(
            "jog_arm_tool",
            ARM_TOOL_TOPIC,
            live,
            type_name=type_name,
            duration=duration,
            execute=execute,
            rate=rate,
            stop_message=stop,
            needs_token=True,
        )

    def jog_base(
        self,
        linear_x: float = 0.0,
        linear_y: float = 0.0,
        angular_z: float = 0.0,
        *,
        duration: float,
        execute: bool = False,
        max_linear: float = MAX_BASE_VEL,
        max_yaw: float = MAX_BASE_YAW,
        rate: float = 10.0,
        type_name: str = DEFAULT_BASE_JOG_TYPE,
    ) -> PendantAction:
        live = _base_command(
            "",
            (_clip_one(linear_x, max_linear), _clip_one(linear_y, max_linear), 0.0),
            (0.0, 0.0, _clip_one(angular_z, max_yaw)),
        )
        stop = _base_command("", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        return self._jog(
            "jog_base",
            BASE_JOG_TOPIC,
            live,
            type_name=type_name,
            duration=duration,
            execute=execute,
            rate=rate,
            stop_message=stop,
            needs_token=True,
        )

    def _call(
        self,
        name: str,
        service: str,
        args: Mapping[str, Any] | None = None,
    ) -> PendantAction:
        try:
            reply = self.ros.call_service(service, dict(args or {})) or {}
        except RobotApiError as exc:
            return PendantAction(name, False, str(exc))
        ok = bool(reply.get("success", True))
        detail = "" if ok else str(reply.get("error_message") or reply)
        if ok:
            self.log(f"pendant {name}: {service}")
        return PendantAction(name, ok, detail, reply)

    def _jog(
        self,
        name: str,
        topic: str,
        message: dict[str, Any],
        *,
        type_name: str,
        duration: float,
        execute: bool,
        rate: float,
        stop_message: dict[str, Any],
        needs_token: bool = False,
    ) -> PendantAction:
        if duration <= 0 or duration > 5.0:
            raise ValueError("jog duration must be in (0, 5] seconds")
        if not execute:
            return PendantAction(
                name,
                True,
                f"dry run: would publish {topic} for {duration:.2f}s then zero",
            )
        period = 1.0 / max(rate, 1.0)

        def _run(token: str) -> None:
            live = dict(message)
            stop = dict(stop_message)
            if needs_token:
                live["token_id"] = token
                stop["token_id"] = token
            deadline = time.monotonic() + duration
            try:
                while time.monotonic() < deadline:
                    self.ros.publish(topic, live, type_name=type_name)
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(period, remaining))
            finally:
                self.ros.publish(topic, stop, type_name=type_name)

        try:
            if needs_token:
                with ProgrammingSession(ros=self.ros) as session:
                    _run(session.token)
            else:
                _run("")
        except Exception as exc:
            return PendantAction(name, False, str(exc))
        self.log(f"pendant {name}: published {topic} for {duration:.2f}s then zero")
        return PendantAction(name, True, f"jogged {topic} for {duration:.2f}s")


def _clip(values: Sequence[float], limit: float) -> list[float]:
    return [_clip_one(float(v), limit) for v in values]


def _clip_one(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _pad3(values: Sequence[float]) -> tuple[float, float, float]:
    padded = list(values) + [0.0, 0.0, 0.0]
    return float(padded[0]), float(padded[1]), float(padded[2])


def _vector3(values: Sequence[float]) -> dict[str, float]:
    return {"x": float(values[0]), "y": float(values[1]), "z": float(values[2])}


def _twist(linear: Sequence[float], angular: Sequence[float]) -> dict[str, Any]:
    return {"linear": _vector3(linear), "angular": _vector3(angular)}


def _axes_command(token: str, dq: Sequence[float]) -> dict[str, Any]:
    return {"token_id": token, "uid": "", "dq": [float(v) for v in dq]}


def _tool_command(token: str, twist: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "token_id": token,
        "uid": "",
        "reference": "Base",
        "tool_name": "",
        "twist": dict(twist),
    }


def _base_command(
    token: str, linear: Sequence[float], angular: Sequence[float]
) -> dict[str, Any]:
    return {
        "token_id": token,
        "uid": "",
        "linear": _vector3(linear),
        "angular": _vector3(angular),
    }

"""Watching the base while it drives, and stopping it when it stops getting anywhere.

The MiR's scanners cannot be read from either API. There is no laser topic and no
detected-object endpoint, so this module cannot see an obstacle and cannot predict a
collision. What it can do is notice that the base has stopped making progress toward its
target and end the leg, which is the difference between a robot that leans on a box until
someone hits the e-stop and one that stops and says where it stopped.

Why that matters here rather than in the MiR's own safety system: Ability's approach drives
the base with MiR missions named ``Forward 1.45m without collision detection`` and
``ER Move To Position Mute``. Those reduce the protective fields and switch collision
detection off, so for part of every station approach the scanners have no authority to stop
anything. The scanners still see the object -- it draws on the MiR dashboard -- but nothing
acts on it. This watchdog is the only thing looking during that window.

Progress is the primary signal, and ``distance_to_next_target`` falling is the only evidence
that a drive is achieving anything. Motion on its own means nothing: a robot pushing into a
cardboard box still reports wheel velocity.

Motion does matter once it is paired with progress, and that pairing is what separates the
two tiers this module reports:

- **No progress and no motion.** The drive is getting nowhere: the MiR is refusing to plan,
  or is waiting for a path it will not find. Stopped gently with :func:`stop_base`, retried,
  and the MiR's own planner is given the chance to route around whatever it can see. This is
  the recovery that actually works, and it needs the robot to still be drivable afterwards.
- **No progress but the wheels are turning**, or a base that was driving and stopped dead
  short of its target, or the MiR reporting its own emergency or protective stop. The base is
  in contact with something, or something appeared in front of it. Stopped by latching the
  controller with :func:`~alab_control.mobile_robot_mir250.safety.emergency_stop`: no retry,
  no self-docking, and a person has to look at it and physically reset it.

The second tier is deliberately unforgiving. A latch strands the robot where it stopped and
costs someone a walk to the cell, which is the right price for not leaning on whatever it
found. Everything about it is tunable from ``stations.toml`` so a cell that turns out to trip
it spuriously can be softened without a code change -- but soften the thresholds, not the
principle.
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

logger = logging.getLogger(__name__)
from .clients import RobotApiError
from .safety import MUTE_SETTLE_S, emergency_stop, ensure_fields_unmuted

#: Ability publishes here when the base cannot proceed. Present on the cell since the
#: beginning and read by nothing until now, so it is treated as a corroborating signal
#: rather than the primary one: the topic publishes on change, so a poll can miss an edge.
BLOCKED_TOPIC = "/ability_backend/mobile_device_blocked"

#: The mobile driver's own status, whose ``error_msg`` carries MiR-side complaints that
#: never reach Ability's REST ``message``.
MOBILE_STATUS_TOPIC = "/mobile/status"

#: Stops the wheels without latching anything. The whole point of preferring this to an
#: emergency stop is that the robot has to be able to drive itself to the charger next.
STOP_SERVICE = "/mobile/stop"

#: The MiR state that means a mission is actually running.
MIR_EXECUTING = "Executing"

#: MiR ``state_id`` values that mean the base has already been stopped by its own safety
#: system. 10 is the emergency-stop state: a robot in it cannot move until someone resets it,
#: so retrying is not an option whatever put it there.
#:
#: Not yet confirmed on this cell is whether a protective-field trip also lands in 10 or
#: merely pauses the mission. If it turns out to be 10 and to clear itself, take 10 out of
#: ``hard_stop_state_ids`` in ``stations.toml``: a self-clearing stop should be handled by the
#: patient tier, which lets the MiR replan around the obstacle.
DEFAULT_HARD_STOP_STATE_IDS: tuple[int, ...] = (10,)

#: Text in the MiR's state or errors that means the base stopped hard rather than merely
#: failed to get anywhere. Matched case-insensitively as substrings.
#:
#: Every word here is load-bearing, and two of them are deliberately narrower than they look.
#: `collision detected` rather than `collision`, because Ability's own approach missions are
#: named `Forward 1.45m without collision detection` -- a needle of `collision` would latch the
#: robot on every station approach it ever makes. And `protective stop` is absent entirely:
#: with the fields live, a protective stop is the safety system working, and what follows is
#: the MiR routing around the obstacle, which latching would trade away.
#:
#: This is also why ``mission_text`` is not searched for these. Mission names are cell-authored
#: prose describing what the robot is *trying* to do, not what happened to it.
DEFAULT_HARD_STOP_NEEDLES: tuple[str, ...] = (
    "emergency",
    "collision detected",
    "bumper",
)

#: Front reach of the base from its centre, used to turn "where the robot stopped" into
#: "where its front bumper was". Overridden by the live footprint whenever the MiR
#: reports one; this is only the fallback.
DEFAULT_FRONT_REACH_M = 0.54

#: Prose the MiR puts in ``mission_text`` that means the path is not clear. Deliberately
#: empty by default: the strings are cell-specific and are meant to be filled in from an
#: instrumented run rather than guessed at, and a wrong needle here would stop missions
#: for no reason.
DEFAULT_MISSION_TEXT_NEEDLES: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObstructionSettings:
    """How patient to be before stopping a drive, and when to stop it hard.

    There are two tiers and the difference between them is what the robot is allowed to do
    next. A drive that is simply getting nowhere is stopped gently and retried, because the
    MiR's own planner routing around the object is the recovery that actually works. A drive
    that has hit something, or that stopped dead because something appeared, is stopped by
    latching the controller: no retry, no docking, a person has to come and look.

    ``stall_grace_s`` and ``impact_grace_s`` are the numbers that matter. Set them from a
    logged approach, not from taste.
    """

    stall_grace_s: float = 20.0
    blocked_grace_s: float = 8.0
    progress_epsilon_m: float = 0.05
    #: Re-approach attempts after an obstruction before the mission goes on hold.
    max_attempts: int = 2
    #: The station a second attempt routes through, so the approach starts from a
    #: different heading and the MiR plans a fresh path.
    detour_via: str = "Home"
    #: Check the ROS signals every Nth poll. Each check opens a websocket, so doing it
    #: every time would cost more than the MiR status read it is corroborating.
    ros_poll_every: int = 4
    mission_text_needles: tuple[str, ...] = DEFAULT_MISSION_TEXT_NEEDLES
    treat_mir_errors_as_obstruction: bool = True
    #: A jump this large in ``distance_to_next_target`` is a new target or a replan, not a
    #: failure to make progress, so the progress clock starts again. Without this, every
    #: waypoint the MiR passes would look like a drive that had stopped getting closer.
    target_jump_m: float = 0.5

    # -- the hard stop -----------------------------------------------------
    #: The master switch. Off means every stop is the gentle, retryable kind, which is
    #: only appropriate if a latch is somehow more dangerous than a collision.
    hard_stop: bool = True
    #: Reported speed at or above which the base is taken to be driving. Well clear of the
    #: measured noise floor: a parked MiR250 reports about 0.0002 m/s and 0.05 rad/s.
    moving_speed_mps: float = 0.05
    #: Wheels turning at ``moving_speed_mps`` while the target refuses to get closer for
    #: this long is what pushing something looks like from the outside. Much shorter than
    #: ``stall_grace_s``, because this is contact rather than indecision.
    impact_grace_s: float = 4.0
    #: A drive that was moving and is now stopped dead for this long, with the target still
    #: further away than ``arrival_epsilon_m``, is treated as something having appeared in
    #: front of the robot. The likeliest of these to need softening on a cell that pauses
    #: legitimately mid-path, which is why it has its own switch.
    hard_stop_on_sudden_stop: bool = True
    sudden_confirm_s: float = 3.0
    #: Only latch on a sudden stop while the protective fields are muted.
    #:
    #: With the fields live, a base stopping short of something is the MiR's safety system
    #: doing its job, and what follows is the MiR replanning around the obstacle -- the one
    #: recovery that actually works. Latching there would trade that away and turn every stray
    #: box into a walk to the cell with a reset key. With the fields muted, nothing is watching
    #: and nothing will replan, so a base that stops dead has been stopped by something, and
    #: the only safe reading is that it found it the hard way.
    sudden_stop_needs_muted_fields: bool = True
    #: Below this the base counts as stopped rather than slow.
    stopped_speed_mps: float = 0.02
    #: Above this it is turning on the spot, which is motion and not a sudden stop.
    turning_speed_radps: float = 0.15
    #: Nearer than this to the target, a stop is an arrival.
    arrival_epsilon_m: float = 0.3
    hard_stop_needles: tuple[str, ...] = DEFAULT_HARD_STOP_NEEDLES
    hard_stop_state_ids: tuple[int, ...] = DEFAULT_HARD_STOP_STATE_IDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "stall_grace_s": self.stall_grace_s,
            "blocked_grace_s": self.blocked_grace_s,
            "progress_epsilon_m": self.progress_epsilon_m,
            "max_attempts": self.max_attempts,
            "detour_via": self.detour_via,
            "ros_poll_every": self.ros_poll_every,
            "mission_text_needles": list(self.mission_text_needles),
            "treat_mir_errors_as_obstruction": self.treat_mir_errors_as_obstruction,
            "target_jump_m": self.target_jump_m,
            "hard_stop": self.hard_stop,
            "moving_speed_mps": self.moving_speed_mps,
            "impact_grace_s": self.impact_grace_s,
            "hard_stop_on_sudden_stop": self.hard_stop_on_sudden_stop,
            "sudden_confirm_s": self.sudden_confirm_s,
            "sudden_stop_needs_muted_fields": self.sudden_stop_needs_muted_fields,
            "stopped_speed_mps": self.stopped_speed_mps,
            "turning_speed_radps": self.turning_speed_radps,
            "arrival_epsilon_m": self.arrival_epsilon_m,
            "hard_stop_needles": list(self.hard_stop_needles),
            "hard_stop_state_ids": list(self.hard_stop_state_ids),
        }


DEFAULT_OBSTRUCTION_SETTINGS = ObstructionSettings()


@dataclass(frozen=True)
class MotionSample:
    """One reading of everything that says whether the base is getting anywhere.

    Kept as a plain value with no client attached so the detector can be driven from a
    scripted sequence in a test and from the robot in the cell through the same code.
    """

    at: float
    wall_clock: str = ""
    mir_state: str = ""
    #: The MiR's numeric state. Judged on in preference to the text, because the numbers
    #: are stable across firmware versions and the wording is not.
    mir_state_id: int | None = None
    distance_to_next_target: float | None = None
    velocity_linear: float = 0.0
    velocity_angular: float = 0.0
    muted: bool | None = None
    errors: tuple[str, ...] = ()
    mission_text: str = ""
    x: float | None = None
    y: float | None = None
    orientation_deg: float | None = None
    map_id: str = ""
    footprint: tuple[tuple[float, float], ...] = ()
    #: None where the topic said nothing within the timeout, which is not the same as False.
    blocked: bool | None = None
    mobile_error: str = ""

    @property
    def executing(self) -> bool:
        return self.mir_state == MIR_EXECUTING

    @property
    def has_target(self) -> bool:
        """Whether ``distance_to_next_target`` is reporting a real target.

        Zero means no target as often as it means arrival, so a zero is never treated as
        evidence of anything. Without this the detector would fire on every parked robot.
        """
        return (
            self.distance_to_next_target is not None
            and self.distance_to_next_target > 0.0
        )

    def driving(self, settings: "ObstructionSettings") -> bool:
        """Whether the wheels say the base is moving.

        Only ever asked alongside a progress question. On its own it means nothing: a base
        pushing a box across the floor, and a base slipping against something it cannot
        move, both report speed.
        """
        return abs(self.velocity_linear) >= settings.moving_speed_mps

    def stopped_dead(self, settings: "ObstructionSettings") -> bool:
        """Whether the base has stopped, rather than slowed down or turned on the spot.

        Turning counts as moving: the linear velocity of a base rotating to line up with a
        marker is near zero, and calling that a sudden stop would latch the controller in
        the middle of every normal approach.
        """
        return (
            abs(self.velocity_linear) <= settings.stopped_speed_mps
            and abs(self.velocity_angular) <= settings.turning_speed_radps
        )

    @property
    def front_reach_m(self) -> float:
        return max((abs(px) for px, _ in self.footprint), default=DEFAULT_FRONT_REACH_M)

    def front_edge(self) -> tuple[float, float] | None:
        """Where the front of the base was, in map coordinates.

        This is as close as the cell can get to the position of the obstruction: the
        robot stopped with something in front of it, and the front face is the last place
        that something can be. It is not a sensed object position and must not be
        described as one.
        """
        if self.x is None or self.y is None or self.orientation_deg is None:
            return None
        heading = math.radians(self.orientation_deg)
        reach = self.front_reach_m
        return (self.x + reach * math.cos(heading), self.y + reach * math.sin(heading))

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_clock": self.wall_clock,
            "mir_state": self.mir_state,
            "mir_state_id": self.mir_state_id,
            "distance_to_next_target": self.distance_to_next_target,
            "velocity_linear": self.velocity_linear,
            "velocity_angular": self.velocity_angular,
            "muted": self.muted,
            "errors": list(self.errors),
            "mission_text": self.mission_text,
            "x": self.x,
            "y": self.y,
            "orientation_deg": self.orientation_deg,
            "map_id": self.map_id,
            "blocked": self.blocked,
            "mobile_error": self.mobile_error,
        }


@dataclass(frozen=True)
class Obstruction:
    """Why a drive was stopped, and everything a person needs to go and look.

    ``obstruction_point`` is the front face of the base, not a sensed object. Whoever
    reads this is walking to a spot on the floor, so the honest label matters more than
    the precision claim.
    """

    reason: str
    signal: str
    station: str
    leg_index: int
    sample: MotionSample
    settings: ObstructionSettings = DEFAULT_OBSTRUCTION_SETTINGS
    stalled_for_s: float = 0.0
    detected_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )
    attempts: int = 0
    #: Set when the fields were muted at the moment of the stop, which means the stop
    #: happened inside one of Ability's unprotected approach segments.
    unprotected: bool = False
    #: True when the evidence is contact or a sudden stop rather than a drive that never
    #: got anywhere. The robot is emergency-stopped for these and does not retry.
    hard: bool = False

    @property
    def robot_pose(self) -> dict[str, float] | None:
        if self.sample.x is None or self.sample.y is None:
            return None
        return {
            "x": self.sample.x,
            "y": self.sample.y,
            "orientation_deg": self.sample.orientation_deg or 0.0,
        }

    @property
    def obstruction_point(self) -> dict[str, float] | None:
        point = self.sample.front_edge()
        if point is None:
            return None
        return {"x": point[0], "y": point[1]}

    def where(self) -> str:
        """One line naming the spot on the floor to go and inspect."""
        point = self.obstruction_point
        pose = self.robot_pose
        if point is None or pose is None:
            return "the MiR did not report a position, so the spot is not known"
        return (
            f"the base stopped at ({pose['x']:.2f}, {pose['y']:.2f}) facing "
            f"{pose['orientation_deg']:.0f} deg, so whatever is in the way is at about "
            f"({point['x']:.2f}, {point['y']:.2f}) on map {self.sample.map_id or 'unknown'}"
        )

    def describe(self) -> str:
        lines = [
            f"{self.reason} while driving to {self.station} (leg {self.leg_index + 1})",
            f"  {self.where()}",
            f"  signal: {self.signal}",
            f"  distance to target: {self.sample.distance_to_next_target}",
            f"  speed at the stop: {self.sample.velocity_linear:.3f} m/s linear, "
            f"{self.sample.velocity_angular:.3f} rad/s angular",
            f"  MiR state: {self.sample.mir_state!r} mission_text: "
            f"{self.sample.mission_text!r}",
        ]
        if self.hard:
            lines.append(
                "  treated as a collision or something appearing in the path, so the "
                "controller is emergency-stopped: no retry, and it needs a physical reset"
            )
        if self.sample.errors:
            lines.append(f"  MiR errors: {'; '.join(self.sample.errors)}")
        if self.unprotected:
            lines.append(
                "  the protective fields were muted at the moment of the stop, so this "
                "happened inside one of Ability's unprotected approach segments"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "signal": self.signal,
            "station": self.station,
            "leg_index": self.leg_index,
            "detected_at": self.detected_at,
            "stalled_for_s": self.stalled_for_s,
            "attempts": self.attempts,
            "unprotected": self.unprotected,
            "hard": self.hard,
            "robot_pose": self.robot_pose,
            "obstruction_point": self.obstruction_point,
            "map_id": self.sample.map_id,
            "where": self.where(),
            "signals": self.sample.to_dict(),
            "settings": self.settings.to_dict(),
        }


def parse_footprint(raw: Any) -> tuple[tuple[float, float], ...]:
    """The MiR reports its footprint as a JSON string inside the status JSON."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return ()
    if not isinstance(raw, Sequence):
        return ()
    points: list[tuple[float, float]] = []
    for corner in raw:
        if isinstance(corner, Mapping):
            try:
                points.append((float(corner["x"]), float(corner["y"])))
            except (KeyError, TypeError, ValueError):
                continue
            continue
        if isinstance(corner, Sequence) and not isinstance(corner, str) and len(corner) >= 2:
            try:
                points.append((float(corner[0]), float(corner[1])))
            except (TypeError, ValueError):
                continue
    return tuple(points)


def sample_from_status(status: Mapping[str, Any], *, at: float | None = None) -> MotionSample:
    """Turn one MiR ``GET /status`` into a reading. Needs no credentials."""
    position = status.get("position") or {}
    velocity = status.get("velocity") or {}
    errors = status.get("errors") or []
    return MotionSample(
        at=time.monotonic() if at is None else at,
        wall_clock=datetime.now().astimezone().isoformat(timespec="seconds"),
        mir_state=str(status.get("state_text") or ""),
        mir_state_id=_as_int(status.get("state_id")),
        distance_to_next_target=_as_float(status.get("distance_to_next_target")),
        velocity_linear=_as_float(velocity.get("linear")) or 0.0,
        velocity_angular=_as_float(velocity.get("angular")) or 0.0,
        muted=(
            bool(status["safety_system_muted"])
            if "safety_system_muted" in status
            else None
        ),
        errors=tuple(_error_text(error) for error in errors),
        mission_text=str(status.get("mission_text") or ""),
        x=_as_float(position.get("x")),
        y=_as_float(position.get("y")),
        orientation_deg=_as_float(position.get("orientation")),
        map_id=str(status.get("map_id") or ""),
        footprint=parse_footprint(status.get("footprint")),
    )


#: How long to wait for the two ROS topics. Measured on the cell: both publish often enough
#: that a one-second wait catches them every time, where 0.6 s missed half the reads. The
#: websocket connect itself occasionally takes several seconds regardless of this, which is
#: why these are read after the MiR status and only every few ticks.
ROS_SIGNAL_TIMEOUT_S = 1.0


def read_ros_signals(
    ros: Any, *, timeout: float = ROS_SIGNAL_TIMEOUT_S
) -> tuple[bool | None, str]:
    """The blocked flag and the mobile driver's error text, best effort.

    Both are corroboration, never the only evidence. A topic that says nothing within the
    timeout has not told us the robot is fine, so silence reads as unknown rather than as
    False. Every failure is swallowed -- a watchdog that raises because rosbridge was busy
    would fail the leg it is supposed to be protecting.

    On the cell these are ``std_msgs/Bool`` on ``/ability_backend/mobile_device_blocked`` and
    ``er_hwl_ros/MobileDeviceStatus`` on ``/mobile/status``, both published continuously
    rather than only on change, which is what makes polling them viable at all.
    """
    blocked: bool | None = None
    error = ""
    try:
        for message in ros.topic_messages(BLOCKED_TOPIC, count=1, timeout=timeout):
            blocked = bool(
                message.get("data", message.get("blocked", message.get("response")))
            )
    except Exception:  # noqa: BLE001 - see the docstring
        blocked = None
    try:
        for message in ros.topic_messages(MOBILE_STATUS_TOPIC, count=1, timeout=timeout):
            payload = message.get("mobile_driver_status") or message
            error = str(payload.get("error_msg") or "")
    except Exception:  # noqa: BLE001
        error = ""
    return blocked, error


class ObstructionWatch:
    """Decides whether a drive in progress has been stopped by something in the way.

    Reading and judging are separate on purpose: ``judge`` is pure, so the grace periods
    can be tested against a scripted sequence and a fake clock instead of against a robot
    and a cardboard box.
    """

    def __init__(
        self,
        mir: Any,
        ros: Any = None,
        *,
        station: str = "",
        leg_index: int = -1,
        settings: ObstructionSettings = DEFAULT_OBSTRUCTION_SETTINGS,
        log: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.mir = mir
        self.ros = ros
        self.station = station
        self.leg_index = leg_index
        self.settings = settings
        self.log = log or logger.info
        self.clock = clock

        self.last: MotionSample | None = None
        #: True once the fields have been seen muted during this leg. Recorded rather than
        #: acted on, so the unprotected windows finally appear in the record.
        self.saw_mute = False
        self._closest: float | None = None
        self._progress_at: float | None = None
        self._blocked_since: float | None = None
        #: The collision detector stays disarmed until the drive has been seen to get closer
        #: to its target at least once. Ability backs the base out of a station before it
        #: drives anywhere, and during that retreat the distance to the next target grows
        #: while the wheels turn, which is the exact signature of pushing something.
        self._made_progress = False
        self._stopped_since: float | None = None
        self._was_driving = False
        self._ticks = 0

    # -- reading -----------------------------------------------------------

    def sample(self) -> MotionSample:
        """One reading, MiR first and the ROS corroboration only every few ticks.

        The order and the timestamp both matter. The MiR status is one cheap HTTP GET and
        carries the primary signal, so it goes first and is stamped before anything slower
        runs. A rosbridge read that takes several seconds -- which happens -- then delays the
        *next* sample rather than corrupting this one's timing, so the stall timer keeps
        measuring real elapsed time.
        """
        status = self.mir.status()
        reading = sample_from_status(status, at=self.clock())
        self._ticks += 1
        every = max(1, self.settings.ros_poll_every)
        if self.ros is not None and self._ticks % every == 0:
            blocked, error = read_ros_signals(self.ros)
            reading = replace(reading, blocked=blocked, mobile_error=error)
        return reading

    def check(self) -> Obstruction | None:
        """Read the cell and return an obstruction if there is one. Never raises.

        A status read that fails is not a verdict: the MiR web service drops requests
        under load, and stopping a mission because of one missed poll would be worse than
        the thing this guards against.
        """
        try:
            reading = self.sample()
        except RobotApiError as error:
            logger.debug("obstruction watch could not read the MiR: %s", error)
            return None
        return self.judge(reading)

    # -- judging -----------------------------------------------------------

    def judge(self, reading: MotionSample) -> Obstruction | None:
        """Whether this reading, in the context of the ones before it, is an obstruction.

        The hard signals are asked first. They mean the base has hit something or has been
        stopped by something appearing, and the answer to those is to latch the controller,
        so they must not be pre-empted by a gentler verdict that would allow a retry.
        """
        self.last = reading
        if reading.muted:
            self.saw_mute = True
        self._track(reading)

        hard = self._hard_verdict(reading)
        if hard is not None:
            return hard

        if reading.errors and self.settings.treat_mir_errors_as_obstruction:
            return self._verdict(
                reading,
                "the MiR reported an error mid-drive",
                f"errors={'; '.join(reading.errors)}",
            )

        if reading.mobile_error:
            return self._verdict(
                reading,
                "the mobile driver reported an error mid-drive",
                f"{MOBILE_STATUS_TOPIC} error_msg={reading.mobile_error!r}",
            )

        needle = self._mission_text_needle(reading.mission_text)
        if needle:
            return self._verdict(
                reading,
                "the MiR says the path is not clear",
                f"mission_text contains {needle!r}",
            )

        blocked = self._blocked_verdict(reading)
        if blocked is not None:
            return blocked

        return self._stall_verdict(reading)

    def _track(self, reading: MotionSample) -> None:
        """Keep the progress and motion history every verdict below is judged against.

        Separated from the verdicts because two of them need the same history, and because
        the order the verdicts run in must not decide what the history says.
        """
        if not reading.executing or not reading.has_target:
            # Between missions, or no target to make progress against. Forget everything:
            # the next drive gets a clean slate rather than inheriting this one's stall.
            self._closest = None
            self._progress_at = None
            self._made_progress = False
            self._stopped_since = None
            self._was_driving = False
            return

        distance = float(reading.distance_to_next_target or 0.0)
        if self._closest is None:
            # The first sight of a target is not progress toward it.
            self._closest = distance
            self._progress_at = reading.at
        elif distance < self._closest - self.settings.progress_epsilon_m:
            self._closest = distance
            self._progress_at = reading.at
            self._made_progress = True
        elif distance > self._closest + self.settings.target_jump_m:
            # A new waypoint, or the MiR replanning. The old target is not the one being
            # driven to any more, so the clock starts again rather than reading the change
            # as a failure to get closer.
            self._closest = distance
            self._progress_at = reading.at
        elif self._progress_at is None:
            self._progress_at = reading.at

        if reading.driving(self.settings):
            self._was_driving = True
            self._stopped_since = None
        elif reading.stopped_dead(self.settings):
            if self._stopped_since is None:
                self._stopped_since = reading.at
        else:
            # Slowing down, or turning. Neither is a stop.
            self._stopped_since = None

    def _hard_verdict(self, reading: MotionSample) -> Obstruction | None:
        """The signals that mean stop now and do not try again."""
        if not self.settings.hard_stop:
            return None

        named = self._hard_needle(reading)
        if named:
            return self._verdict(
                reading,
                "the MiR reports the base was stopped by its own safety system",
                named,
                hard=True,
            )
        if reading.mir_state_id in self.settings.hard_stop_state_ids:
            return self._verdict(
                reading,
                "the MiR reports the base was stopped by its own safety system",
                f"MiR state_id={reading.mir_state_id} ({reading.mir_state!r})",
                hard=True,
            )

        impact = self._impact_verdict(reading)
        if impact is not None:
            return impact
        return self._sudden_stop_verdict(reading)

    def _hard_needle(self, reading: MotionSample) -> str:
        """The first hard-stop phrase found in what the MiR says happened to it.

        Not ``mission_text``: that is the name of the mission being attempted, and Ability's
        approaches are named after the collision detection they switch off. Anything to be
        matched there belongs in the patient tier's ``mission_text_needles``.
        """
        haystacks = [
            ("state_text", reading.mir_state),
            (MOBILE_STATUS_TOPIC, reading.mobile_error),
        ]
        haystacks.extend(("errors", error) for error in reading.errors)
        for needle in self.settings.hard_stop_needles:
            lowered = needle.lower()
            for where, text in haystacks:
                if text and lowered in text.lower():
                    return f"{where} contains {needle!r}: {text!r}"
        return ""

    def _impact_verdict(self, reading: MotionSample) -> Obstruction | None:
        """Wheels turning, target not getting closer: the base is pushing something.

        This is the signal that would have caught the collision this module was written
        after. A stalled drive and a drive pushing a box look identical in
        ``distance_to_next_target``; the difference is that the pushing one still reports
        speed, and the difference in what to do about it is total.
        """
        if not self._made_progress or self._progress_at is None:
            return None
        if not reading.driving(self.settings):
            return None
        distance = float(reading.distance_to_next_target or 0.0)
        if distance <= self.settings.arrival_epsilon_m:
            # Inside the arrival radius the base is shuffling into place against a marker or
            # a dock, and making no measurable progress while doing it is normal. Whatever it
            # is in contact with this close to the target is the station. The patient stall
            # detector still covers this window; it is only the latch that steps back.
            return None
        pushing_for = reading.at - self._progress_at
        if pushing_for < self.settings.impact_grace_s:
            return None
        return self._verdict(
            reading,
            "the base was driving into something: the wheels were turning but the target "
            "stopped getting closer",
            f"{reading.velocity_linear:.2f} m/s for {pushing_for:.0f}s with "
            f"distance_to_next_target stuck at {reading.distance_to_next_target:.2f} m",
            stalled_for_s=pushing_for,
            hard=True,
        )

    def _sudden_stop_verdict(self, reading: MotionSample) -> Obstruction | None:
        """Moving, then dead, with the target still well away: something appeared.

        Not judged on until the base has actually been seen driving during this leg, so a
        drive that has not started yet cannot fire it, and only outside the arrival radius,
        so stopping because it got there cannot either. By default it is also only judged on
        while the fields are muted -- see ``sudden_stop_needs_muted_fields`` for why the same
        reading means something different when the scanners have authority.
        """
        if not self.settings.hard_stop_on_sudden_stop:
            return None
        if self.settings.sudden_stop_needs_muted_fields and not reading.muted:
            return None
        if not self._was_driving or self._stopped_since is None:
            return None
        distance = float(reading.distance_to_next_target or 0.0)
        if distance <= self.settings.arrival_epsilon_m:
            return None
        stopped_for = reading.at - self._stopped_since
        if stopped_for < self.settings.sudden_confirm_s:
            return None
        return self._verdict(
            reading,
            "the base was driving and stopped dead short of its target with its protective "
            "fields muted",
            f"stopped for {stopped_for:.0f}s with {distance:.2f} m still to go, after "
            f"driving earlier in this leg",
            stalled_for_s=stopped_for,
            hard=True,
        )

    def _mission_text_needle(self, text: str) -> str:
        lowered = text.lower()
        for needle in self.settings.mission_text_needles:
            if needle.lower() in lowered:
                return needle
        return ""

    def _blocked_verdict(self, reading: MotionSample) -> Obstruction | None:
        if reading.blocked is not True:
            # False clears the timer; None leaves it alone, because a topic that said
            # nothing has not told us the robot is free.
            if reading.blocked is False:
                self._blocked_since = None
            return None
        if self._blocked_since is None:
            self._blocked_since = reading.at
            return None
        held = reading.at - self._blocked_since
        if held < self.settings.blocked_grace_s:
            return None
        return self._verdict(
            reading,
            "Ability reported the base blocked and it did not clear",
            f"{BLOCKED_TOPIC} true for {held:.0f}s",
            stalled_for_s=held,
        )

    def _stall_verdict(self, reading: MotionSample) -> Obstruction | None:
        """The patient signal: this drive is getting nowhere, whatever the reason.

        Reached only when nothing above fired, so by here the base is not pushing anything
        and has not been stopped hard. What is left is a drive that never got going, or one
        the MiR is refusing to plan, and for those a retry is the right answer.
        """
        if not reading.executing or not reading.has_target or self._progress_at is None:
            return None

        distance = float(reading.distance_to_next_target or 0.0)
        stalled = reading.at - self._progress_at
        if stalled < self.settings.stall_grace_s:
            return None
        return self._verdict(
            reading,
            "the base stopped making progress toward its target",
            f"distance_to_next_target stuck at {distance:.2f} m for {stalled:.0f}s "
            f"(within {self.settings.progress_epsilon_m} m)",
            stalled_for_s=stalled,
        )

    def _verdict(
        self,
        reading: MotionSample,
        reason: str,
        signal: str,
        *,
        stalled_for_s: float = 0.0,
        hard: bool = False,
    ) -> Obstruction:
        return Obstruction(
            reason=reason,
            signal=signal,
            station=self.station,
            leg_index=self.leg_index,
            sample=reading,
            settings=self.settings,
            stalled_for_s=stalled_for_s,
            unprotected=bool(reading.muted),
            hard=hard,
        )


@dataclass(frozen=True)
class StopStep:
    name: str
    ok: bool
    detail: str = ""


def stop_base(
    ros: Any,
    ability: Any,
    mir: Any,
    *,
    settle: float = MUTE_SETTLE_S,
    log: Callable[[str], None] | None = None,
) -> list[StopStep]:
    """Bring the base to a halt without latching anything.

    Order matters. The wheels stop first, because every further step takes a second or
    two and the robot is in contact with something. Ability is stopped second so ``Main``
    ends and the leg terminates rather than sitting in its drive block. The fields are
    restored last, before anything can be commanded to move again.

    For a drive that is merely getting nowhere, deliberately not
    :func:`~alab_control.mobile_robot_mir250.safety.emergency_stop`: that latches the
    controller and needs a physical reset, and spending a person's walk to the cell on a MiR
    that could not find a path would teach everyone to ignore the alarm. When the evidence is
    contact or something appearing, :func:`hard_stop` is used instead and the latch is the
    point. Every step reports instead of raising, because the caller already has a reason for
    stopping and must not lose it to a second failure.
    """
    say = log or logger.info
    steps: list[StopStep] = []

    try:
        reply = ros.call_service(STOP_SERVICE) or {}
        ok = bool(reply.get("success", True))
        steps.append(
            StopStep(
                "base_stopped",
                ok,
                f"{STOP_SERVICE} {'accepted' if ok else reply.get('error_message', 'refused')}",
            )
        )
    except Exception as error:  # noqa: BLE001 - the reason is the useful part
        steps.append(StopStep("base_stopped", False, f"{STOP_SERVICE} failed: {error}"))
    say(f"obstruction stop: {steps[-1].detail}")

    try:
        ability.stop()
        steps.append(StopStep("program_stopped", True, "Ability accepted the stop request"))
    except Exception as error:  # noqa: BLE001
        steps.append(StopStep("program_stopped", False, f"the Ability stop failed: {error}"))
    say(f"obstruction stop: {steps[-1].detail}")

    try:
        ensure_fields_unmuted(
            ros,
            mir,
            ability=ability,
            settle=settle,
            log=say,
            reason="after stopping for an obstruction",
        )
        steps.append(StopStep("fields_live", True, "protective fields are live again"))
    except Exception as error:  # noqa: BLE001
        steps.append(
            StopStep("fields_live", False, f"could not restore the protective fields: {error}")
        )
        say(f"obstruction stop: {steps[-1].detail}")
    return steps


def hard_stop(
    ros: Any,
    ability: Any,
    mir: Any,
    *,
    log: Callable[[str], None] | None = None,
) -> list[StopStep]:
    """Latch the controller, because the base has hit something or been stopped by something.

    The wheels are stopped first for the same reason as in :func:`stop_base` -- it is the one
    step that takes effect immediately and the robot is in contact with something -- and only
    then is the controller latched. Doing it the other way round would spend a second or two
    of contact time on the slower call.

    A latch is not a failure of this function; it is the product. The robot will not drive
    itself anywhere afterwards, including to the charger, and that is deliberate: a robot that
    has just collided with something should not be moving under its own steam past whatever it
    hit until a person has looked at both.
    """
    say = log or logger.warning
    steps: list[StopStep] = []

    try:
        reply = ros.call_service(STOP_SERVICE) or {}
        ok = bool(reply.get("success", True))
        steps.append(StopStep("base_stopped", ok, f"{STOP_SERVICE} {'accepted' if ok else 'refused'}"))
    except Exception as error:  # noqa: BLE001 - the latch below matters more than this
        steps.append(StopStep("base_stopped", False, f"{STOP_SERVICE} failed: {error}"))
    say(f"hard stop: {steps[-1].detail}")

    report = emergency_stop(ability, ros, mir, log=say)
    steps.append(
        StopStep(
            "controller_latched",
            report.ok,
            str(report),
        )
    )
    if not report.ok:
        # The one case where software cannot deliver what it promised. Say so in the words a
        # person needs to hear, rather than leaving it in a report nobody reads.
        say(
            "the emergency stop did not complete. Use the physical e-stop on the robot now "
            "and treat the base as unsafe to command."
        )
    return steps


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _error_text(error: Any) -> str:
    if isinstance(error, Mapping):
        code = error.get("code")
        description = error.get("description") or error.get("message") or ""
        module = error.get("module") or ""
        parts = [str(part) for part in (module, code, description) if part not in (None, "")]
        return " ".join(parts) or str(error)
    return str(error)

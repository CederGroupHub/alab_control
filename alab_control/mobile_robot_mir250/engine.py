"""Runs a mission leg by leg, and stops cleanly when asked.

The two rules this file exists to enforce:

**Interruption happens between legs, never inside one.** A leg is a single `Main`
invocation that ends with the gripper empty and `BasePosition` written. Aborting halfway
through leaves a crucible in the gripper and the cell needing a person, so a cancel or a
battery suspend that arrives mid-leg is honoured the moment that leg finishes. This is what
"safe boundary" means, and it is why every leg is small.

**No wait ignores the callbacks.** Waiting on Labman to free a quadrant is the one place a
mission can sit for many minutes, and a robot that waits there while its battery drains is
the failure the whole battery policy exists to prevent. Every wait in this file goes through
:meth:`MissionEngine.wait_for`, which polls the callbacks and raises rather than sleeping
through them.

The engine is deliberately ignorant of Labman, furnaces and racks. It is handed legs and it
runs them.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence

from .clients import (
    ATTENDED_STATES,
    IDLE_STATES,
    TYPE_STRING,
    AbilityClient,
    is_error_state,
)
from .errors import (
    BatterySuspend,
    LegFailed,
    MissionCancelled,
    MissionInterrupted,
    MobileRobotError,
    ObstructionHold,
)
from .mission import Leg, Mission, SampleMove

logger = logging.getLogger(__name__)

MAIN_PROGRAM = "Main"

#: How often the callbacks are consulted while waiting. Half a second is responsive enough
#: for a person clicking cancel and cheap enough to leave running for hours.
POLL_INTERVAL = 0.5

#: A leg is given this long to start moving before we conclude the controller never took it.
START_GRACE = 8.0

Reason = Callable[[], "bool | str"]


def interrupted_status(interruption: MissionInterrupted) -> str:
    """The mission status that goes with an interruption.

    Named rather than inlined because three places have to agree on it: the result the
    engine attaches, the driver's own `mission_status`, and the dashboard reading both.
    """
    if isinstance(interruption, MissionCancelled):
        return "cancelled"
    if isinstance(interruption, ObstructionHold):
        return "held"
    return "suspended"


def _reason(callback: Reason | None, default: str) -> str:
    """Normalise a callback that may return a bool or an explanation.

    Callers write `lambda: battery < 80` as often as they write a function returning a
    sentence, and both are useful; a bool becomes the default wording.
    """
    if callback is None:
        return ""
    answer = callback()
    if answer is True:
        return default
    if not answer:
        return ""
    return str(answer)


@dataclass(frozen=True)
class MissionEvent:
    """Something worth telling the operator about.

    Emitted through the `on_event` callback so the device can publish it to the dashboard
    and the task can mirror sample movements into AlabOS. The engine never writes to a
    database itself.
    """

    kind: str
    mission_id: str
    reason: str
    leg: Leg | None = None
    leg_index: int = -1
    legs_total: int = 0
    detail: str = ""
    moves: tuple[SampleMove, ...] = ()
    at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "mission_id": self.mission_id,
            "reason": self.reason,
            "leg_index": self.leg_index,
            "legs_total": self.legs_total,
            "leg": self.leg.to_dict() if self.leg else None,
            "detail": self.detail,
            "moves": [move.to_dict() for move in self.moves],
            "at": self.at,
        }

    def __str__(self) -> str:
        where = f" leg {self.leg_index + 1}/{self.legs_total}" if self.leg else ""
        return f"[{self.kind}]{where} {self.reason}"


@dataclass
class MissionResult:
    """What happened. Returned on success, and attached to an interruption."""

    mission: Mission
    legs_completed: int
    status: str
    detail: str = ""
    moves: tuple[SampleMove, ...] = ()

    @property
    def finished(self) -> bool:
        return self.legs_completed >= len(self.mission)

    @property
    def positions(self) -> dict[str, str]:
        """Where every sample actually ended up, replayed from the legs that ran."""
        return self.mission.positions_after(self.legs_completed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission.id,
            "status": self.status,
            "detail": self.detail,
            "legs_completed": self.legs_completed,
            "legs_total": len(self.mission),
            "positions": self.positions,
            "moves": [move.to_dict() for move in self.moves],
        }


class MissionEngine:
    """Executes missions against the Ability controller.

    `run_leg` is a seam: the real implementation loads `Main` over REST and waits, and the
    test double replaces just that. Everything about ordering, interruption and reporting is
    tested through the same code path the robot uses.
    """

    def __init__(
        self,
        ability: AbilityClient,
        *,
        log: Callable[[str], None] | None = None,
        poll: float = POLL_INTERVAL,
        leg_runner: Callable[[Leg], None] | None = None,
    ) -> None:
        self.ability = ability
        self.log = log or logger.info
        self.poll = poll
        #: How a leg is actually executed. The driver substitutes its retrying, field-muting
        #: version here, so a mission gets the full safety treatment rather than the bare
        #: `Main` invocation below. Kept as a hook rather than a subclass so the ordering and
        #: interruption logic has exactly one implementation.
        self.leg_runner: Callable[[Leg], None] = leg_runner or self.run_leg
        #: Called once per poll while a leg is in flight, and expected to raise if the leg
        #: must not continue. The driver puts its obstruction watch here. Left unset by
        #: default so a bare engine behaves exactly as it always did.
        self.mid_leg_check: Callable[[Leg], None] | None = None
        #: Set while a leg is in flight, so an interruption arriving now is deferred rather
        #: than dropped. Read by the dashboard to explain why cancel has not taken effect yet.
        self.pending: str = ""
        self.pending_kind: str = ""

    # -- the interruptible primitives --------------------------------------

    def wait_for(
        self,
        predicate: Callable[[], bool],
        reason: str,
        *,
        timeout: float | None = None,
        mission: Mission | None = None,
        leg: Leg | None = None,
        should_cancel: Reason | None = None,
        should_suspend: Reason | None = None,
        on_event: Callable[[MissionEvent], None] | None = None,
    ) -> None:
        """Wait until `predicate` is true, unless asked to stop first.

        This is the only sanctioned way to wait for anything outside the robot. A caller
        that sleeps in a loop of its own is the bug this method exists to make unnecessary:
        such a loop would hold the robot at Labman with a flat battery, which is precisely
        what we promised never to do.
        """
        started = time.monotonic()
        announced = False
        while not predicate():
            self._raise_if_asked_to_stop(
                mission=mission,
                leg=leg,
                should_cancel=should_cancel,
                should_suspend=should_suspend,
                on_event=on_event,
                while_doing=reason,
            )
            if not announced and mission is not None:
                self._emit(
                    on_event,
                    MissionEvent(
                        kind="waiting",
                        mission_id=mission.id,
                        reason=reason,
                        leg=leg,
                        leg_index=leg.index if leg else -1,
                        legs_total=len(mission),
                    ),
                )
                announced = True
            if timeout is not None and time.monotonic() - started > timeout:
                raise LegFailed(
                    f"gave up after {timeout:.0f}s waiting for {reason}",
                    leg_index=leg.index if leg else None,
                )
            time.sleep(self.poll)

    def _raise_if_asked_to_stop(
        self,
        *,
        mission: Mission | None,
        leg: Leg | None,
        should_cancel: Reason | None,
        should_suspend: Reason | None,
        on_event: Callable[[MissionEvent], None] | None,
        while_doing: str = "",
    ) -> None:
        """Cancel wins over a battery suspend: a cancelled mission will not resume, so
        there is nothing to charge up for beyond getting home, and the dock leg the caller
        adds afterwards handles that either way."""
        cancel = _reason(should_cancel, "the task was cancelled")
        if cancel:
            self._interrupt(
                MissionCancelled, cancel, mission, leg, on_event, while_doing, "cancelled"
            )
        suspend = _reason(should_suspend, "the battery fell below the working floor")
        if suspend:
            self._interrupt(
                BatterySuspend, suspend, mission, leg, on_event, while_doing, "suspended"
            )

    def _interrupt(
        self,
        kind: type[MissionInterrupted],
        reason: str,
        mission: Mission | None,
        leg: Leg | None,
        on_event: Callable[[MissionEvent], None] | None,
        while_doing: str,
        event_kind: str,
    ) -> None:
        index = leg.index if leg else None
        detail = f" while waiting for {while_doing}" if while_doing else ""
        if mission is not None:
            self._emit(
                on_event,
                MissionEvent(
                    kind=event_kind,
                    mission_id=mission.id,
                    reason=reason,
                    leg=leg,
                    leg_index=index if index is not None else -1,
                    legs_total=len(mission),
                    detail=(
                        f"stopping before leg {index + 1} of {len(mission)}"
                        if index is not None
                        else ""
                    ),
                ),
            )
        raise kind(
            f"{reason}{detail}",
            leg_index=index,
            held_resources=tuple(leg.resources) if leg else (),
        )

    # -- running -----------------------------------------------------------

    def run(
        self,
        mission: Mission,
        *,
        on_event: Callable[[MissionEvent], None] | None = None,
        should_cancel: Reason | None = None,
        should_suspend: Reason | None = None,
        before_leg: Callable[[Leg], None] | None = None,
        start_at: int = 0,
    ) -> MissionResult:
        """Run `mission` from `start_at`, and report what got done.

        `start_at` is how a suspended mission resumes: the leg that was about to run when
        the battery gave out runs once, not twice. Legs already completed are not repeated,
        which is the whole point of numbering them.

        `before_leg` is the caller's chance to book resources or hand over a quadrant. It
        runs inside the same interruption discipline as everything else.

        Raises `MissionCancelled` or `BatterySuspend` at a leg boundary. Both carry the leg
        index to resume from and the resources still held, so the caller can release a
        quadrant before the robot drives away.
        """
        total = len(mission)
        if start_at:
            self._emit(
                on_event,
                MissionEvent(
                    kind="mission_resumed",
                    mission_id=mission.id,
                    reason=f"picking up at leg {start_at + 1} of {total}",
                    legs_total=total,
                    leg_index=start_at,
                    leg=mission.leg(start_at) if start_at < total else None,
                ),
            )
        else:
            self._emit(
                on_event,
                MissionEvent(
                    kind="mission_started",
                    mission_id=mission.id,
                    reason=mission.description or str(mission),
                    legs_total=total,
                ),
            )

        done = start_at
        performed: list[SampleMove] = []
        try:
            for leg in mission.legs_from(start_at):
                # The boundary check. Anything asking us to stop is honoured here, before
                # the arm or the base commits to anything new.
                self._raise_if_asked_to_stop(
                    mission=mission,
                    leg=leg,
                    should_cancel=should_cancel,
                    should_suspend=should_suspend,
                    on_event=on_event,
                )
                if before_leg is not None:
                    before_leg(leg)
                    self._raise_if_asked_to_stop(
                        mission=mission,
                        leg=leg,
                        should_cancel=should_cancel,
                        should_suspend=should_suspend,
                        on_event=on_event,
                    )
                self._emit(
                    on_event,
                    MissionEvent(
                        kind="leg_started",
                        mission_id=mission.id,
                        reason=leg.reason,
                        leg=leg,
                        leg_index=leg.index,
                        legs_total=total,
                        moves=leg.moves,
                    ),
                )
                self._run_leg_recording_deferrals(
                    leg, should_cancel=should_cancel, should_suspend=should_suspend
                )
                done = leg.index + 1
                performed.extend(leg.moves)
                self._emit(
                    on_event,
                    MissionEvent(
                        kind="leg_finished",
                        mission_id=mission.id,
                        reason=leg.reason,
                        leg=leg,
                        leg_index=leg.index,
                        legs_total=total,
                        moves=leg.moves,
                    ),
                )
        except MissionInterrupted as interruption:
            interruption.result = MissionResult(
                mission=mission,
                legs_completed=done,
                status=interrupted_status(interruption),
                detail=str(interruption),
                moves=tuple(performed),
            )
            raise
        except MobileRobotError as failure:
            self._emit(
                on_event,
                MissionEvent(
                    kind="leg_failed",
                    mission_id=mission.id,
                    reason=str(failure),
                    leg=mission.leg(done) if done < total else None,
                    leg_index=done,
                    legs_total=total,
                ),
            )
            raise

        result = MissionResult(
            mission=mission,
            legs_completed=done,
            status="completed",
            moves=tuple(performed),
        )
        self._emit(
            on_event,
            MissionEvent(
                kind="mission_finished",
                mission_id=mission.id,
                reason=f"{total} legs, {len(mission.samples)} samples delivered",
                legs_total=total,
                leg_index=done,
                moves=result.moves,
            ),
        )
        return result

    def _run_leg_recording_deferrals(
        self,
        leg: Leg,
        *,
        should_cancel: Reason | None,
        should_suspend: Reason | None,
    ) -> None:
        """Run one leg, noting anything that asked us to stop while it was in flight.

        The note is what lets the dashboard say "cancelling after this leg" instead of
        appearing to ignore the button, and the boundary check at the top of the next
        iteration is what acts on it.
        """
        self.pending = ""
        self.pending_kind = ""
        try:
            self.leg_runner(leg)
        finally:
            cancel = _reason(should_cancel, "the task was cancelled")
            suspend = _reason(should_suspend, "the battery fell below the working floor")
            if cancel:
                self.pending, self.pending_kind = cancel, "cancel"
            elif suspend:
                self.pending, self.pending_kind = suspend, "suspend"
            if self.pending:
                self.log(
                    f"  {self.pending_kind} requested during leg {leg.index + 1} "
                    f"({self.pending}); stopping at the leg boundary"
                )

    def run_leg(self, leg: Leg) -> None:
        """Load `Main` with this leg's arguments, start it, and wait for it to finish.

        Uninterruptible by request. The whole design rests on `Main` running to the end of
        a leg so the gripper is empty when it stops; a caller wanting to stop sooner is
        served by the boundary checks around this call, not by cutting it short.

        `mid_leg_check` is the one exception, and only for a leg that moves the base. There
        the arm is parked and the payload is sitting on the robot's own rack, so stopping
        part way leaves the cell in a state that is just as known as a leg boundary --
        whereas cutting off an arm that is inside a furnace does not. The driver is
        responsible for only installing the check on those legs.
        """
        arguments = leg.main_arguments()
        self.log(f"  leg {leg.index + 1}: {leg} -- {leg.reason}")
        self.ability.wait_until_loadable()
        self.ability.load_program(MAIN_PROGRAM, arguments, arg_type=TYPE_STRING)
        loaded = self.ability.program_current() or {}
        if str(loaded.get("name", "")) != MAIN_PROGRAM:
            raise LegFailed(
                f"asked the controller for {MAIN_PROGRAM} but it loaded "
                f"{loaded.get('name')!r}",
                leg_index=leg.index,
            )
        self.ability.start()
        self._await_leg(leg)

    def _await_leg(self, leg: Leg) -> None:
        deadline = time.monotonic() + leg.deadline
        started = time.monotonic()
        moved = False
        last = ""
        while time.monotonic() < deadline:
            if self.mid_leg_check is not None:
                # Before reading Ability, because Ability reports a blocked drive only once
                # its own move times out, which on the cell is minutes of pushing later.
                self.mid_leg_check(leg)
            status = self.ability.status()
            state = str(status.get("state", ""))
            message = str(status.get("message") or "")
            if f"{state}|{message}" != last:
                self.log(f"    state={state!r} message={message!r}")
                last = f"{state}|{message}"
            if is_error_state(state):
                raise LegFailed(
                    f"{leg} failed: {state} {message!r}", leg_index=leg.index
                )
            if state in ATTENDED_STATES:
                raise LegFailed(
                    f"{leg}: controller went to {state!r}, someone has taken control "
                    f"from the pendant",
                    leg_index=leg.index,
                )
            if state not in IDLE_STATES:
                moved = True
            elif moved or time.monotonic() - started > START_GRACE:
                # Idle after having run, or idle for long enough that it never started.
                if not moved:
                    raise LegFailed(
                        f"{leg}: the controller stayed {state!r} and never began the leg",
                        leg_index=leg.index,
                    )
                return
            time.sleep(self.poll)
        raise LegFailed(
            f"{leg} did not finish within {leg.deadline:.0f}s, last seen {last!r}",
            leg_index=leg.index,
        )

    # -- plumbing ----------------------------------------------------------

    def _emit(
        self, on_event: Callable[[MissionEvent], None] | None, event: MissionEvent
    ) -> None:
        self.log(str(event))
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:  # noqa: BLE001 - a broken listener must not strand the robot
            logger.exception("mission event listener failed on %s", event.kind)


def dock_mission(
    charger: str,
    reason: str,
    *,
    route: str = "",
) -> Mission:
    """A one-leg mission that parks the robot on the charger.

    Used after a cancel and by the battery guard. It is a mission like any other so it shows
    up in the dashboard timeline with its reason, rather than the robot silently driving off.
    """
    from .mission import dock

    return Mission.build(
        [dock(charger, reason)],
        route=route or f"-> {charger}",
        description=reason,
    )


def go_home_mission(reason: str) -> Mission:
    """A one-leg mission back to the parking spot."""
    from .mission import travel

    return Mission.build([travel("Home", reason)], route="-> Home", description=reason)


def legs_summary(legs: Iterable[Leg]) -> list[str]:
    """One readable line per leg. For logs and for a maintenance prompt."""
    return [f"{leg.index + 1}. {leg} -- {leg.reason}" for leg in legs]


def moves_by_sample(moves: Sequence[SampleMove]) -> dict[str, SampleMove]:
    """The last move recorded for each sample, which is where it actually is."""
    out: dict[str, SampleMove] = {}
    for move in moves:
        out[move.sample] = move
    return out

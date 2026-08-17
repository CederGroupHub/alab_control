"""A mission as an ordered list of legs.

One leg is one invocation of `Main`. That is the whole idea: `Main` always ends with the
gripper empty and `BasePosition` written, so a leg boundary is a place where the cell's
state is known, and therefore a place where the mission can be interrupted and picked up
again. Nothing here interrupts anything -- `engine.py` does that -- but the shape of a
mission is what makes it possible.

Each leg also carries the sentence explaining why it exists, and the list of samples it
moves and where from and to. That is not decoration: it is what the dashboard shows, and
what the `Moving` task mirrors into AlabOS so the sample records follow the real crucibles.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Sequence

from .clients import MAIN_ARGUMENT_NONE, main_arguments

#: Generous, because a blocked drive is handled inside `Main` and we would rather wait than
#: abandon a leg that is about to succeed. Per-leg overrides exist for the outliers.
TRAVEL_TIMEOUT = 600.0
TRANSFER_TIMEOUT = 300.0
DOCK_TIMEOUT = 900.0


class LegKind(str, Enum):
    """What a leg does. The value is what appears in the dashboard and the logs."""

    TRAVEL = "travel"
    TRANSFER = "transfer"
    DOCK = "dock"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SampleMove:
    """One sample changing places, in AlabOS terms.

    A leg that moves a whole subrack produces one of these per crucible inside it, because
    AlabOS tracks crucibles, not subracks.
    """

    sample: str
    source: str
    destination: str
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample": self.sample,
            "source": self.source,
            "destination": self.destination,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class Leg:
    """One `Main` invocation, with the reason it is happening.

    A leg is either travel (the base moves, the arm does not) or a transfer (the arm moves,
    the base does not). `Main` takes both in the same five arguments and does one or the
    other depending on which are set to the string "None"; keeping them apart here is what
    lets the engine know whether the payload is in the gripper.
    """

    kind: LegKind
    #: Where the base is for this leg. For travel and docking, where it is going.
    station: str
    #: A sentence a person can read, shown verbatim in the dashboard timeline.
    reason: str

    source_region: str = MAIN_ARGUMENT_NONE
    source_slot: str = MAIN_ARGUMENT_NONE
    destination_region: str = MAIN_ARGUMENT_NONE
    destination_slot: str = MAIN_ARGUMENT_NONE

    moves: tuple[SampleMove, ...] = ()
    #: AlabOS devices that must be booked before this leg runs.
    resources: tuple[str, ...] = ()
    #: Whether the station's device needs handing over (a Labman quadrant does).
    take_control: bool = False
    timeout: float | None = None
    index: int = -1

    def __post_init__(self) -> None:
        if self.kind is LegKind.TRANSFER and self.source_region == MAIN_ARGUMENT_NONE:
            raise ValueError("a transfer leg needs a source region")
        if self.kind is not LegKind.TRANSFER and self.source_region != MAIN_ARGUMENT_NONE:
            raise ValueError(f"a {self.kind} leg must not carry transfer arguments")

    @property
    def samples(self) -> tuple[str, ...]:
        return tuple(move.sample for move in self.moves)

    @property
    def request_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for move in self.moves:
            if move.request_id and move.request_id not in seen:
                seen.append(move.request_id)
        return tuple(seen)

    @property
    def deadline(self) -> float:
        if self.timeout is not None:
            return self.timeout
        return {
            LegKind.TRAVEL: TRAVEL_TIMEOUT,
            LegKind.TRANSFER: TRANSFER_TIMEOUT,
            LegKind.DOCK: DOCK_TIMEOUT,
        }[self.kind]

    @property
    def moves_the_base(self) -> bool:
        return self.kind in (LegKind.TRAVEL, LegKind.DOCK)

    def main_arguments(self) -> dict[str, str]:
        """The five arguments `Main` is loaded with for this leg."""
        if self.moves_the_base:
            return main_arguments(target_base_position=self.station)
        return main_arguments(
            source_region=self.source_region,
            source_slot=self.source_slot,
            destination_region=self.destination_region,
            destination_slot=self.destination_slot,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": str(self.kind),
            "station": self.station,
            "reason": self.reason,
            "arguments": self.main_arguments(),
            "moves": [move.to_dict() for move in self.moves],
            "samples": list(self.samples),
            "resources": list(self.resources),
            "take_control": self.take_control,
        }

    def __str__(self) -> str:
        if self.moves_the_base:
            return f"{self.kind} to {self.station}"
        return (
            f"{self.kind} {self.source_region}/{self.source_slot} -> "
            f"{self.destination_region}/{self.destination_slot}"
        )


@dataclass(frozen=True)
class Mission:
    """An ordered list of legs that together serve a set of delivery requests."""

    legs: tuple[Leg, ...]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    #: "LABMAN -> BFT", for the dashboard header.
    route: str = ""
    description: str = ""
    request_ids: tuple[str, ...] = ()
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        )
    )

    @classmethod
    def build(cls, legs: Sequence[Leg], **kwargs: Any) -> "Mission":
        """Number the legs and collect the requests they serve."""
        numbered = tuple(replace(leg, index=i) for i, leg in enumerate(legs))
        requests: list[str] = list(kwargs.pop("request_ids", ()) or ())
        for leg in numbered:
            for request_id in leg.request_ids:
                if request_id not in requests:
                    requests.append(request_id)
        return cls(legs=numbered, request_ids=tuple(requests), **kwargs)

    def __len__(self) -> int:
        return len(self.legs)

    def __iter__(self):
        return iter(self.legs)

    def leg(self, index: int) -> Leg:
        return self.legs[index]

    def legs_from(self, index: int) -> tuple[Leg, ...]:
        return self.legs[index:]

    @property
    def samples(self) -> tuple[str, ...]:
        seen: list[str] = []
        for leg in self.legs:
            for sample in leg.samples:
                if sample not in seen:
                    seen.append(sample)
        return tuple(seen)

    @property
    def stations(self) -> tuple[str, ...]:
        """The stations visited, in order, with repeats collapsed."""
        out: list[str] = []
        for leg in self.legs:
            if leg.moves_the_base and (not out or out[-1] != leg.station):
                out.append(leg.station)
        return tuple(out)

    def moves(self) -> tuple[SampleMove, ...]:
        return tuple(move for leg in self.legs for move in leg.moves)

    def positions_after(self, legs_completed: int) -> dict[str, str]:
        """Where each sample is once `legs_completed` legs have run.

        Replayed from the legs rather than tracked, so it is correct for a mission that was
        suspended, resumed, or stopped part way -- which is exactly when someone wants to
        know where the crucibles ended up.
        """
        positions: dict[str, str] = {}
        for leg in self.legs[:legs_completed]:
            for move in leg.moves:
                positions.setdefault(move.sample, move.source)
                positions[move.sample] = move.destination
        return positions

    def carried_after(self, legs_completed: int, base_prefix: str) -> dict[str, str]:
        """The samples riding on the robot once `legs_completed` legs have run.

        `base_prefix` is the AlabOS device that owns the base positions, so this stays
        honest if the device is ever renamed.
        """
        return {
            sample: position
            for sample, position in self.positions_after(legs_completed).items()
            if position.startswith(f"{base_prefix}/")
        }

    def final_positions(self) -> dict[str, str]:
        """Where each sample ends up if the whole mission runs."""
        return self.positions_after(len(self.legs))

    def to_dict(
        self,
        legs_completed: int = 0,
        status: str = "pending",
        base_prefix: str = "",
        detail: str = "",
    ) -> dict[str, Any]:
        """The shape the dashboard reads. Progress is a parameter, not state."""
        current = (
            self.legs[legs_completed].to_dict() if legs_completed < len(self.legs) else None
        )
        return {
            "id": self.id,
            "route": self.route,
            "description": self.description,
            "status": status,
            "detail": detail,
            "created_at": self.created_at,
            "legs_completed": legs_completed,
            "legs_total": len(self.legs),
            "current_leg": current,
            "legs": [leg.to_dict() for leg in self.legs],
            "stations": list(self.stations),
            "request_ids": list(self.request_ids),
            "samples": list(self.samples),
            "positions": self.positions_after(legs_completed),
            "carried": self.carried_after(legs_completed, base_prefix)
            if base_prefix
            else {},
        }

    def __str__(self) -> str:
        return f"{self.route or 'mission'} ({len(self.legs)} legs, {len(self.samples)} samples)"


def travel(station: str, reason: str, **kwargs: Any) -> Leg:
    """A leg that drives the base to `station` and leaves the arm parked."""
    return Leg(kind=LegKind.TRAVEL, station=station, reason=reason, **kwargs)


def dock(station: str, reason: str, **kwargs: Any) -> Leg:
    """A leg that drives the base onto a charger."""
    return Leg(kind=LegKind.DOCK, station=station, reason=reason, **kwargs)


def transfer(
    station: str,
    reason: str,
    source_region: str,
    source_slot: str,
    destination_region: str,
    destination_slot: str,
    moves: Iterable[SampleMove] = (),
    **kwargs: Any,
) -> Leg:
    """A leg that moves one thing with the arm while the base stays put."""
    return Leg(
        kind=LegKind.TRANSFER,
        station=station,
        reason=reason,
        source_region=source_region,
        source_slot=source_slot,
        destination_region=destination_region,
        destination_slot=destination_slot,
        moves=tuple(moves),
        **kwargs,
    )

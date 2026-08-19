"""The record of a mission parked because something was in the way.

A held mission is the one state in this driver that outlives the process, because clearing
it is a physical act by a person who may not be there for hours. The file is the contract
between the robot and that person: it says where the obstruction was, which leg was
interrupted, and whether anyone has been to look yet.

Written the same way as :mod:`~alab_control.mobile_robot_mir250.poses`: one JSON file named
by ``MIR250_HOLD_FILE`` or defaulting under the user's home, rewritten whole on every
change. There is only ever one hold, because the driver runs one mission at a time.

What this file deliberately does not hold is the mission itself. Rebuilding a `Mission` from
disk would mean reconstructing bookings and sample positions from a summary and hoping they
still describe the lab, and a resume that is subtly wrong about where a crucible is would be
worse than no resume at all. The caller that was running the mission keeps it -- in memory
for a script, in AlabOS's own mission document for the lab -- and this file only records
which leg to hand back to it.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Environment variable naming the hold record.
HOLD_FILE_ENV = "MIR250_HOLD_FILE"


def runtime_file() -> Path:
    """Where the hold record is written."""
    configured = os.environ.get(HOLD_FILE_ENV)
    if configured:
        return Path(configured)
    return Path.home() / ".alab_control" / "mir250" / "hold.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class ObstructionHoldRecord:
    """One mission on hold, and what a person has to do about it."""

    reason: str = ""
    station: str = ""
    leg_index: int = 0
    legs_completed: int = 0
    legs_total: int = 0
    mission_id: str = ""
    mission_route: str = ""
    mission_description: str = ""
    leg_reason: str = ""
    attempts: int = 0
    created_at: str = field(default_factory=_now)
    #: The full :meth:`Obstruction.to_dict` payload, including the map coordinates.
    obstruction: dict[str, Any] = field(default_factory=dict)
    #: Where each sample was when the mission stopped, so nothing is lost track of.
    sample_positions: dict[str, str] = field(default_factory=dict)
    held_resources: list[str] = field(default_factory=list)
    #: The MiR map position created for this obstruction, when one could be.
    marker: str = ""
    #: True when the robot was emergency-stopped rather than stopped gently, so it is
    #: standing where it stopped and needs a physical reset before it can move at all.
    latched: bool = False
    cleared_at: str = ""
    cleared_by: str = ""
    cleared_note: str = ""

    @property
    def cleared(self) -> bool:
        """Whether a person has said the path is clear."""
        return bool(self.cleared_at)

    @property
    def obstruction_point(self) -> dict[str, float] | None:
        point = self.obstruction.get("obstruction_point")
        return point if isinstance(point, dict) else None

    def where(self) -> str:
        return str(self.obstruction.get("where") or "the position was not recorded")

    def describe(self) -> str:
        lines = [
            f"the mission is on hold before leg {self.leg_index + 1} of {self.legs_total}",
            f"  route     : {self.mission_route or self.mission_description or '-'}",
            f"  leg       : {self.leg_reason or f'travel to {self.station}'}",
            f"  reason    : {self.reason}",
            f"  where     : {self.where()}",
            f"  attempts  : {self.attempts}",
            f"  held since: {self.created_at}",
        ]
        if self.latched:
            lines.append(
                "  the robot was EMERGENCY-STOPPED and is standing where it stopped, not on "
                "the charger. It needs a physical reset at the robot before it can move."
            )
        if self.marker:
            lines.append(f"  marked on the MiR map as: {self.marker}")
        if self.sample_positions:
            carried = ", ".join(
                f"{sample} at {where}" for sample, where in sorted(self.sample_positions.items())
            )
            lines.append(f"  samples   : {carried}")
        lines.append(
            f"  cleared   : {self.cleared_at} by {self.cleared_by or 'someone'}"
            if self.cleared
            else "  cleared   : not yet. The mission will not resume until it is."
        )
        return "\n".join(lines)

    def prompt(self) -> str:
        """The operator-facing wording, for a maintenance request."""
        if self.latched:
            return (
                f"The mobile robot was EMERGENCY-STOPPED on its way to {self.station} "
                f"because it ran into something, or something appeared in front of it.\n\n"
                f"{self.reason}\n\n"
                f"{self.where()}\n\n"
                f"It is standing where it stopped, not on the charger, and it did not try "
                f"again. It is holding leg {self.leg_index + 1} of {self.legs_total} and "
                f"nothing is in the gripper.\n\n"
                "Go to the robot. Check it and whatever it met for damage before anything "
                "moves. Move what is in the way, then reset the emergency stop at the robot "
                "and confirm the base can be driven from the MiR interface. Only then choose "
                "whether the robot should carry on with the delivery."
            )
        return (
            f"The mobile robot stopped because something was in its way and could not get "
            f"to {self.station}.\n\n"
            f"{self.reason}\n\n"
            f"{self.where()}\n\n"
            f"It tried {self.attempts} time(s), including re-approaching from a different "
            f"heading, then parked itself on the charger. It is holding leg "
            f"{self.leg_index + 1} of {self.legs_total} and nothing is in the gripper.\n\n"
            "Go to the position above, find what is in the way and move it. Then choose "
            "whether the robot should carry on with the delivery."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "station": self.station,
            "leg_index": self.leg_index,
            "legs_completed": self.legs_completed,
            "legs_total": self.legs_total,
            "mission_id": self.mission_id,
            "mission_route": self.mission_route,
            "mission_description": self.mission_description,
            "leg_reason": self.leg_reason,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "obstruction": self.obstruction,
            "sample_positions": self.sample_positions,
            "held_resources": self.held_resources,
            "marker": self.marker,
            "latched": self.latched,
            "cleared_at": self.cleared_at,
            "cleared_by": self.cleared_by,
            "cleared_note": self.cleared_note,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ObstructionHoldRecord":
        known = {
            "reason": str(raw.get("reason") or ""),
            "station": str(raw.get("station") or ""),
            "leg_index": int(raw.get("leg_index") or 0),
            "legs_completed": int(raw.get("legs_completed") or 0),
            "legs_total": int(raw.get("legs_total") or 0),
            "mission_id": str(raw.get("mission_id") or ""),
            "mission_route": str(raw.get("mission_route") or ""),
            "mission_description": str(raw.get("mission_description") or ""),
            "leg_reason": str(raw.get("leg_reason") or ""),
            "attempts": int(raw.get("attempts") or 0),
            "created_at": str(raw.get("created_at") or _now()),
            "obstruction": dict(raw.get("obstruction") or {}),
            "sample_positions": dict(raw.get("sample_positions") or {}),
            "held_resources": list(raw.get("held_resources") or []),
            "marker": str(raw.get("marker") or ""),
            "latched": bool(raw.get("latched") or False),
            "cleared_at": str(raw.get("cleared_at") or ""),
            "cleared_by": str(raw.get("cleared_by") or ""),
            "cleared_note": str(raw.get("cleared_note") or ""),
        }
        return cls(**known)


def save(record: ObstructionHoldRecord, path: Path | str | None = None) -> Path:
    """Write the hold record, creating its directory if need be."""
    target = Path(path) if path else runtime_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    return target


def load(path: Path | str | None = None) -> ObstructionHoldRecord | None:
    """The current hold, or None when there is not one.

    A file that cannot be parsed is reported as no hold rather than as an error. The
    alternative is a corrupt scratch file that blocks every mission until someone deletes
    it by hand, which is a worse failure than losing one record.
    """
    target = Path(path) if path else runtime_file()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not raw:
        return None
    return ObstructionHoldRecord.from_dict(raw)


def active(path: Path | str | None = None) -> ObstructionHoldRecord | None:
    """The current hold if it is still waiting on a person, else None."""
    record = load(path)
    if record is None or record.cleared:
        return None
    return record


def mark_cleared(
    *,
    by: str = "",
    note: str = "",
    path: Path | str | None = None,
) -> ObstructionHoldRecord | None:
    """Record that a person has cleared the path. Returns the updated hold, or None.

    This is the whole handshake. Nothing else in the driver may set ``cleared_at``: the
    robot cannot know that a box has been carried away, so only a person saying so counts.
    """
    record = load(path)
    if record is None:
        return None
    record.cleared_at = _now()
    record.cleared_by = by
    record.cleared_note = note
    save(record, path)
    return record


def clear(path: Path | str | None = None) -> None:
    """Forget the hold entirely. Called once a resume has actually started."""
    target = Path(path) if path else runtime_file()
    try:
        target.unlink()
    except OSError:
        pass

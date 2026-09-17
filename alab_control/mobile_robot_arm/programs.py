"""Routing table for the station-scoped Ability programs.

``Main`` used to take five strings and pick a leaf from three if-ladders. Those ladders
live here now. Each movement loads one of the twelve programs on the controller:

* ``base_Home`` / ``base_Charging`` — direct HomeBase / Charging
* ``base_{STATION}`` — go or out via the ``action`` argument (``\"go\"`` / ``\"out\"``)
* ``robotarm_{STATION}`` — pick/place via region and slot arguments

``Main`` stays installed as the fallback when ``program_mode = \"main\"``.
"""

from __future__ import annotations

NONE = "None"

#: Base positions ``BaseHandler`` accepted as a target.
BASE_POSITIONS = (
    "Home",
    "Charging",
    "ChargingNoWait",
    "LABMAN",
    "BFT",
    "DASH",
    "SRS",
    "IXRD",
)

#: Where the robot must be before any station ``go`` will run. Station-to-station moves
#: still funnel through Home, as ``BaseHandler`` did.
HOME = "Home"

#: What to call a pose nobody can vouch for, after a failed move or a manual jog.
UNKNOWN = "Unknown"

#: Regions whose slot is a grid index rather than a named subrack.
SLOT_IS_AN_INDEX = ("BFT", "DASH")

#: Prefix of the robot-deck crucible regions, e.g. ``ROBOT_BASE/SubRackA``.
ON_ROBOT_CRUCIBLE_PREFIX = "ROBOT_BASE/"

#: Stations that have both a ``base_*`` and a ``robotarm_*`` program.
STATIONS = ("LABMAN", "BFT", "DASH", "SRS", "IXRD")

# --------------------------------------------------------------------------------------
# Base moves
# --------------------------------------------------------------------------------------

#: Target station -> program that drives there from Home.
GOTO: dict[str, str] = {
    "Home": "base_Home",
    "Charging": "base_Charging",
    # Same archive as Charging; the Charging leaf still waits when battery is low.
    "ChargingNoWait": "base_Charging",
    "LABMAN": "base_LABMAN",
    "BFT": "base_BFT",
    "DASH": "base_DASH",
    "SRS": "base_SRS",
    "IXRD": "base_IXRD",
}

#: Current station -> program that backs out of it (and typically ends at Home).
OUTFROM: dict[str, str] = {
    "LABMAN": "base_LABMAN",
    "BFT": "base_BFT",
    "DASH": "base_DASH",
    "SRS": "base_SRS",
    "IXRD": "base_IXRD",
    "Charging": "base_Home",
    "ChargingNoWait": "base_Home",
    "FurnaceWorkbenchCalibrationForMoving": "base_Home",
}

#: What the ladder did when ``BasePosition`` matched none of its branches: drive Home.
DEFAULT_OUTFROM = "base_Home"

#: Stations whose base program needs ``action=go`` / ``action=out``.
_BASE_ACTION_STATIONS = frozenset(STATIONS)

# --------------------------------------------------------------------------------------
# Arm moves — one program per station; region/slot select the leaf inside it
# --------------------------------------------------------------------------------------

#: (region, slot) pairs that ``robotarm_LABMAN`` can pick.
PICK_LABMAN = {
    ("LABMAN", slot) for slot in ("SubRackA", "SubRackB", "SubRackC", "SubRackD")
} | {
    ("ROBOT_BASE", slot) for slot in ("SubRackA", "SubRackB", "SubRackC", "SubRackD")
}

PLACE_LABMAN = {
    ("LABMAN", slot) for slot in ("SubRackA", "SubRackB", "SubRackC", "SubRackD")
} | {
    ("ROBOT_BASE", slot) for slot in ("SubRackA", "SubRackB", "SubRackC", "SubRackD")
}

PICK_SRS = {
    ("SRS", slot) for slot in ("SubRackA", "SubRackB", "SubRackC", "SubRackD")
}

PLACE_SRS_VERTICAL = {
    ("ROBOT_BASE", f"SubRack{letter}Vertical") for letter in "ABCD"
}

PLACE_IXRD = {
    ("IXRD", slot) for slot in ("SubRackA", "SubRackB", "SubRackC", "SubRackD")
}
PICK_IXRD_ROBOT = {
    ("ROBOT_BASE", f"SubRack{letter}Vertical_IXRD") for letter in "ABCD"
}
PLACE_IXRD_ROBOT = {
    ("ROBOT_BASE", f"SubRack{letter}Vertical") for letter in "ABCD"
}

#: Provenance: program name -> Main leaf (or dispatcher) it wraps.
ENTRY_PROGRAMS: dict[str, str] = {
    "base_Home": "HomeBase",
    "base_Charging": "Charging",
    "base_LABMAN": "Run(action=go|out)",
    "base_BFT": "Run(action=go|out)",
    "base_DASH": "Run(action=go|out)",
    "base_SRS": "Run(action=go|out)",
    "base_IXRD": "Run(action=go|out)",
    "robotarm_LABMAN": "Run(region/slot)",
    "robotarm_BFT": "Run(region/slot)",
    "robotarm_DASH": "Run(region/slot)",
    "robotarm_SRS": "Run(region/slot)",
    "robotarm_IXRD": "Run(region/slot)",
}


class UnsupportedRoute(ValueError):
    """The requested move has no program, the way ``Main`` threw NotImplementedError."""


def arguments(
    *,
    action: str = NONE,
    source_region: str = NONE,
    source_slot: str = NONE,
    destination_region: str = NONE,
    destination_slot: str = NONE,
    include_action: bool = False,
    include_arm: bool = False,
) -> dict[str, str]:
    """Named arguments for a split program load.

    Base station programs only need ``action``. Arm programs need the four region/slot
    keys. Unused keys stay the string ``\"None\"`` when included, matching Ability's
    convention.
    """
    out: dict[str, str] = {}
    if include_action:
        out["action"] = action
    if include_arm:
        out["source_region"] = source_region
        out["source_slot"] = source_slot
        out["destination_region"] = destination_region
        out["destination_slot"] = destination_slot
    return out


def _base_args(program: str, *, action: str | None = None) -> dict[str, str]:
    if program in {GOTO[s] for s in _BASE_ACTION_STATIONS} or program in {
        OUTFROM[s] for s in _BASE_ACTION_STATIONS if s in OUTFROM
    }:
        if action is None:
            raise UnsupportedRoute(f"{program} requires action go or out")
        return arguments(action=action, include_action=True)
    return {}


def resolve_base_move(current: str, target: str) -> list[tuple[str, dict[str, str]]]:
    """The programs to run to get the base from ``current`` to ``target``.

    Returns one step when already at Home or when Home is the target, and two when the
    robot has to back out of a station first. An empty list means it is already there.
    """
    if target not in GOTO:
        raise UnsupportedRoute(
            f"no program drives the base to {target!r}; "
            f"known targets are {sorted(GOTO)}"
        )
    if current == target:
        return []

    steps: list[tuple[str, dict[str, str]]] = []
    if current != HOME:
        out_program = OUTFROM.get(current, DEFAULT_OUTFROM)
        out_action = "out" if current in _BASE_ACTION_STATIONS else None
        steps.append((out_program, _base_args(out_program, action=out_action)))
        if target == HOME:
            return steps

    go_program = GOTO[target]
    go_action = "go" if target in _BASE_ACTION_STATIONS else None
    steps.append((go_program, _base_args(go_program, action=go_action)))
    return steps


def _robotarm_for(region: str, slot: str) -> str:
    if region in STATIONS:
        return f"robotarm_{region}"
    if region == "ROBOT_BASE" or region.startswith(ON_ROBOT_CRUCIBLE_PREFIX):
        if "IXRD" in slot or "IXRD" in region:
            return "robotarm_IXRD"
        if "Vertical" in slot or "Vertical" in region:
            return "robotarm_SRS"
        if region.startswith(ON_ROBOT_CRUCIBLE_PREFIX):
            # Deck crucible grid alone is ambiguous; prefer LABMAN. Transfers that
            # name BFT/DASH on the other end resolve via resolve_transfer instead.
            return "robotarm_LABMAN"
        return "robotarm_LABMAN"
    raise UnsupportedRoute(f"no robotarm program covers region {region!r}")


def _assert_pick_supported(region: str, slot: str, program: str) -> None:
    if program == "robotarm_BFT":
        if region == "BFT" or region.startswith(ON_ROBOT_CRUCIBLE_PREFIX):
            return
        raise UnsupportedRoute(f"no program can pick {slot!r} in region {region!r}")
    if program == "robotarm_DASH":
        if region != "DASH":
            raise UnsupportedRoute(f"no program can pick {slot!r} in region {region!r}")
        return
    if program == "robotarm_LABMAN":
        if (region, slot) not in PICK_LABMAN and not region.startswith(
            ON_ROBOT_CRUCIBLE_PREFIX
        ):
            raise UnsupportedRoute(f"no program can pick {slot!r} in region {region!r}")
        return
    if program == "robotarm_SRS":
        if region == "SRS" and slot in {"SubRackA", "SubRackB", "SubRackC", "SubRackD"}:
            return
        if region == "ROBOT_BASE" and (
            slot in {"SubRackA", "SubRackB", "SubRackC", "SubRackD"}
            or slot.endswith("Vertical")
        ):
            return
        raise UnsupportedRoute(f"no program can pick {slot!r} in region {region!r}")
    if program == "robotarm_IXRD":
        if (region, slot) in PICK_IXRD_ROBOT:
            return
        raise UnsupportedRoute(f"no program can pick {slot!r} in region {region!r}")
    raise UnsupportedRoute(f"no program can pick {slot!r} in region {region!r}")


def _assert_place_supported(region: str, slot: str, program: str) -> None:
    if program == "robotarm_BFT":
        if region == "BFT" or region.startswith(ON_ROBOT_CRUCIBLE_PREFIX):
            return
        raise UnsupportedRoute(f"no program can place {slot!r} in region {region!r}")
    if program == "robotarm_DASH":
        if region != "DASH":
            raise UnsupportedRoute(f"no program can place {slot!r} in region {region!r}")
        return
    if program == "robotarm_LABMAN":
        if (region, slot) not in PLACE_LABMAN and not region.startswith(
            ON_ROBOT_CRUCIBLE_PREFIX
        ):
            raise UnsupportedRoute(f"no program can place {slot!r} in region {region!r}")
        return
    if program == "robotarm_SRS":
        if region == "SRS" and slot in {"SubRackA", "SubRackB", "SubRackC", "SubRackD"}:
            return
        if region == "ROBOT_BASE":
            return
        raise UnsupportedRoute(f"no program can place {slot!r} in region {region!r}")
    if program == "robotarm_IXRD":
        if (region, slot) in PLACE_IXRD or (region, slot) in PLACE_IXRD_ROBOT:
            return
        if region == "ROBOT_BASE" and slot.endswith("Vertical"):
            return
        raise UnsupportedRoute(f"no program can place {slot!r} in region {region!r}")
    raise UnsupportedRoute(f"no program can place {slot!r} in region {region!r}")


def resolve_pick(region: str, slot: str) -> tuple[str, dict[str, str]]:
    """The program that picks ``slot`` out of ``region``."""
    program = _robotarm_for(region, slot)
    _assert_pick_supported(region, slot, program)
    return program, arguments(
        source_region=region,
        source_slot=slot,
        include_arm=True,
    )


def resolve_place(region: str, slot: str) -> tuple[str, dict[str, str]]:
    """The program that places into ``slot`` of ``region``."""
    program = _robotarm_for(region, slot)
    _assert_place_supported(region, slot, program)
    return program, arguments(
        destination_region=region,
        destination_slot=slot,
        include_arm=True,
    )


def resolve_transfer(
    source_region: str,
    source_slot: str,
    destination_region: str,
    destination_slot: str,
) -> tuple[str, dict[str, str]]:
    """One robotarm program that can do both the pick and the place.

    Chooses the station named on either side. Deck-only transfers use LABMAN's
    on-robot leaves unless a Vertical / IXRD slot forces SRS or IXRD.
    """
    if source_region in STATIONS:
        program = f"robotarm_{source_region}"
    elif destination_region in STATIONS:
        program = f"robotarm_{destination_region}"
    elif "IXRD" in source_slot or "IXRD" in destination_slot:
        program = "robotarm_IXRD"
    elif "Vertical" in source_slot or "Vertical" in destination_slot:
        program = "robotarm_SRS"
    else:
        program = _robotarm_for(source_region, source_slot)

    _assert_pick_supported(source_region, source_slot, program)
    _assert_place_supported(destination_region, destination_slot, program)
    return program, arguments(
        source_region=source_region,
        source_slot=source_slot,
        destination_region=destination_region,
        destination_slot=destination_slot,
        include_arm=True,
    )


def all_entry_programs() -> tuple[str, ...]:
    """Every program name the table can return, for cross-checking a deployment."""
    return tuple(sorted(ENTRY_PROGRAMS))

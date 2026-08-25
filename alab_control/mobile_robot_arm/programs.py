"""Routing table for the split Blockly programs.

The controller used to run one program, ``Main``, which took five strings and picked a
leaf function from three large if-ladders: ``BaseHandler`` on ``target_base_position``,
and ``PickHandler`` / ``PlaceHandler`` on ``robot_arm_region`` and ``robot_arm_slot``.
Those ladders were about 4000 lines of string matching. They live here now, and each
leaf is reachable directly as its own program.

Every entry program takes the same five arguments ``Main`` took, because the preamble
that reads them is Main's, lifted verbatim: it materialises ``target_base_position``,
``source_region``, ``source_slot``, ``destination_region`` and ``destination_slot``, and
converts the two slots to integers. A base move fills the first, a pick the source pair,
a place the destination pair, and whatever is unused stays the string ``"None"``, exactly
as it was when one program served every route.

Each entry program then sets ``robot_arm_region`` and ``robot_arm_slot`` from that pair
before calling its leaf, so the leaf sees the state it saw under ``Main``.

``ENTRY_PROGRAMS`` records which ``Main`` function each program wraps. It is the
provenance of the generated Blockly and the contract the generator checks itself
against, so keep it in step with what is deployed on the controller.
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
    "SEMEDS",
)

#: Where the robot must be before any ``Run_GoTo_*`` will run. ``BaseHandler`` funnelled
#: every station-to-station move through Home, and the generated programs keep that.
HOME = "Home"

#: What to call a pose nobody can vouch for, after a failed move or a manual jog. The
#: same word ``LoadAllVariables`` defaults ``BasePosition`` to, and it routes to
#: ``DEFAULT_OUTFROM`` -- drive Home and find out where we are from there.
UNKNOWN = "Unknown"

#: Regions whose slot is a grid index rather than a named subrack. The leaf works the
#: index out itself, so one program covers every slot.
SLOT_IS_AN_INDEX = ("BFT", "DASH")

#: Prefix of the robot-deck crucible regions, e.g. ``ROBOT_BASE/SubRackA``.
ON_ROBOT_CRUCIBLE_PREFIX = "ROBOT_BASE/"

# --------------------------------------------------------------------------------------
# Base moves
# --------------------------------------------------------------------------------------

#: Target station -> program that drives there from Home.
GOTO: dict[str, str] = {
    "Home": "Run_GoTo_Home",
    "Charging": "Run_GoTo_Charging",
    "ChargingNoWait": "Run_GoTo_ChargingNoWait",
    "LABMAN": "Run_GoTo_Labman",
    "BFT": "Run_GoTo_BFT",
    "DASH": "Run_GoTo_DASH",
    "SRS": "Run_GoTo_SRS",
    "IXRD": "Run_GoTo_IXRD",
    "SEMEDS": "Run_GoTo_SEMEDS",
}

#: Current station -> program that backs out of it and returns to Home. Leaving either
#: charger, or the furnace calibration pose, is just a drive Home, as in ``BaseHandler``.
OUTFROM: dict[str, str] = {
    "LABMAN": "Run_OutFrom_Labman",
    "BFT": "Run_OutFrom_BFT",
    "DASH": "Run_OutFrom_DASH",
    "SRS": "Run_OutFrom_SRS",
    "IXRD": "Run_OutFrom_IXRD",
    "SEMEDS": "Run_OutFrom_SEMEDS",
    "Charging": "Run_GoTo_Home",
    "ChargingNoWait": "Run_GoTo_Home",
    "FurnaceWorkbenchCalibrationForMoving": "Run_GoTo_Home",
}

#: What the ladder did when ``BasePosition`` matched none of its branches: drive Home.
#: Kept because that fallback is load bearing, the variable holds poses such as
#: ``FurnaceWorkbenchCalibrationForMoving`` that no dedicated exit covers.
DEFAULT_OUTFROM = "Run_GoTo_Home"

# --------------------------------------------------------------------------------------
# Arm moves
# --------------------------------------------------------------------------------------

#: (region, slot) -> program, for picks where the slot names a subrack.
PICK: dict[tuple[str, str], str] = {
    ("LABMAN", "SubRackA"): "Run_Pick_Labman_SubrackA",
    ("LABMAN", "SubRackB"): "Run_Pick_Labman_SubrackB",
    ("LABMAN", "SubRackC"): "Run_Pick_Labman_SubrackC",
    ("LABMAN", "SubRackD"): "Run_Pick_Labman_SubrackD",
    ("ROBOT_BASE", "SubRackA"): "Run_Pick_OnRobot_SubrackA",
    ("ROBOT_BASE", "SubRackB"): "Run_Pick_OnRobot_SubrackB",
    ("ROBOT_BASE", "SubRackC"): "Run_Pick_OnRobot_SubrackC",
    ("ROBOT_BASE", "SubRackD"): "Run_Pick_OnRobot_SubrackD",
    ("ROBOT_BASE", "SubRackAVertical"): "Run_Pick_OnRobot_SubrackAVertical",
    ("ROBOT_BASE", "SubRackBVertical"): "Run_Pick_OnRobot_SubrackBVertical",
    ("ROBOT_BASE", "SubRackCVertical"): "Run_Pick_OnRobot_SubrackCVertical",
    ("ROBOT_BASE", "SubRackDVertical"): "Run_Pick_OnRobot_SubrackDVertical",
    ("ROBOT_BASE", "SubRackAVertical_IXRD"): "Run_Pick_OnRobot_SubrackAVertical_IXRD",
    ("ROBOT_BASE", "SubRackBVertical_IXRD"): "Run_Pick_OnRobot_SubrackBVertical_IXRD",
    ("ROBOT_BASE", "SubRackCVertical_IXRD"): "Run_Pick_OnRobot_SubrackCVertical_IXRD",
    ("ROBOT_BASE", "SubRackDVertical_IXRD"): "Run_Pick_OnRobot_SubrackDVertical_IXRD",
    ("ROBOT_BASE", "SubRackDVertical_SEMEDS"): "Run_Pick_OnRobot_SubrackDVertical_SEMEDS",
    ("SRS", "SubRackA"): "Run_Pick_SRS_SubrackA",
    ("SRS", "SubRackB"): "Run_Pick_SRS_SubrackB",
    ("SRS", "SubRackC"): "Run_Pick_SRS_SubrackC",
    ("SRS", "SubRackD"): "Run_Pick_SRS_SubrackD",
}

#: (region, slot) -> program, for places where the slot names a subrack.
PLACE: dict[tuple[str, str], str] = {
    ("ROBOT_BASE", "SubRackA"): "Run_Place_OnRobot_SubrackA",
    ("ROBOT_BASE", "SubRackB"): "Run_Place_OnRobot_SubrackB",
    ("ROBOT_BASE", "SubRackC"): "Run_Place_OnRobot_SubrackC",
    ("ROBOT_BASE", "SubRackD"): "Run_Place_OnRobot_SubrackD",
    ("ROBOT_BASE", "SubRackAVertical"): "Run_Place_OnRobot_SubrackAVertical",
    ("ROBOT_BASE", "SubRackBVertical"): "Run_Place_OnRobot_SubrackBVertical",
    ("ROBOT_BASE", "SubRackCVertical"): "Run_Place_OnRobot_SubrackCVertical",
    ("ROBOT_BASE", "SubRackDVertical"): "Run_Place_OnRobot_SubrackDVertical",
    ("LABMAN", "SubRackA"): "Run_Place_Labman_SubrackA",
    ("LABMAN", "SubRackB"): "Run_Place_Labman_SubrackB",
    ("LABMAN", "SubRackC"): "Run_Place_Labman_SubrackC",
    ("LABMAN", "SubRackD"): "Run_Place_Labman_SubrackD",
    ("SRS", "SubRackA"): "Run_Place_SRS_SubrackA",
    ("SRS", "SubRackB"): "Run_Place_SRS_SubrackB",
    ("SRS", "SubRackC"): "Run_Place_SRS_SubrackC",
    ("SRS", "SubRackD"): "Run_Place_SRS_SubrackD",
    ("IXRD", "SubRackA"): "Run_Place_IXRD_SubrackA",
    ("IXRD", "SubRackB"): "Run_Place_IXRD_SubrackB",
    ("IXRD", "SubRackC"): "Run_Place_IXRD_SubrackC",
    ("IXRD", "SubRackD"): "Run_Place_IXRD_SubrackD",
}

#: region -> program, for picks and places whose slot is a grid index.
PICK_BY_REGION: dict[str, str] = {
    "BFT": "Run_Pick_BFT",
    "DASH": "Run_Pick_DASH",
    # PickHandler's SEMEDS branch calls PickCrucibleRackDOnSRS, not the SEMEDS
    # function. Reproduced as found rather than corrected; see the note at the bottom.
    "SEMEDS": "Run_Pick_SEMEDS",
}
PLACE_BY_REGION: dict[str, str] = {
    "BFT": "Run_Place_BFT",
    "DASH": "Run_Place_DASH",
    "SEMEDS": "Run_Place_SEMEDS",
}

#: Robot-deck crucible transfers. The region carries the subrack, the slot the index.
PICK_ON_ROBOT_CRUCIBLE = "Run_Pick_OnRobot_Crucible"
PLACE_ON_ROBOT_CRUCIBLE = "Run_Place_OnRobot_Crucible"

# --------------------------------------------------------------------------------------
# Provenance: entry program -> the Main function it wraps
# --------------------------------------------------------------------------------------

ENTRY_PROGRAMS: dict[str, str] = {
    # Base moves
    "Run_GoTo_Home": "HomeBase",
    "Run_GoTo_Charging": "Charging",
    "Run_GoTo_ChargingNoWait": "Charging",
    "Run_GoTo_Labman": "Go to Labman",
    "Run_GoTo_BFT": "Go To Furnace Station",
    "Run_GoTo_DASH": "Go To DASH",
    "Run_GoTo_SRS": "Go To SubRackStorage Station",
    "Run_GoTo_IXRD": "GoToIXRDStation",
    "Run_GoTo_SEMEDS": "GoToSEMEDS",
    "Run_OutFrom_Labman": "Out from Labman",
    "Run_OutFrom_BFT": "Out From Furnace Station",
    "Run_OutFrom_DASH": "OutFromDASH_New",
    "Run_OutFrom_SRS": "Out From SubRackStorageStation",
    "Run_OutFrom_IXRD": "Out from IXRD",
    "Run_OutFrom_SEMEDS": "Out from SEMEDS",
    # Picks
    "Run_Pick_Labman_SubrackA": "PickCrucibleRackAOnLABMAN",
    "Run_Pick_Labman_SubrackB": "PickCrucibleRackBOnLABMAN",
    "Run_Pick_Labman_SubrackC": "PickCrucibleRackCOnLABMAN",
    "Run_Pick_Labman_SubrackD": "PickCrucibleRackDOnLABMAN",
    "Run_Pick_OnRobot_SubrackA": "PickCrucibleRackAOnRobot",
    "Run_Pick_OnRobot_SubrackB": "PickCrucibleRackBOnRobot",
    "Run_Pick_OnRobot_SubrackC": "PickCrucibleRackCOnRobot",
    "Run_Pick_OnRobot_SubrackD": "PickCrucibleRackDOnRobot",
    "Run_Pick_OnRobot_SubrackAVertical": "PickCrucibleRackAVerticalOnRobot",
    "Run_Pick_OnRobot_SubrackBVertical": "PickCrucibleRackBVerticalOnRobot",
    "Run_Pick_OnRobot_SubrackCVertical": "PickCrucibleRackCVerticalOnRobot",
    "Run_Pick_OnRobot_SubrackDVertical": "PickCrucibleRackDVerticalOnRobot",
    "Run_Pick_OnRobot_SubrackAVertical_IXRD": "PickCrucibleRackAVerticalOnRobot_IXRD",
    "Run_Pick_OnRobot_SubrackBVertical_IXRD": "PickCrucibleRackBVerticalOnRobot_IXRD",
    "Run_Pick_OnRobot_SubrackCVertical_IXRD": "PickCrucibleRackCVerticalOnRobot_IXRD",
    "Run_Pick_OnRobot_SubrackDVertical_IXRD": "PickCrucibleRackDVerticalOnRobot_IXRD",
    "Run_Pick_OnRobot_SubrackDVertical_SEMEDS": "PickSEMRackVerticalOnRobot_SEMEDS",
    "Run_Pick_SRS_SubrackA": "PickCrucibleRackAOnSRS",
    "Run_Pick_SRS_SubrackB": "PickCrucibleRackBOnSRS",
    "Run_Pick_SRS_SubrackC": "PickCrucibleRackCOnSRS",
    "Run_Pick_SRS_SubrackD": "PickCrucibleRackDOnSRS",
    "Run_Pick_BFT": "BFT_PICK",
    "Run_Pick_DASH": "DASH_PICK",
    # Not the bare leaf: the four ROBOT_BASE/SubRack* branches load a different rack
    # origin before calling it, and that selection has to run in the same program as the
    # leaf, so it was lifted into On_Robot as its own function.
    "Run_Pick_OnRobot_Crucible": "PickCrucibleFromRobotBase",
    "Run_Pick_SEMEDS": "PickCrucibleRackDOnSRS",
    # Places
    "Run_Place_OnRobot_SubrackA": "PlaceCrucibleRackAOnRobot",
    "Run_Place_OnRobot_SubrackB": "PlaceCrucibleRackBOnRobot",
    "Run_Place_OnRobot_SubrackC": "PlaceCrucibleRackCOnRobot",
    "Run_Place_OnRobot_SubrackD": "PlaceCrucibleRackDOnRobot",
    "Run_Place_OnRobot_SubrackAVertical": "PlaceCrucibleRackAVerticalOnRobot",
    "Run_Place_OnRobot_SubrackBVertical": "PlaceCrucibleRackBVerticalOnRobot",
    "Run_Place_OnRobot_SubrackCVertical": "PlaceCrucibleRackCVerticalOnRobot",
    "Run_Place_OnRobot_SubrackDVertical": "PlaceCrucibleRackDVerticalOnRobot",
    "Run_Place_Labman_SubrackA": "PlaceCrucibleRackAOnLABMAN",
    "Run_Place_Labman_SubrackB": "PlaceCrucibleRackBOnLABMAN",
    "Run_Place_Labman_SubrackC": "PlaceCrucibleRackCOnLABMAN",
    "Run_Place_Labman_SubrackD": "PlaceCrucibleRackDOnLABMAN",
    "Run_Place_SRS_SubrackA": "PlaceCrucibleRackAOnSRS",
    "Run_Place_SRS_SubrackB": "PlaceCrucibleRackBOnSRS",
    "Run_Place_SRS_SubrackC": "PlaceCrucibleRackCOnSRS",
    "Run_Place_SRS_SubrackD": "PlaceCrucibleRackDOnSRS",
    "Run_Place_IXRD_SubrackA": "PlaceSubrackAIXRD",
    "Run_Place_IXRD_SubrackB": "PlaceSubrackBIXRD",
    "Run_Place_IXRD_SubrackC": "PlaceSubrackCIXRD",
    "Run_Place_IXRD_SubrackD": "PlaceSubrackDIXRD",
    "Run_Place_BFT": "BFT_PLACE",
    "Run_Place_DASH": "DASH_PLACE",
    "Run_Place_OnRobot_Crucible": "PlaceCrucibleOnRobotBase",
    "Run_Place_SEMEDS": "PlaceSEMEDSRack",
}


class UnsupportedRoute(ValueError):
    """The requested move has no program, the way ``Main`` threw NotImplementedError."""


def arguments(
    target_base_position: str = NONE,
    source_region: str = NONE,
    source_slot: str = NONE,
    destination_region: str = NONE,
    destination_slot: str = NONE,
) -> dict[str, str]:
    """The full argument set every entry program takes, unused keys left at ``"None"``."""
    return {
        "target_base_position": target_base_position,
        "source_region": source_region,
        "source_slot": source_slot,
        "destination_region": destination_region,
        "destination_slot": destination_slot,
    }


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
        steps.append(
            (OUTFROM.get(current, DEFAULT_OUTFROM), arguments(target_base_position=HOME))
        )
        # Leaving a charger already ends at Home, so asking to go there again is a no-op.
        if target == HOME:
            return steps

    steps.append((GOTO[target], arguments(target_base_position=target)))
    return steps


def _program_for(
    region: str, slot: str, by_pair: dict, by_region: dict, on_robot: str, what: str
) -> str:
    if region.startswith(ON_ROBOT_CRUCIBLE_PREFIX):
        return on_robot
    if region in by_region:
        return by_region[region]
    program = by_pair.get((region, slot))
    if program is None:
        raise UnsupportedRoute(f"no program can {what} {slot!r} in region {region!r}")
    return program


def resolve_pick(region: str, slot: str) -> tuple[str, dict[str, str]]:
    """The program that picks ``slot`` out of ``region``."""
    program = _program_for(
        region, slot, PICK, PICK_BY_REGION, PICK_ON_ROBOT_CRUCIBLE, "pick"
    )
    return program, arguments(source_region=region, source_slot=slot)


def resolve_place(region: str, slot: str) -> tuple[str, dict[str, str]]:
    """The program that places into ``slot`` of ``region``."""
    program = _program_for(
        region, slot, PLACE, PLACE_BY_REGION, PLACE_ON_ROBOT_CRUCIBLE, "place"
    )
    return program, arguments(destination_region=region, destination_slot=slot)


def all_entry_programs() -> tuple[str, ...]:
    """Every program name the table can return, for cross-checking a deployment."""
    return tuple(sorted(ENTRY_PROGRAMS))


#: Two entry programs deliberately wrap the same Main function.
#:
#: ``Charging`` is reached from both charger targets, which differ only in whether the
#: program waits for the charge to finish.
#:
#: ``PickCrucibleRackDOnSRS`` is reached from both the ``SRS``/``SubRackD`` branch and
#: the ``SEMEDS`` branch. The latter looks like a copy-paste slip in the original
#: Blockly, since every other SEMEDS route uses a SEMEDS function. It is reproduced
#: rather than corrected, so the split cannot be the thing that changed behaviour.
#: Worth fixing on the controller once the split itself is trusted.
SHARED_LEAVES = ("Charging", "PickCrucibleRackDOnSRS")

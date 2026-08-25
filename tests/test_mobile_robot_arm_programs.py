"""The split-program routing table that replaced Main's if-ladders."""

from __future__ import annotations

import pytest

from alab_control.mobile_robot_arm.programs import (
    DEFAULT_OUTFROM,
    ENTRY_PROGRAMS,
    GOTO,
    HOME,
    OUTFROM,
    SHARED_LEAVES,
    PICK,
    PICK_BY_REGION,
    PICK_ON_ROBOT_CRUCIBLE,
    PLACE,
    PLACE_BY_REGION,
    PLACE_ON_ROBOT_CRUCIBLE,
    UNKNOWN,
    UnsupportedRoute,
    arguments,
    resolve_base_move,
    resolve_pick,
    resolve_place,
)

#: The five Main took, because the preamble that reads them is Main's, lifted verbatim.
ARGUMENT_KEYS = {
    "target_base_position",
    "source_region",
    "source_slot",
    "destination_region",
    "destination_slot",
}


def _routed_programs() -> set[str]:
    """Every program name any lookup in the table can produce."""
    return (
        set(GOTO.values())
        | set(OUTFROM.values())
        | set(PICK.values())
        | set(PLACE.values())
        | set(PICK_BY_REGION.values())
        | set(PLACE_BY_REGION.values())
        | {PICK_ON_ROBOT_CRUCIBLE, PLACE_ON_ROBOT_CRUCIBLE}
    )


def test_every_routed_program_has_a_main_function_behind_it() -> None:
    """A route that names a program we cannot generate would fail only on hardware."""
    assert _routed_programs() <= set(ENTRY_PROGRAMS)


def test_no_entry_program_is_unreachable() -> None:
    """An entry program nothing routes to is dead weight on the controller."""
    assert set(ENTRY_PROGRAMS) == _routed_programs()


def test_each_main_function_is_wrapped_once() -> None:
    """Two programs wrapping one function is nearly always a copy-paste slip, so only
    the documented pair from Main is tolerated."""
    wrapped = [fn for fn in ENTRY_PROGRAMS.values() if fn not in SHARED_LEAVES]
    assert len(wrapped) == len(set(wrapped))


def test_arguments_always_carries_the_full_set() -> None:
    assert set(arguments().keys()) == ARGUMENT_KEYS
    assert set(arguments().values()) == {"None"}
    assert arguments(source_region="BFT", source_slot="3")["target_base_position"] == "None"


def test_a_pick_fills_the_source_pair_and_a_place_the_destination_pair() -> None:
    """Which pair is set is what tells the lifted prologue where to point the arm."""
    _, picked = resolve_pick("BFT", "3")
    assert (picked["source_region"], picked["source_slot"]) == ("BFT", "3")
    assert picked["destination_region"] == picked["destination_slot"] == "None"

    _, placed = resolve_place("BFT", "3")
    assert (placed["destination_region"], placed["destination_slot"]) == ("BFT", "3")
    assert placed["source_region"] == placed["source_slot"] == "None"


class TestBaseMoves:
    def test_from_home_is_a_single_leg(self) -> None:
        steps = resolve_base_move(HOME, "DASH")
        assert steps == [
            ("Run_GoTo_DASH", arguments(target_base_position="DASH"))
        ]

    def test_station_to_station_backs_out_through_home(self) -> None:
        """BaseHandler funnelled every move through Home; so does the table."""
        steps = resolve_base_move("LABMAN", "DASH")
        assert [name for name, _ in steps] == ["Run_OutFrom_Labman", "Run_GoTo_DASH"]

    def test_leaving_a_station_for_home_does_not_double_up(self) -> None:
        """Out from Labman already ends at Home, so no second leg."""
        assert [n for n, _ in resolve_base_move("LABMAN", HOME)] == [
            "Run_OutFrom_Labman"
        ]

    def test_leaving_the_charger_is_just_a_drive_home(self) -> None:
        for charger in ("Charging", "ChargingNoWait"):
            assert [n for n, _ in resolve_base_move(charger, HOME)] == ["Run_GoTo_Home"]

    def test_already_there_is_a_no_op(self) -> None:
        assert resolve_base_move("DASH", "DASH") == []

    def test_every_base_position_is_reachable(self) -> None:
        for target in GOTO:
            if target == HOME:
                continue
            assert resolve_base_move(HOME, target)
        # Home is reachable too, just not from itself.
        assert resolve_base_move("BFT", HOME)

    def test_unknown_target_is_refused(self) -> None:
        with pytest.raises(UnsupportedRoute, match="drives the base to"):
            resolve_base_move(HOME, "SLS")

    def test_unknown_origin_falls_back_to_driving_home(self) -> None:
        """BaseHandler's ladder ended in a plain HomeBase, and BasePosition really does
        hold poses like FurnaceWorkbenchCalibrationForMoving that have no exit branch."""
        assert [n for n, _ in resolve_base_move("SLS", "DASH")] == [
            DEFAULT_OUTFROM,
            "Run_GoTo_DASH",
        ]

    def test_an_unknown_pose_drives_home_before_anything_else(self) -> None:
        """What the device records after a failed drive, so it must route somewhere."""
        assert [n for n, _ in resolve_base_move(UNKNOWN, HOME)] == ["Run_GoTo_Home"]
        assert [n for n, _ in resolve_base_move(UNKNOWN, "BFT")] == [
            "Run_GoTo_Home",
            "Run_GoTo_BFT",
        ]

    def test_the_furnace_calibration_pose_can_be_left(self) -> None:
        assert [
            n for n, _ in resolve_base_move("FurnaceWorkbenchCalibrationForMoving", "BFT")
        ] == ["Run_GoTo_Home", "Run_GoTo_BFT"]


class TestArmMoves:
    def test_named_subrack_pick(self) -> None:
        program, args = resolve_pick("LABMAN", "SubRackA")
        assert program == "Run_Pick_Labman_SubrackA"
        assert args == arguments(source_region="LABMAN", source_slot="SubRackA")

    def test_named_subrack_place(self) -> None:
        program, _ = resolve_place("IXRD", "SubRackC")
        assert program == "Run_Place_IXRD_SubrackC"

    def test_grid_index_regions_share_one_program_per_region(self) -> None:
        """BFT_PICK works the grid position out from the slot, so slot stays data."""
        first, args_first = resolve_pick("BFT", "3")
        second, args_second = resolve_pick("BFT", "14")
        assert first == second == "Run_Pick_BFT"
        assert args_first["source_slot"] == "3"
        assert args_second["source_slot"] == "14"

    def test_robot_deck_crucible_carries_the_subrack_in_the_region(self) -> None:
        program, args = resolve_pick("ROBOT_BASE/SubRackB", "2")
        assert program == PICK_ON_ROBOT_CRUCIBLE
        assert args["source_region"] == "ROBOT_BASE/SubRackB"
        assert args["source_slot"] == "2"

        program, _ = resolve_place("ROBOT_BASE/SubRackD", "4")
        assert program == PLACE_ON_ROBOT_CRUCIBLE

    def test_vertical_variants_are_distinct_programs(self) -> None:
        plain, _ = resolve_pick("ROBOT_BASE", "SubRackA")
        vertical, _ = resolve_pick("ROBOT_BASE", "SubRackAVertical")
        ixrd, _ = resolve_pick("ROBOT_BASE", "SubRackAVertical_IXRD")
        assert len({plain, vertical, ixrd}) == 3

    def test_every_ladder_branch_resolves(self) -> None:
        for (region, slot) in PICK:
            assert resolve_pick(region, slot)
        for (region, slot) in PLACE:
            assert resolve_place(region, slot)

    def test_semeds_pick_keeps_mains_odd_target(self) -> None:
        """PickHandler's SEMEDS branch called an SRS function. Reproduced, not fixed."""
        program, _ = resolve_pick("SEMEDS", "1")
        assert program == "Run_Pick_SEMEDS"
        assert ENTRY_PROGRAMS[program] == "PickCrucibleRackDOnSRS"
        assert ENTRY_PROGRAMS["Run_Pick_SRS_SubrackD"] == "PickCrucibleRackDOnSRS"

    def test_unsupported_pick_is_refused(self) -> None:
        with pytest.raises(UnsupportedRoute, match="can pick"):
            resolve_pick("LABMAN", "SubRackZ")

    def test_unsupported_place_is_refused(self) -> None:
        with pytest.raises(UnsupportedRoute, match="can place"):
            resolve_place("SLS", "1")

    def test_a_region_valid_for_place_is_not_assumed_valid_for_pick(self) -> None:
        """Main could place into IXRD but never picked from it."""
        assert resolve_place("IXRD", "SubRackA")
        with pytest.raises(UnsupportedRoute):
            resolve_pick("IXRD", "SubRackA")


class TestEveryRouteAlabosCanAsk:
    """The whole vocabulary AlabOS can produce, resolved.

    The eight ``RobotArmMobile.pick_*`` methods validate their arguments and then hand
    ``move_robot_arm`` a region and slot; these are those arguments. Spelled out here
    rather than imported, because alab_control cannot import alab_one, so a changed
    ``pick_*`` signature has to be reflected here by hand.
    """

    SUBRACKS = ("SubRackA", "SubRackB", "SubRackC", "SubRackD")
    VERTICAL = tuple(name + "Vertical" for name in SUBRACKS)
    CRUCIBLES = tuple(str(n) for n in range(1, 5))
    GRID = tuple(str(n) for n in range(1, 17))
    #: What move_base_to is asked for, plus what charge() and charge_no_waiting() are.
    TARGETS = ("Home", "LABMAN", "BFT", "DASH", "SRS", "Charging", "ChargingNoWait")

    def test_every_target_is_reachable_from_every_pose_the_robot_can_hold(self) -> None:
        poses = (*GOTO, UNKNOWN, "FurnaceWorkbenchCalibrationForMoving")
        for pose in poses:
            for target in self.TARGETS:
                steps = resolve_base_move(pose, target)
                assert steps or pose == target
                assert all(name in ENTRY_PROGRAMS for name, _ in steps)

    def test_labman_subrack_transfers_resolve(self) -> None:
        for source in self.SUBRACKS:
            for destination in self.SUBRACKS:
                assert resolve_pick("LABMAN", source)
                assert resolve_place("ROBOT_BASE", destination)
                assert resolve_pick("ROBOT_BASE", source)
                assert resolve_place("LABMAN", destination)

    def test_srs_subrack_transfers_resolve(self) -> None:
        """Both SRS methods add the Vertical suffix before calling move_robot_arm."""
        for source in self.SUBRACKS:
            assert resolve_pick("SRS", source)
            assert resolve_place("SRS", source)
        for vertical in self.VERTICAL:
            assert resolve_place("ROBOT_BASE", vertical)
            assert resolve_pick("ROBOT_BASE", vertical)

    def test_grid_station_crucible_transfers_resolve(self) -> None:
        for station in ("BFT", "DASH"):
            for subrack in self.SUBRACKS:
                for crucible in self.CRUCIBLES:
                    assert resolve_pick(f"ROBOT_BASE/{subrack}", crucible)
                    assert resolve_place(f"ROBOT_BASE/{subrack}", crucible)
                for slot in self.GRID:
                    assert resolve_place(station, slot)
                    assert resolve_pick(station, slot)

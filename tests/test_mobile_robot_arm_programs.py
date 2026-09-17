"""Unit tests for the station-scoped split-program routing table."""

from __future__ import annotations

import pytest

from alab_control.mobile_robot_arm.programs import (
    DEFAULT_OUTFROM,
    ENTRY_PROGRAMS,
    GOTO,
    HOME,
    OUTFROM,
    UNKNOWN,
    UnsupportedRoute,
    arguments,
    resolve_base_move,
    resolve_pick,
    resolve_place,
    resolve_transfer,
)


class TestBaseMoves:
    def test_from_home_is_a_single_leg(self) -> None:
        steps = resolve_base_move(HOME, "DASH")
        assert steps == [("base_DASH", arguments(action="go", include_action=True))]

    def test_station_to_station_backs_out_then_goes(self) -> None:
        steps = resolve_base_move("LABMAN", "DASH")
        assert [name for name, _ in steps] == ["base_LABMAN", "base_DASH"]
        assert steps[0][1]["action"] == "out"
        assert steps[1][1]["action"] == "go"

    def test_leaving_a_station_for_home_is_out_only(self) -> None:
        assert [n for n, _ in resolve_base_move("LABMAN", HOME)] == ["base_LABMAN"]
        assert resolve_base_move("LABMAN", HOME)[0][1]["action"] == "out"

    def test_leaving_the_charger_is_base_home(self) -> None:
        for charger in ("Charging", "ChargingNoWait"):
            assert [n for n, _ in resolve_base_move(charger, HOME)] == ["base_Home"]

    def test_already_there_is_a_no_op(self) -> None:
        assert resolve_base_move("DASH", "DASH") == []

    def test_home_and_charging_carry_no_action(self) -> None:
        assert resolve_base_move(HOME, "Charging") == [("base_Charging", {})]
        assert resolve_base_move(HOME, HOME) == []

    def test_unknown_target_is_refused(self) -> None:
        with pytest.raises(UnsupportedRoute, match="drives the base to"):
            resolve_base_move(HOME, "SEMEDS")

    def test_unknown_origin_falls_back_to_home(self) -> None:
        steps = resolve_base_move("SLS", "DASH")
        assert [n for n, _ in steps] == [DEFAULT_OUTFROM, "base_DASH"]

    def test_unknown_pose_drives_home_before_anything_else(self) -> None:
        assert [n for n, _ in resolve_base_move(UNKNOWN, HOME)] == ["base_Home"]
        assert [n for n, _ in resolve_base_move(UNKNOWN, "BFT")] == [
            "base_Home",
            "base_BFT",
        ]


class TestArmMoves:
    def test_labman_pick(self) -> None:
        program, args = resolve_pick("LABMAN", "SubRackA")
        assert program == "robotarm_LABMAN"
        assert args["source_region"] == "LABMAN"
        assert args["source_slot"] == "SubRackA"
        assert args["destination_region"] == "None"

    def test_ixrd_place(self) -> None:
        program, _ = resolve_place("IXRD", "SubRackC")
        assert program == "robotarm_IXRD"

    def test_bft_grid_pick(self) -> None:
        first, a = resolve_pick("BFT", "3")
        second, b = resolve_pick("BFT", "14")
        assert first == second == "robotarm_BFT"
        assert a["source_slot"] == "3"
        assert b["source_slot"] == "14"

    def test_transfer_labman_to_deck_is_one_program(self) -> None:
        program, args = resolve_transfer(
            "LABMAN", "SubRackA", "ROBOT_BASE", "SubRackB"
        )
        assert program == "robotarm_LABMAN"
        assert args["source_region"] == "LABMAN"
        assert args["destination_region"] == "ROBOT_BASE"

    def test_transfer_deck_crucible_to_bft_is_robotarm_bft(self) -> None:
        program, args = resolve_transfer(
            "ROBOT_BASE/SubRackA", "1", "BFT", "2"
        )
        assert program == "robotarm_BFT"
        assert args["source_region"] == "ROBOT_BASE/SubRackA"
        assert args["source_slot"] == "1"
        assert args["destination_region"] == "BFT"
        assert args["destination_slot"] == "2"

    def test_transfer_bft_to_deck_crucible_is_robotarm_bft(self) -> None:
        program, args = resolve_transfer(
            "BFT", "3", "ROBOT_BASE/SubRackB", "4"
        )
        assert program == "robotarm_BFT"
        assert args["destination_region"] == "ROBOT_BASE/SubRackB"

    def test_unsupported_pick_is_refused(self) -> None:
        with pytest.raises(UnsupportedRoute, match="can pick"):
            resolve_pick("LABMAN", "SubRackZ")

    def test_ixrd_has_no_pick_from_station(self) -> None:
        with pytest.raises(UnsupportedRoute):
            resolve_pick("IXRD", "SubRackA")


class TestEntryPrograms:
    def test_every_goto_and_outfrom_is_listed(self) -> None:
        routed = set(GOTO.values()) | set(OUTFROM.values()) | {DEFAULT_OUTFROM}
        assert routed <= set(ENTRY_PROGRAMS)

    def test_robotarm_programs_are_listed(self) -> None:
        for station in ("LABMAN", "BFT", "DASH", "SRS", "IXRD"):
            assert f"robotarm_{station}" in ENTRY_PROGRAMS

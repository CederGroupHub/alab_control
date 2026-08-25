"""The driver that runs one program per movement instead of one program for all of them."""

from __future__ import annotations

import pytest

from alab_control.mobile_robot_arm.driver import SplitProgramRobot
from alab_control.mobile_robot_arm.programs import UNKNOWN, UnsupportedRoute


class FakeTransport:
    """Records what would have been run, and can be told to fail."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.ran: list[tuple[str, dict[str, str]]] = []
        self.fail_on = fail_on

    def run_program(self, program_name, arguments=None):
        if program_name == self.fail_on:
            raise RuntimeError(f"{program_name} failed on the cell")
        self.ran.append((program_name, arguments or {}))

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.ran]


class FakePositions:
    """Stands in for the controller's BasePosition, and counts the reads."""

    def __init__(self, where: str) -> None:
        self.where = where
        self.reads = 0

    def base_position(self) -> str:
        self.reads += 1
        return self.where


def robot(where: str = "Home", fail_on: str | None = None):
    transport, positions = FakeTransport(fail_on), FakePositions(where)
    return SplitProgramRobot(transport=transport, positions=positions), transport, positions


class TestBaseMoves:
    def test_from_home_is_one_program(self) -> None:
        arm, transport, _ = robot("Home")
        assert arm.move_base_to("BFT") == ["Run_GoTo_BFT"]
        assert transport.names == ["Run_GoTo_BFT"]

    def test_from_a_station_retreats_first(self) -> None:
        arm, transport, _ = robot("LABMAN")
        assert transport.names == []
        assert arm.move_base_to("BFT") == ["Run_OutFrom_Labman", "Run_GoTo_BFT"]
        assert transport.names == ["Run_OutFrom_Labman", "Run_GoTo_BFT"]

    def test_already_there_runs_nothing(self) -> None:
        arm, transport, _ = robot("DASH")
        assert arm.move_base_to("DASH") == []
        assert transport.ran == []

    def test_the_controller_is_asked_once_per_move(self) -> None:
        """Once, not per leg: the second leg's start is the first leg's end."""
        arm, _, positions = robot("LABMAN")
        arm.move_base_to("BFT")
        assert positions.reads == 1

    def test_a_supplied_position_is_used_instead_of_asking(self) -> None:
        arm, transport, positions = robot("Home")
        arm.move_base_to("BFT", current="LABMAN")
        assert positions.reads == 0
        assert transport.names == ["Run_OutFrom_Labman", "Run_GoTo_BFT"]

    def test_an_unknown_position_drives_home_first(self) -> None:
        """What the controller reports before anything has set BasePosition."""
        arm, transport, _ = robot(UNKNOWN)
        arm.move_base_to("BFT")
        assert transport.names == ["Run_GoTo_Home", "Run_GoTo_BFT"]

    def test_an_unroutable_target_runs_nothing(self) -> None:
        arm, transport, _ = robot("Home")
        with pytest.raises(UnsupportedRoute, match="drives the base to"):
            arm.move_base_to("SLS")
        assert transport.ran == []

    def test_a_failed_leg_stops_the_move(self) -> None:
        """The second leg must not run once the retreat has failed."""
        arm, transport, _ = robot("LABMAN", fail_on="Run_OutFrom_Labman")
        with pytest.raises(RuntimeError):
            arm.move_base_to("BFT")
        assert transport.ran == []

    def test_charging_is_a_base_move(self) -> None:
        arm, transport, _ = robot("LABMAN")
        assert arm.charge() == ["Run_OutFrom_Labman", "Run_GoTo_Charging"]
        arm, transport, _ = robot("Home")
        assert arm.charge_no_waiting() == ["Run_GoTo_ChargingNoWait"]

    def test_homing_works_from_anywhere(self) -> None:
        expected = {
            "Home": [],
            "LABMAN": ["Run_OutFrom_Labman"],
            "Charging": ["Run_GoTo_Home"],
            UNKNOWN: ["Run_GoTo_Home"],
        }
        for start, programs in expected.items():
            arm, transport, _ = robot(start)
            assert arm.home_base() == programs
            assert transport.names == programs


class TestArmMoves:
    def test_a_transfer_is_a_pick_then_a_place(self) -> None:
        arm, transport, _ = robot()
        assert arm.transfer("LABMAN", "SubRackA", "ROBOT_BASE", "SubRackB") == [
            "Run_Pick_Labman_SubrackA",
            "Run_Place_OnRobot_SubrackB",
        ]
        assert transport.names == [
            "Run_Pick_Labman_SubrackA",
            "Run_Place_OnRobot_SubrackB",
        ]

    def test_a_transfer_needs_no_base_position(self) -> None:
        """The arm does not move the base, so nothing should be asked of it."""
        arm, _, positions = robot()
        arm.transfer("LABMAN", "SubRackA", "ROBOT_BASE", "SubRackB")
        assert positions.reads == 0

    def test_an_unroutable_destination_is_caught_before_the_pick(self) -> None:
        """Otherwise the arm ends up holding something with nowhere to put it."""
        arm, transport, _ = robot()
        with pytest.raises(UnsupportedRoute, match="can place"):
            arm.transfer("LABMAN", "SubRackA", "SLS", "1")
        assert transport.ran == []

    def test_the_pick_carries_the_source_pair_and_the_place_the_destination(self) -> None:
        arm, transport, _ = robot()
        arm.transfer("BFT", "7", "ROBOT_BASE/SubRackA", "2")
        (_, picked), (_, placed) = transport.ran
        assert (picked["source_region"], picked["source_slot"]) == ("BFT", "7")
        assert picked["destination_region"] == "None"
        assert (placed["destination_region"], placed["destination_slot"]) == (
            "ROBOT_BASE/SubRackA",
            "2",
        )
        assert placed["source_region"] == "None"

    def test_a_pick_and_a_place_can_be_run_alone(self) -> None:
        arm, transport, _ = robot()
        assert arm.pick("SRS", "SubRackC") == "Run_Pick_SRS_SubrackC"
        assert arm.place("IXRD", "SubRackC") == "Run_Place_IXRD_SubrackC"
        assert len(transport.ran) == 2


def test_nothing_is_constructed_until_it_is_needed() -> None:
    """Building the client talks to the robot, so it must not happen on construction."""
    arm = SplitProgramRobot(ip="192.0.2.1")
    assert arm._transport is None
    assert arm._positions is None

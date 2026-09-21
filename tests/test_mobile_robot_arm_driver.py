"""Unit tests for SplitProgramRobot (no hardware)."""

from __future__ import annotations

import pytest

from alab_control.mobile_robot_arm.driver import SplitProgramRobot
from alab_control.mobile_robot_arm.programs import UNKNOWN, UnsupportedRoute


class FakeTransport:
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
    def __init__(self, where: str) -> None:
        self.where = where
        self.reads = 0

    def base_position(self) -> str:
        self.reads += 1
        return self.where


def robot(where: str = "Home", fail_on: str | None = None):
    return SplitProgramRobot(
        transport=FakeTransport(fail_on=fail_on),
        positions=FakePositions(where),
    )


def test_already_at_target_runs_nothing() -> None:
    r = robot("Home")
    assert r.move_base_to("Home") == []
    assert r.transport.names == []


def test_from_home_to_station_runs_go() -> None:
    r = robot("Home")
    assert r.move_base_to("LABMAN") == ["base_LABMAN"]
    assert r.transport.ran == [("base_LABMAN", {"action": "go"})]


def test_station_to_station_runs_out_then_go() -> None:
    r = robot("LABMAN")
    assert r.move_base_to("DASH") == ["base_LABMAN", "base_DASH"]
    assert r.transport.names == ["base_LABMAN", "base_DASH"]
    assert r.transport.ran[0][1]["action"] == "out"
    assert r.transport.ran[1][1]["action"] == "go"


def test_charger_to_home() -> None:
    r = robot("Charging")
    assert r.move_base_to("Home") == ["base_Home"]


def test_reads_position_when_not_passed() -> None:
    r = robot("BFT")
    r.move_base_to("Home")
    assert r.positions.reads == 1


def test_passed_current_skips_position_read() -> None:
    r = robot("BFT")
    r.move_base_to("Home", current="LABMAN")
    assert r.positions.reads == 0
    assert r.transport.names == ["base_LABMAN"]


def test_transfer_one_program() -> None:
    r = robot("LABMAN")
    names = r.transfer("LABMAN", "SubRackA", "ROBOT_BASE", "SubRackB")
    assert names == ["robotarm_LABMAN"]
    args = r.transport.ran[0][1]
    assert args["source_region"] == "LABMAN"
    assert args["destination_slot"] == "SubRackB"


def test_unknown_target_raises_before_running() -> None:
    r = robot("Home")
    with pytest.raises(UnsupportedRoute):
        r.move_base_to("SEMEDS")
    assert r.transport.names == []


def test_unknown_pose_still_routes_via_home() -> None:
    r = robot(UNKNOWN)
    assert r.move_base_to("BFT") == ["base_Home", "base_BFT"]


class HomingTransport(FakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self.homes = 0

    def home_robot_arm(self) -> None:
        self.homes += 1
        self.ran.append(("HomeRobotArm", {}))


def test_move_base_folds_arm_before_driving() -> None:
    transport = HomingTransport()
    r = SplitProgramRobot(transport=transport, positions=FakePositions("Home"))
    assert r.move_base_to("LABMAN") == ["base_LABMAN"]
    assert transport.names == ["HomeRobotArm", "base_LABMAN"]
    assert transport.homes == 1


def test_already_at_target_does_not_fold() -> None:
    transport = HomingTransport()
    r = SplitProgramRobot(transport=transport, positions=FakePositions("Home"))
    assert r.move_base_to("Home") == []
    assert transport.homes == 0
    assert transport.names == []

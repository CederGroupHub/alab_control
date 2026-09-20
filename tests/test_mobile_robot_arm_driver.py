"""Unit tests for SplitProgramRobot (no hardware)."""

from __future__ import annotations

from typing import Any

import pytest

from alab_control.mobile_robot_arm.driver import (
    LABMAN_TAG_CALIBRATED_VARIABLE,
    LABMAN_TAG_VARIABLE,
    SplitProgramRobot,
    usable_labman_tag,
)
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


class FakeVariablePositions(FakePositions):
    def __init__(self, where: str, variables: dict[str, Any] | None = None) -> None:
        super().__init__(where)
        self.variables = dict(variables or {})
        self.edits: list[tuple[str, Any]] = []

    def variable(self, name: str) -> Any:
        if name not in self.variables:
            raise RuntimeError(f"unknown variable {name!r}")
        return self.variables[name]

    def edit_variable(self, name: str, value: Any) -> None:
        self.edits.append((name, value))
        self.variables[name] = value


SAVED_LABMAN_TAG = [-0.2186562880317527, 0.4808528224808302, 0.2711981644973904, 1.609756351367726, 0.008231016769650159, -3.133958980221916]


def robot(where: str = "Home", fail_on: str | None = None):
    return SplitProgramRobot(
        transport=FakeTransport(fail_on=fail_on),
        positions=FakePositions(where),
    )


def robot_with_vars(where: str = "LABMAN", variables: dict[str, Any] | None = None):
    return SplitProgramRobot(
        transport=FakeTransport(),
        positions=FakeVariablePositions(where, variables),
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


@pytest.mark.parametrize(
    "tag, expected",
    [
        (SAVED_LABMAN_TAG, True),
        ([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], False),
        ([0, 0, 0, 0, 0, 1e-9], False),
        (None, False),
        ([1.0, 2.0, 3.0], False),
        ("not-a-pose", False),
    ],
)
def test_usable_labman_tag(tag: Any, expected: bool) -> None:
    assert usable_labman_tag(tag) is expected


def test_saved_labman_tag_skips_camera_on_pick() -> None:
    r = robot_with_vars(variables={LABMAN_TAG_VARIABLE: SAVED_LABMAN_TAG})
    assert r.pick("LABMAN", "SubRackA") == "robotarm_LABMAN"
    assert r.positions.edits == [(LABMAN_TAG_CALIBRATED_VARIABLE, True)]
    assert r.positions.variables[LABMAN_TAG_CALIBRATED_VARIABLE] is True
    assert r.positions.variables[LABMAN_TAG_VARIABLE] == SAVED_LABMAN_TAG


def test_saved_labman_tag_skips_camera_on_transfer() -> None:
    r = robot_with_vars(variables={LABMAN_TAG_VARIABLE: SAVED_LABMAN_TAG})
    assert r.transfer("LABMAN", "SubRackA", "ROBOT_BASE", "SubRackB") == ["robotarm_LABMAN"]
    assert r.positions.edits == [(LABMAN_TAG_CALIBRATED_VARIABLE, True)]


def test_missing_labman_tag_leaves_camera_path() -> None:
    r = robot_with_vars(variables={})
    assert r.pick("LABMAN", "SubRackA") == "robotarm_LABMAN"
    assert r.positions.edits == []
    assert LABMAN_TAG_CALIBRATED_VARIABLE not in r.positions.variables


def test_zero_labman_tag_leaves_camera_path() -> None:
    r = robot_with_vars(variables={LABMAN_TAG_VARIABLE: [0.0] * 6})
    assert r.pick("LABMAN", "SubRackA") == "robotarm_LABMAN"
    assert r.positions.edits == []


def test_base_labman_does_not_touch_labman_flag() -> None:
    r = robot_with_vars("Home", variables={LABMAN_TAG_VARIABLE: SAVED_LABMAN_TAG})
    assert r.move_base_to("LABMAN") == ["base_LABMAN"]
    assert r.positions.edits == []


def test_other_robotarm_program_does_not_touch_labman_flag() -> None:
    r = robot_with_vars("BFT", variables={LABMAN_TAG_VARIABLE: SAVED_LABMAN_TAG})
    assert r.pick("BFT", "1") == "robotarm_BFT"
    assert r.positions.edits == []

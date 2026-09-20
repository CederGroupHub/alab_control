"""SimulatedMobileRobotArm drives the split routing table without a controller."""

from __future__ import annotations

import json

import pytest

from alab_control.mobile_robot_arm.driver import SplitProgramRobot
from alab_control.mobile_robot_arm.mobile_robot_arm import MRAState
from alab_control.mobile_robot_arm.simulated import SimulatedMobileRobotArm


def _write_script(path, script: dict) -> None:
    path.write_text(json.dumps(script), encoding="utf-8")


def _sim(tmp_path, script: dict | None = None, **kwargs) -> SimulatedMobileRobotArm:
    script_path = tmp_path / "script.json"
    _write_script(script_path, {"seconds_per_program": 0.0, **(script or {})})
    return SimulatedMobileRobotArm(
        script_path=script_path,
        event_log_path=tmp_path / "events.jsonl",
        **kwargs,
    )


def _events(tmp_path) -> list[dict]:
    text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_starts_docked_and_charging(tmp_path) -> None:
    sim = _sim(tmp_path)
    assert sim.base_position() == "Charging"
    assert sim.is_actually_charging() is True
    assert sim.is_running() is False
    assert sim.is_error() is False
    assert sim.get_state_and_message() == (MRAState.IDLE, "")


def test_split_robot_routes_and_base_position_follows(tmp_path) -> None:
    sim = _sim(tmp_path)
    robot = SplitProgramRobot(transport=sim, positions=sim)
    assert robot.move_base_to("LABMAN") == ["base_Home", "base_LABMAN"]
    assert sim.base_position() == "LABMAN"
    assert sim.is_actually_charging() is False
    assert robot.move_base_to("BFT") == ["base_LABMAN", "base_BFT"]
    assert sim.base_position() == "BFT"
    assert robot.move_base_to("Charging") == ["base_BFT", "base_Charging"]
    assert sim.base_position() == "Charging"
    assert sim.is_actually_charging() is True
    # Charging -> ChargingNoWait is the same pad: nothing runs.
    assert robot.move_base_to("ChargingNoWait") == []


def test_transfer_runs_one_arm_program(tmp_path) -> None:
    sim = _sim(tmp_path)
    robot = SplitProgramRobot(transport=sim, positions=sim)
    assert robot.transfer("LABMAN", "SubRackA", "ROBOT_BASE", "SubRackB") == ["robotarm_LABMAN"]
    program, arguments = sim.programs_run[-1]
    assert program == "robotarm_LABMAN"
    assert arguments["source_slot"] == "SubRackA"
    assert arguments["destination_slot"] == "SubRackB"


def test_program_takes_time(tmp_path) -> None:
    sim = _sim(tmp_path, {"seconds_per_program": 0.6})
    sim.load_program("base_LABMAN", [{"name": "action", "type": 0, "value": "go"}])
    sim.start_program()
    assert sim.is_running() is True
    sim.wait_for_program_to_finish()
    assert sim.is_running() is False
    assert sim.base_position() == "LABMAN"


def test_staged_fault_latches_error_until_acknowledged(tmp_path) -> None:
    message = "The Move action timed out after being blocked"
    sim = _sim(
        tmp_path,
        {"fail": [{"program": "base_BFT", "action": "go", "nth": 1, "message": message}]},
        base_position="Home",
        charging=False,
    )
    with pytest.raises(ValueError, match=message):
        sim.run_program("base_BFT", {"action": "go"})
    assert sim.is_error() is True
    # BasePosition is left where the failed program found it, like the cell.
    assert sim.base_position() == "Home"
    with pytest.raises(ValueError):
        sim.run_program("base_BFT", {"action": "go"})
    sim.acknowledge_error()
    assert sim.is_error() is False
    # nth=1 only: the second attempt succeeds.
    sim.run_program("base_BFT", {"action": "go"})
    assert sim.base_position() == "BFT"
    events = [e["event"] for e in _events(tmp_path)]
    assert "program_failed" in events
    assert events.count("program_end") == 1


def test_always_fault_and_narrowing_by_region(tmp_path) -> None:
    sim = _sim(
        tmp_path,
        {
            "fail": [
                {
                    "program": "robotarm_*",
                    "source_region": "LABMAN",
                    "nth": "always",
                    "message": "Failed to Calibrate Tag",
                }
            ]
        },
    )
    for _ in range(2):
        with pytest.raises(ValueError, match="Failed to Calibrate Tag"):
            sim.run_program(
                "robotarm_LABMAN",
                {"source_region": "LABMAN", "source_slot": "SubRackA", "destination_region": "ROBOT_BASE", "destination_slot": "SubRackA"},
            )
        sim.acknowledge_error()
    # Same program, other direction: not matched.
    sim.run_program(
        "robotarm_LABMAN",
        {"source_region": "ROBOT_BASE", "source_slot": "SubRackA", "destination_region": "LABMAN", "destination_slot": "SubRackA"},
    )


def test_hang_is_released_by_script(tmp_path) -> None:
    script_path = tmp_path / "script.json"
    sim = _sim(tmp_path, {"hang": [{"program": "robotarm_LABMAN", "nth": 1, "seconds": 600}]})
    sim.load_program("robotarm_LABMAN", [])
    sim.start_program()
    assert sim.is_running() is True
    _write_script(script_path, {"seconds_per_program": 0.0, "release_hang": True})
    sim.wait_for_program_to_finish()
    assert sim.is_running() is False


def test_battery_drains_per_program_and_can_be_pinned(tmp_path) -> None:
    sim = _sim(tmp_path, {"battery_drain_per_program": 5.0}, battery=50.0, base_position="Home", charging=False)
    sim.run_program("base_LABMAN", {"action": "go"})
    assert sim.get_battery_level() == pytest.approx(45.0)
    _write_script(tmp_path / "script.json", {"seconds_per_program": 0.0, "battery": 30.0})
    assert sim.get_battery_level() == pytest.approx(30.0)


def test_charge_drop_and_redock(tmp_path) -> None:
    sim = _sim(
        tmp_path,
        {"charge_drops": {"after_dock_s": 0.0, "times": 1}},
        base_position="Home",
        charging=False,
    )
    sim.run_program("base_Charging", {})
    assert sim.base_position() == "Charging"
    # The drop is applied on the next read, mirroring Ability's late teardown.
    assert sim.is_actually_charging() is False
    assert sim.settle_on_charge(settle_s=0.0, redock_attempts=1) is True
    assert sim.redocks == 1
    assert sim.is_actually_charging() is True


def test_redock_can_be_refused(tmp_path) -> None:
    sim = _sim(
        tmp_path,
        {"charge_drops": {"after_dock_s": 0.0, "times": 1}, "redock_succeeds": False},
        base_position="Home",
        charging=False,
    )
    sim.run_program("base_Charging", {})
    assert sim.settle_on_charge(settle_s=0.0, redock_attempts=1) is False


def test_main_program_path_moves_base(tmp_path) -> None:
    sim = _sim(tmp_path, base_position="Home", charging=False)
    sim.run_main_program("DASH", "None", "None", "None", "None")
    assert sim.base_position() == "DASH"
    sim.charge_no_waiting()
    assert sim.base_position() == "Charging"
    assert sim.is_actually_charging() is True


def test_manual_mode_handshake(tmp_path) -> None:
    sim = _sim(tmp_path)
    assert sim.is_manual_mode() is True
    sim.set_automatic_mode(True)
    assert sim.is_automatic_mode() is True
    assert sim.ensure_manual_mode() is True
    assert sim.is_manual_mode() is True
    assert sim.clear_error_with_auto_manual_handshake() is True
    assert sim.is_manual_mode() is True


def test_home_robot_arm(tmp_path) -> None:
    sim = _sim(tmp_path, robot_pose="Unknown")
    sim.home_robot_arm()
    assert sim.robot_pose() == "Home"
    assert sim.programs_run[-1][0] == "HomeRobotArm"

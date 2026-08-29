"""Main start must actually enter Executing, not return Idle as success."""

from unittest.mock import patch

import pytest

from alab_control.mobile_robot_arm.mobile_robot_arm import MRAState, MobileRobotArm


def _arm():
    arm = MobileRobotArm.__new__(MobileRobotArm)
    arm.ip = "192.168.1.207"
    arm.timeout = 10
    return arm


def test_wait_until_running_returns_when_executing():
    arm = _arm()
    arm.get_state_and_message = lambda: (MRAState.RUNNING, "")
    arm.wait_until_running(timeout=1)


def test_wait_until_running_raises_when_controller_stays_idle():
    arm = _arm()
    arm.get_state_and_message = lambda: (MRAState.IDLE, "")
    arm.get_current_program = lambda: {"name": "Main", "arguments": []}
    with patch(
        "alab_control.mobile_robot_arm.mobile_robot_arm.ability_cell_snapshot",
        return_value={"robot_pose": "Unknown", "base_position": "BFT", "rest_state": "Idle"},
    ), patch(
        "alab_control.mobile_robot_arm.mobile_robot_arm.format_cell_snapshot",
        return_value="REST='Idle' RobotPose='Unknown' BasePosition='BFT'",
    ):
        with pytest.raises(ValueError, match="did not move"):
            arm.wait_until_running(timeout=0.3)


def test_acknowledge_error_skips_when_already_idle():
    arm = _arm()
    arm.request_status = lambda: {"state": "Idle", "message": ""}
    with patch("alab_control.mobile_robot_arm.mobile_robot_arm.requests.put") as put:
        arm.acknowledge_error()
    put.assert_not_called()


def test_prepare_for_main_persists_charging_when_stale_station_on_dock():
    import math

    from alab_control.mobile_robot_mir250.clients import Pose

    arm = _arm()
    snap = {
        "rest_state": "Idle",
        "robot_pose": "Home",
        "base_position": "BFT",
        "program_name": "Main",
        "program_started_at": None,
        "ros_program_state": {},
    }
    charger = Pose(-4.3146, -2.1434, 0.0, math.radians(34.4), 0.0, 0.0)
    with patch(
        "alab_control.mobile_robot_arm.mobile_robot_arm.ability_cell_snapshot",
        return_value=snap,
    ), patch(
        "alab_control.mobile_robot_mir250.clients.AbilityClient"
    ) as ability_cls, patch(
        "alab_control.mobile_robot_mir250.clients.AbilityRosClient"
    ) as ros_cls:
        ability_cls.return_value.status.return_value = {"state": "Idle"}
        ability_cls.return_value.wait_until_loadable.return_value = "Idle"
        ability_cls.return_value.transform.return_value = charger
        ros = ros_cls.return_value
        ros.base_position.return_value = "Charging"
        out = arm._prepare_for_main("SRS")
        ros.edit_variable.assert_called_once_with("BasePosition", "Charging")
        assert out["base_position"] == "Charging"


def test_prepare_for_main_refuses_unknown_robot_pose():
    arm = _arm()
    snap = {
        "rest_state": "Idle",
        "robot_pose": "Unknown",
        "base_position": "BFT",
        "program_name": "Main",
        "program_started_at": None,
        "ros_program_state": {},
    }
    with patch(
        "alab_control.mobile_robot_arm.mobile_robot_arm.ability_cell_snapshot",
        return_value=snap,
    ), patch(
        "alab_control.mobile_robot_mir250.clients.AbilityClient"
    ) as ability_cls, patch(
        "alab_control.mobile_robot_mir250.clients.AbilityRosClient"
    ):
        ability_cls.return_value.status.return_value = {"state": "Idle"}
        ability_cls.return_value.wait_until_loadable.return_value = "Idle"
        with pytest.raises(ValueError, match="RobotPose is 'Unknown'"):
            arm._prepare_for_main("SRS")

import json
from multiprocessing.sharedctypes import Value
from pathlib import Path
import types
from typing import Callable, List, Dict, Literal, Optional, Union

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import numpy as np

from alab_control.robot_arm_ur5e import URRobotDashboard, URRobotSecondary
from alab_control.robot_arm_ur5e.ur_robot_ssh import URRobotSSH


class BaseURRobot:
    """
    Base class shared among different ur robot arms.
    """

    HEADER_FILE_NAME = "empty.script"

    def __init__(self, ip_address: str) -> None:
        self.ip_address = ip_address
        self.ssh = URRobotSSH(ip=ip_address)
        self.secondary = URRobotSecondary(ip=ip_address)
        self.dashboard = URRobotDashboard(ip=ip_address)

    def run_program(
        self,
        program: str,
        fmt: Optional[Literal["urp_path", "urscript", "urscript_path"]] = None,
        block: bool = True,
    ):
        """
        Run single program in the robot arm.

        Currently we support to submit program by:
            (1) specify the urp path in the robot arm's ``/programs`` folder (urp_path)
            (2) specify the urscript path in the robot arm's ``/programs`` folder (urscript_path)
            (3) submit a program string directly (urscript)

        Args:
            program: can be either a path of program or a urscript program
            fmt: the format of the program arg. If not specified, the function will
              imply the format based on the content of program.
            block: the function will wait until the program is finished.
        """
        if fmt is None:
            if program.endswith(".urp"):
                fmt = "urp_path"
            elif program.endswith(".script"):
                fmt = "urscript_path"
            elif program.startswith("def"):
                fmt = "urscript"
            else:
                raise ValueError(
                    "Cannot infer the format from the program string. "
                    "Please specifiy the fmt manually."
                )

        if fmt == "urp_path":
            self.dashboard.run_program(program, block=block)
        elif fmt == "urscript_path":
            program_content = self.ssh.read_program(
                program, header_file_name=self.HEADER_FILE_NAME
            )
            self.secondary.run_program(program_content, block=block)
        elif fmt == "urscript":
            self.secondary.run_program(program, block=block)
        else:
            raise ValueError(
                f"Unknown fmt value: {fmt}. "
                "Currently we support ['urp_path', 'urscript', 'urscript_path']."
            )

    def run_programs(self, programs: List[Union[str, Callable[[], None]]]):
        """
        Helper function to run multiple robot arm programs one by one. The program can also
        be a callable that controls other device to do other operations

        Args:
            programs: The programs can be (1) a program string that will be sent to the ``run_program``;
              (2) a callable that have not arguments, it will be called
        """
        # do something type check first
        for program in programs:
            if not isinstance(program, str) and not callable(program):
                raise ValueError(f"Expect str or a callable, but get {type(program)}")

        for program in programs:
            if isinstance(program, str):
                self.run_program(program=program, block=True)
            else:
                program()

    def set_speed(self, speed: float):
        """
        Set the speed of robot arm running, should be a value between 0 and 1.
        """
        self.secondary.set_speed(speed)

    def is_running(self) -> bool:
        """
        Check if there is any program running in the robot arm
        """
        return self.dashboard.is_running()

    def is_remote_mode(self) -> bool:
        """
        Check if the robot arm is put in remote mode.
        """
        return self.dashboard.is_remote_mode()

    def movej(
        self,
        joints: Union[List[float], np.ndarray],
        acc: float = 0.1,
        vel: float = 0.05,
        wait: bool = True,
        relative: bool = False,
        threshold: bool = None,
    ):
        """
        Movej function
        """
        self.secondary.movej(
            joints, acc=acc, vel=vel, wait=wait, relative=relative, threshold=threshold
        )

    def check_joints(self, target_joints: Union[List[float], np.ndarray]):
        return self.secondary.check_joints(target_joints=target_joints)

    def close(self):
        """
        Close all the connections to the robot arm
        """
        self.ssh.close()
        self.secondary.close()
        self.dashboard.close()


class Dummy:
    """
    The UR5e in the synthesis station
    """

    racks_positions = {
        "inside_furnace_b": "BF_B",
        "inside_furnace_c": "BF_C",
        "loading_rack": "BFRACK_L",
        "rack_c": "BFRACK_C",
        "rack_d": "BFRACK_D",
    }

    def __init__(self, ip):
        self.robot_type = "hande_ur5e"
        self._dashboard_client = URRobotDashboard(
            ip
        )  # dashboard client is used for reading status from the robot arm
        # secondary client is used for sending the programs to the robot arm
        self._secondary_client = URRobotSecondary(ip)
        self._ssh_client = URRobotSSH(
            ip
        )  # ssh client is used for reading programs from the robot arm
        self.waypoints = json.load(
            (Path(__file__).parent / "waypoints" / "dummy.json").open(encoding="utf-8")
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader((Path(__file__).parent / "templates").as_posix()),
            extensions=["jinja2_workarounds.MultiLineInclude"],
            undefined=StrictUndefined,
        )

    def is_running(self):
        return self._dashboard_client.is_running()

    def check_status(self):
        """
        Check if the robot arm is ready to run programs
        """
        if not self._secondary_client.check_home():
            raise ValueError("Robot arm is not in home position")
        if not self._dashboard_client.is_remote_mode():
            raise ValueError("Robot arm is not in remote mode")

    def move_rack(self, start: str, end: str):
        self.check_status()
        if start not in self.racks_positions.keys():
            raise ValueError(f"{start} is not a valid rack position")
        if end not in self.racks_positions.keys():
            raise ValueError(f"{end} is not a valid rack position")

        self._secondary_client.set_speed(0.4)
        self._secondary_client.run_program(
            self._ssh_client.read_program("Pick_Handle.script"), block=True
        )
        self._secondary_client.run_program(
            self._ssh_client.read_program(f"Pick_{self.racks_positions[start]}.script"),
            block=True,
        )
        self._secondary_client.run_program(
            self._ssh_client.read_program(f"Place_{self.racks_positions[end]}.script"),
            block=True,
        )
        self._secondary_client.run_program(
            self._ssh_client.read_program("Place_Handle.script"), block=True
        )
        self._secondary_client.run_program(
            self._ssh_client.read_program("Home.script"), block=True
        )

    def _home_trans(self, waypoint_doc: Dict, go_home: bool):
        home_trans_config = {
            "go_home": go_home,
            "robot_type": self.robot_type,
            "home_mid_poses": [pos["pose"] for pos in waypoint_doc["home_trans"]],
            "home_mid_qnears": [pos["joint"] for pos in waypoint_doc["home_trans"]],
            "start_pose": waypoint_doc["initial_position"]["pose"],
            "start_qnear": waypoint_doc["initial_position"]["joint"],
        }

        home_trans_template = self.jinja_env.get_template("home_trans.script")
        script = home_trans_template.render(**home_trans_config)
        self._secondary_client.run_program(script, block=True)

    def _pick_place(self, start: str, end: str, waypoint_doc: Dict):
        start_positions = {
            pos["name"]: {"pose": pos["pose"], "joint": pos["joint"]}
            for pos in waypoint_doc["start_positions"]
        }

        end_positions = {
            pos["name"]: {"pose": pos["pose"], "joint": pos["joint"]}
            for pos in waypoint_doc["end_positions"]
        }
        pick_place_config = {
            "robot_type": self.robot_type,
            "approach_distance_mm": waypoint_doc["approach_distance_mm"],
            "start_pose": waypoint_doc["initial_position"]["pose"],
            "start_qnear": waypoint_doc["initial_position"]["joint"],
            "pick_pose": start_positions[start]["pose"],
            "pick_qnear": start_positions[start]["joint"],
            "trans_poses": [
                pos["pose"] for pos in waypoint_doc["transition_waypoints"]
            ],
            "trans_qnears": [
                pos["joint"] for pos in waypoint_doc["transition_waypoints"]
            ],
            "place_pose": end_positions[end]["pose"],
            "place_qnear": end_positions[end]["joint"],
        }

        pick_place_template = self.jinja_env.get_template("pick_place.script")
        script = pick_place_template.render(**pick_place_config)
        self._secondary_client.run_program(script, block=True)

    def move_crucibles(self, starts: List[str], ends: List[str]):
        self.check_status()
        if len(starts) != len(ends):
            raise ValueError("The number of starts and ends must be the same")
        if len(set(starts)) != len(starts):
            raise ValueError("There are duplicate starts")
        if len(set(ends)) != len(ends):
            raise ValueError("There are duplicate ends")

        if not starts or not ends:
            return
        self._secondary_client.set_speed(0.8)

        waypoint_to_use = None

        for waypoint in self.waypoints:
            if set(pos["name"] for pos in waypoint["start_positions"]).issuperset(
                set(starts)
            ) and set(pos["name"] for pos in waypoint["end_positions"]).issuperset(
                set(ends)
            ):
                waypoint_to_use = waypoint
                break

        if waypoint_to_use is None:
            raise ValueError(f"No waypoint found from {starts} to {ends}")

        self._home_trans(waypoint_doc=waypoint_to_use, go_home=False)
        for start, end in zip(starts, ends):
            self._pick_place(start=start, end=end, waypoint_doc=waypoint_to_use)
        self._home_trans(waypoint_doc=waypoint_to_use, go_home=True)

    def close(self):
        self._dashboard_client.close()
        self._secondary_client.close()
        self._ssh_client.close()


class FurnaceDummy(BaseURRobot):
    pass


class CharDummy(BaseURRobot):
    pass


if __name__ == "__main__":
    robot = Dummy("192.168.0.22")
    try:
        robot.move_crucibles(
            ["loading_rack/1", "loading_rack/8"],
            ["transfer_rack/1", "transfer_rack/16"],
        )
    finally:
        robot.close()

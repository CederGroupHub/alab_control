import json
from pathlib import Path
from typing import List, Dict

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from robot_arm_ur5e import URRobotDashboard, URRobotSecondary
from robot_arm_ur5e.ur_robot_ssh import URRobotSSH


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
        self._dashboard_client = URRobotDashboard(ip)  # dashboard client is used for reading status from the robot arm
        # secondary client is used for sending the programs to the robot arm
        self._secondary_client = URRobotSecondary(ip)
        self._ssh_client = URRobotSSH(ip)  # ssh client is used for reading programs from the robot arm
        self.waypoints = json.load((Path(__file__).parent / "waypoints" / "dummy.json").open(encoding="utf-8"))
        self.jinja_env = Environment(loader=FileSystemLoader((Path(__file__).parent / "templates").as_posix()),
                                     extensions=["jinja2_workarounds.MultiLineInclude"], undefined=StrictUndefined)

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
            self._ssh_client.read_program("Pick_Handle.script"),
            block=True
        )
        self._secondary_client.run_program(
            self._ssh_client.read_program(f"Pick_{self.racks_positions[start]}.script"),
            block=True
        )
        self._secondary_client.run_program(
            self._ssh_client.read_program(f"Place_{self.racks_positions[end]}.script"),
            block=True
        )
        self._secondary_client.run_program(
            self._ssh_client.read_program("Place_Handle.script"),
            block=True
        )
        self._secondary_client.run_program(
            self._ssh_client.read_program("home.script"),
            block=True
        )

    def _home_trans(self, waypoint_doc: Dict, go_home: bool):
        home_trans_config = {
            "go_home": go_home,
            "robot_type": self.robot_type,
            "home_mid_poses": [pos["pose"] for pos in waypoint_doc["home_trans"]],
            "home_mid_qnears": [pos["joint"] for pos in waypoint_doc["home_trans"]],
            "start_pose": waypoint_doc["initial_position"]["pose"],
            "start_qnear": waypoint_doc["initial_position"]["joint"]
        }

        home_trans_template = self.jinja_env.get_template("home_trans.script")
        script = home_trans_template.render(**home_trans_config)
        self._secondary_client.run_program(script, block=True)

    def _pick_place(self, start: str, end: str, waypoint_doc: Dict):
        start_positions = {pos["name"]: {"pose": pos["pose"], "joint": pos["joint"]}
                           for pos in waypoint_doc["start_positions"]}

        end_positions = {pos["name"]: {"pose": pos["pose"], "joint": pos["joint"]}
                         for pos in waypoint_doc["end_positions"]}
        pick_place_config = {
            "robot_type": self.robot_type,
            "approach_distance_mm": waypoint_doc["approach_distance_mm"],
            "start_pose": waypoint_doc["initial_position"]["pose"],
            "start_qnear": waypoint_doc["initial_position"]["joint"],
            "pick_pose": start_positions[start]["pose"],
            "pick_qnear": start_positions[start]["joint"],
            "trans_poses": [pos["pose"] for pos in waypoint_doc["transition_waypoints"]],
            "trans_qnears": [pos["joint"] for pos in waypoint_doc["transition_waypoints"]],
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
        self._secondary_client.set_speed(.8)

        waypoint_to_use = None

        for waypoint in self.waypoints:
            if set(pos["name"] for pos in waypoint["start_positions"]).issuperset(set(starts)) and \
                    set(pos["name"] for pos in waypoint["end_positions"]).issuperset(set(ends)):
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


if __name__ == '__main__':
    robot = Dummy("192.168.0.22")
    try:
        robot.move_crucibles(["loading_rack/1", "loading_rack/8"], ["transfer_rack/1", "transfer_rack/16"])
    finally:
        robot.close()

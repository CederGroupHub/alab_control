from typing import List

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

    def move_crucibles(self, starts: List[str], ends: List[str]):
        self.check_status()
        self._secondary_client.set_speed(1.)
        # TODO: implement this

    def close(self):
        self._dashboard_client.close()
        self._secondary_client.close()
        self._ssh_client.close()


if __name__ == '__main__':
    robot = Dummy("192.168.0.22")
    try:
        robot.move_rack("loading_rack", "loading_rack")
    finally:
        robot.close()

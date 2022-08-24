import time
from typing import Optional, List

import numpy as np
from _socket import timeout
from urx import URRobot
from urx.ursecmon import TimeoutException


class URRobotSecondary:
    robot_type: Optional[str] = None

    def __init__(self, ip: str):
        self.ip = ip
        self._robot: Optional[URRobot] = None
        self.setup_connection()

    def setup_connection(self):
        for i in range(10):
            try:
                time.sleep(0.1)
                self._robot = URRobot(host=self.ip)
            except (TimeoutException, timeout):
                print(f"Failed to connect to {self.ip}, retrying... {i+1}/10")
                continue
            else:
                break
        else:
            raise TimeoutError("Could not connect to robot arm")

    def run_program(self, program: str, block: bool = False):
        """
        Send a program to the robot arm. The program is a string that contains
        an urscript.

        Args:
            program: the urscript string
            block: default to False. When set to True, this method will not return
              util the program is finished.
        """
        if self.is_running():
            raise ValueError("Robot arm is still running")
        self._robot.secmon.send_program(program)
        time.sleep(0.5)  # make sure the robot arm receives and start to run the program
        if block:
            self.wait_for_finish()

    def is_running(self) -> bool:
        """
        Return if there is a program running in the robot arm
        """
        return self._robot.is_program_running()

    def wait_for_finish(self):
        """
        Block the process until finishing
        """
        while self.is_running():
            continue
        return

    def set_speed(self, speed: float):
        """
        Set the speed of the robot arm. The speed is a float between 0 and 1.
        """
        if speed < 0 or speed > 1:
            raise ValueError("Speed must be between 0 and 1")

        self.run_program(
            f"""def set_speed():
            socket_open("127.0.0.1", 30003)
            socket_send_string("set speed")
            socket_send_string({speed})
            socket_send_byte(10)
            socket_close()
end""",
            block=True,
        )

    def close(self):
        """
        Close the connection to the robot arm
        """
        if self._robot is not None:
            self._robot.close()

    def stop(self):
        """
        Stop the program running in the robot arm
        """
        self._robot.stop()

    def check_home(self):
        """
        Check if the robot arm is in home position
        """
        current_joint = self._robot.getj()
        return np.allclose(
            current_joint, [0, -np.pi / 2, 0, -np.pi / 2, 0, 0], atol=1e-4
        )

    def __exit__(self):
        self.close()


if __name__ == "__main__":
    robot = URRobotSecondary("192.168.0.22")
    print(robot.check_home())
    robot.close()

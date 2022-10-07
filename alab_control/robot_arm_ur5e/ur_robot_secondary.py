import time
from typing import List, Union

import numpy as np
from _socket import timeout
from urx import URRobot
from urx.ursecmon import TimeoutException


class URRobotSecondary:
    def __init__(self, ip: str):
        self.ip = ip
        try:
            self._robot: URRobot = URRobot(host=self.ip)
        except (TimeoutException, timeout) as exc:
            raise Exception("Something wrong with the UR Robot secondary port. Try again later.") from exc
    
    def movej(
            self,
            joints: Union[List[float], np.ndarray], 
            acc: float = 0.1, 
            vel: float = 0.05, 
            wait: bool = True, 
            relative: bool = False,
            threshold: bool = None
    ):
        self._robot.movej(joints, acc=acc, vel=vel, wait=wait, relative=relative, threshold=threshold)

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
        self._robot.close()

    def stop(self):
        """
        Stop the program running in the robot arm
        """
        self._robot.stop()

    def check_home(self) -> bool:
        """
        Check if the robot arm is in home position
        """
        return self.check_joint([0, -np.pi / 2, 0, -np.pi / 2, 0, 0])

    def check_joints(self, target_joints: Union[np.ndarray, List[float]]) -> bool:
        """ 
        Check if the robot arm is in the given position

        Args:
            target_joints: a 6-element array with the angle of each joint.
        """
        if len(target_joints) != 6:
            raise ValueError("The target_joint should have 6 elements.")
        current_joints = self._robot.getj()
        return np.allclose(
            current_joints, target_joints, atol=1e-2
        )


if __name__ == "__main__":
    robot = URRobotSecondary("192.168.0.22")
    print(robot.check_home())
    robot.close()

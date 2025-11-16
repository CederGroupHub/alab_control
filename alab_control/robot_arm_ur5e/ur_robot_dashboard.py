"""
Provide simple api to load and execute a program via socket interface in
Universal Robot e-Series
"""

import logging
import socket
import time
from enum import auto, Enum, unique
from threading import Lock
from typing import Optional

from alab_control.robot_arm_ur5e.program_list import PREDEFINED_PROGRAM
from alab_control.robot_arm_ur5e.ur_robot_primary import URRobotPrimary

logger = logging.getLogger(__name__)


@unique
class ProgramStatus(Enum):
    """
    Status of program
    """

    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


@unique
class SafeStatus(Enum):
    NORMAL = auto()
    REDUCED = auto()
    PROTECTIVE_STOP = auto()
    RECOVERY = auto()
    SAFEGUARD_STOP = auto()
    SYSTEM_EMERGENCY_STOP = auto()
    ROBOT_EMERGENCY_STOP = auto()
    VIOLATION = auto()
    FAULT = auto()
    AUTOMATIC_MODE_SAFEGUARD_STOP = auto()
    SYSTEM_THREE_POSITION_ENABLING_STOP = auto()


@unique
class RobotMode(Enum):
    NO_CONTROLLER = auto()
    DISCONNECTED = auto()
    CONFIRM_SAFETY = auto()
    BOOTING = auto()
    POWER_OFF = auto()
    POWER_ON = auto()
    IDLE = auto()
    BACKDRIVE = auto()
    RUNNING = auto()


class URRobotError(Exception):
    """
    Used when URRobot encounter an Exception
    """


class URRobotPopupError(URRobotError):
    """
    Used when URRobot encounter an popup
    """


class URRobotDashboard:
    """
    Refer to https://s3-eu-west-1.amazonaws.com/ur-support-site/42728/DashboardServer_e-Series.pdf
    for commands' instructions
    """

    def __init__(self, ip: str, timeout: float = 5):
        """
        The dashboard interface to UR Robot
        It will also initialize a primary interface to monitor the popup in the robot arm.

        Args:
            ip: the ip address to the UR Robot
            port: port of socket
            timeout: timeout time in sec
        """
        # set up socket connection
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(timeout)
        self._socket.connect((ip, 29999))
        time.sleep(0.1)
        self._socket.recv(2048)

        self._mutex_lock = Lock()

        self._primary = URRobotPrimary(ip, timeout)

    def close(self):
        self._socket.close()

    def send_cmd(self, cmd: str) -> str:
        """
        Threading-safe socket communication function,
        which will send string command to the robot
        dashboard server.
        """
        cmd = cmd.strip("\n") + "\n"
        self._mutex_lock.acquire()

        try:
            self._socket.sendall(cmd.encode())
            logger.debug("Send command: {}".format(cmd))
            response = ""
            retries = 0
            while not response and retries < 20:
                retries += 1
                time.sleep(0.1)
                block = self._socket.recv(2048).decode(encoding="utf-8")
                response += block
                if response and not block:
                    break
            if retries >= 20:
                raise URRobotError("Maximum retries reached, but still no response.")
            logger.debug("Receive response: {}".format(response))
        finally:
            time.sleep(0.1)
            self._mutex_lock.release()

        return response

    def run_program(self, name: str, block: bool = True, timeout: Optional[int] = 600,
                    stop_program_on_timeout: bool = False):
        """
        Run a program

        Args:
            name: the path of program file (*.urp) in the ur dashboard or
                predefined name in the PREDEFINED_PROGRAM
            block: whether to wait and return until the program is finished.
        """
        if timeout is not None:
            timeout_seconds = timeout
        else:
            timeout_seconds = 999999  # effectively no timeout
        if self.is_running():
            raise URRobotError("There is still a program running!")
        self.load(name)
        # TODO: DELETE THIS LATER AND FIND BETTER SOLUTION!! wait for three seconds to make sure the program is loaded
        # TODO: USE get loaded program to check if the correct program is loaded - test whether this exactly works after the loading is done or during loading.
        # CANNOT BE USED UF ITS ONLY DURING LOADING
        time.sleep(3)
        logger.info("Run program: {}".format(name))
        with self._primary.monitor_popup():
            self.play()
            try:
                self.wait_for_start(timeout=30)
            except TimeoutError:
                pass  # the program may end very quickly
            if block:
                try:
                    self.wait_for_finish(
                        timeout=timeout_seconds
                    )  # set the maximum wait time for program finish
                except URRobotPopupError:
                    raise
                except Exception as e:
                    if stop_program_on_timeout:
                        self.stop()
                    raise URRobotError(
                        f"Error when waiting for program to finish: {name}. Protective/Emergency stop might have occured. If so, please jog the robot arm safely to reset and try again. {e.args[0]}"
                    ) from e

    def is_running(self) -> bool:
        """
        Return if there is a program running in the robot arm
        """
        response = self.send_cmd("running")
        if "true" in response:
            return True
        elif "false" in response:
            return False
        else:
            raise URRobotError(
                "Unexpected response for is_running query: {}".format(response)
            )

    def wait_for_start(self, timeout: Optional[float] = None):
        """
        Block the process until starting
        """
        if self.get_robot_mode() not in (RobotMode.RUNNING, RobotMode.IDLE):
            raise URRobotError(
                "Robot is not in running mode, but in {}.".format(
                    self.get_robot_mode().name
                )
            )
        if self.get_safety_status() != SafeStatus.NORMAL:
            raise URRobotError(
                "Robot is not in normal mode, but in {}.".format(
                    self.get_safety_status().name
                )
            )

        start_time = time.time()
        while not self.is_running():
            if timeout and time.time() - start_time > timeout:
                raise TimeoutError(
                    "Timeout when waiting for program start, the limit is {} s. ".format(
                        timeout
                    )
                )

    def wait_for_finish(self, timeout: Optional[float] = None):
        """
        Block the process until finishing
        """
        start_time = time.time()
        while self.is_running():
            if timeout and time.time() - start_time > timeout:
                raise TimeoutError(
                    "Timeout when waiting for program finish, the limit is {} s".format(
                        timeout
                    )
                )
            if self._primary.popup_message is not None:
                raise URRobotPopupError(
                    f"A popup is shown on robot arm: "
                    f"{self._primary.popup_title} - {self._primary.popup_message}"
                )

        if self.get_robot_mode() not in (RobotMode.RUNNING, RobotMode.IDLE):
            raise URRobotError(
                "Robot is not in running mode, but in {}.".format(
                    self.get_robot_mode().name
                )
            )
        if self.get_safety_status() != SafeStatus.NORMAL:
            raise URRobotError(
                "Robot is not in normal mode, but in {}.".format(
                    self.get_safety_status().name
                )
            )

    def load(self, name: str):
        """
        Load program with `name`

        Args:
            name: the path of program file (*.urp) in the ur dashboard or
                predefined name in the PREDEFINED_PROGRAM
        """
        if not self.is_remote_mode():
            raise URRobotError("The robot arm should be in remote mode.")
        program_path = PREDEFINED_PROGRAM.get(name, name)
        response = self.send_cmd("load {}".format(program_path))
        try:
            self._raise_for_unexpected_prefix(response, "Loading program")
        except URRobotError as e:
            if response.endswith(".urp"):
                e.args = (
                    e.args[0] + " Your file seems not to be a valid "
                    "program name, did you define it in "
                    "the predefined program dict?",
                )
            raise

    def play(self):
        """
        Play loaded program
        """
        if not self.is_remote_mode():
            raise URRobotError("The robot arm should be in remote mode.")
        response = self.send_cmd("play")
        try:
            self._raise_for_unexpected_prefix(response, "Starting program")
        except URRobotError as e:
            # add more hints for debug
            e.args = (
                e.args[0] + " Did you remember to load program or did "
                "you stop the program by accident or is the robot"
                "arm in the right start position?",
            )
            raise

    def stop(self):
        """
        Terminate the program, which cannot be started again

        If there is no program running (STOPPED), it will return directly
        """
        if self.get_program_status() == ProgramStatus.STOPPED:
            return
        response = self.send_cmd("stop")
        self._raise_for_unexpected_prefix(response, "Stopped")

    def pause(self):
        """
        Temporarily pause the program

        If there is no program running, it will return directly
        """
        if not self.is_running():
            return
        response = self.send_cmd("pause")
        self._raise_for_unexpected_prefix(response, "Pausing program")

    def continue_play(self):
        """
        Same functionality as play(), but it will check
        if the program is recovered from a paused state

        If not recovered from pause state, it will raise
        an URRobotError
        """
        if self.get_program_status() != ProgramStatus.PAUSED:
            raise URRobotError(
                "continue_play can only be used to recover a paused program"
            )
        self.play()

    def get_robot_mode(self) -> RobotMode:
        """
        Get the current robot mode
        """
        response = self.send_cmd("robotmode")
        robot_mode_string = response.split(" ")[1].strip("\n")

        try:
            return RobotMode[robot_mode_string]
        except KeyError as e:
            raise URRobotError(
                "Unexpected response for robot mode: {}.".format(robot_mode_string)
            ) from e

    def get_program_status(self) -> ProgramStatus:
        """
        Get current program's status

        Returns:
            Choice of [STOPPED, PLAYING, PAUSED]
        """
        response = self.send_cmd("programState")
        state_string = response.split(" ")[0]
        try:
            return ProgramStatus[state_string]
        except KeyError as e:
            raise URRobotError(
                "Get unexpected program status query result: {}".format(response)
            ) from e

    @property
    def loaded_program(self) -> Optional[str]:
        """
        Get the path of currently loaded program
        """
        response = self.send_cmd("get loaded program")
        if response.startswith("No program loaded"):
            return None
        elif response.endswith(".urp") or response.endswith(".urscript"):
            return response
        raise URRobotError(
            "Unexpected result for loaded_program query: {}".format(response)
        )

    def is_remote_mode(self) -> bool:
        """
        Check if the machine is in remote mode
        """
        response = self.send_cmd("is in remote control").strip("\n ")
        if response == "true":
            return True
        elif response == "false":
            return False
        else:
            raise URRobotError(
                "Unexpected result for is_remote_mode query: {}".format(response)
            )

    def clear_popup(self):
        """
        Clear popup message

        If there is no popup message, it will still return but do nothing
        """
        response = self.send_cmd("close popup")
        self._raise_for_unexpected_prefix(response, "closing popup")

    def get_safety_status(self) -> SafeStatus:
        """
        Get current safety status
        Returns:
            Choice of [NORMAL, REDUCED, PROTECTIVE_STOP, RECOVERY, SAFEGUARD_STOP,
                SYSTEM_EMERGENCY_STOP, ROBOT_EMERGENCY_STOP, VIOLATION, FAULT,
                AUTOMATIC_MODE_SAFEGUARD_STOP, SYSTEM_THREE_POSITION_ENABLING_STOP]
        """
        response = self.send_cmd("safetystatus")
        try:
            return SafeStatus[response.split(": ")[1].strip("\n")]
        except KeyError:
            raise URRobotError(
                "Unexpected response for safety status query: {}".format(response)
            )

    def get_variable(self, name: str):
        """
        Get the value of a variable in the robot arm

        Args:
            name: the name of the variable
        """
        response = self.send_cmd("getVariable {}".format(name))
        print(response)
        return response.split(": ")[1].strip("\n")

    @staticmethod
    def _raise_for_unexpected_prefix(response: str, prefix: str):
        """
        Convenience wrapper to raise an URRotError when receiving an unexpected error

        Args:
            response: The actual response string
            prefix: The expected string's prefix (should start with ...)
        """
        if not response.startswith(prefix):
            raise URRobotError(response)


if __name__ == "__main__":
    ur = URRobotDashboard("192.168.0.23")
    ur.run_program("test_popup.urp")

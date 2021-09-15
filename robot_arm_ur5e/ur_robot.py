"""
Provide simple api to load and execute a program via socket interface in
Universal Robot e-Series
"""


import logging
import socket
import time
from threading import Lock, Timer
from typing import Optional

from .program_list import PREDEFINED_PROGRAM

logger = logging.getLogger(__name__)


class URRobotError(Exception):
    pass


class URRobot:
    """
    Refer to https://s3-eu-west-1.amazonaws.com/ur-support-site/42728/DashboardServer_e-Series.pdf
    for commands' instructions
    """
    def __init__(self, ip: str, port: int = 29999, timeout: float = 2):
        """
        Args:
            ip: the ip address to the UR Robot
            port: port of socket
            timeout: timeout time in sec
        """
        # set up socket connection
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(timeout)
        self._socket.connect((ip, port))

        self._mutex_lock = Lock()

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
            if retries == 20:
                raise URRobotError("Maximum retries reached, but still no response.")
            logger.debug("Receive response: {}".format(response))
        finally:
            Timer(0.1, self._mutex_lock.release).start()

        return response

    def run(self, name: str, return_before_finished: bool = True):
        """
        Run a program

        Args:
            name: the path of program file (*.urp) in the ur dashboard or
                predefined name in the PREDEFINED_PROGRAM
            return_before_finished: if set to False, the function will not
                return until current program ends.
        """
        self.wait_for_finish()
        program_path = PREDEFINED_PROGRAM.get(name, name)
        self.load(program_path)
        self.play()
        logger.info("Run program: {}".format(program_path))

        if not return_before_finished:
            self.wait_for_finish()

    def is_running(self) -> bool:
        """
        Return if there is a program running in the robot arm
        """
        response = self.send_cmd("running")
        return "true" in response

    def wait_for_finish(self):
        while self.is_running():
            continue
        return

    def load(self, program_path: str):
        """
        Load program in specific `program_path`
        """
        response = self.send_cmd("load {}".format(program_path))
        self._raise_for_unexpected_prefix(response, "Loading program")

    def play(self):
        """
        Play loaded program
        """
        response = self.send_cmd("play")
        self._raise_for_unexpected_prefix(response, "Starting program")

    def stop(self):
        """
        Terminate the program, which cannot be started again

        If there is no program running, it will return directly
        """
        if not self.is_running():
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

    def pause_for_secs(self, secs: float):
        self.pause()
        time.sleep(secs=secs)
        self.play()

    def continue_play(self):
        """
        Same functionality as play(), but it will check
        if the program is recovered from a paused state

        If not recovered from pause state, it will raise
        an URRobotError
        """
        if self.get_current_mode() != "PAUSED":
            raise URRobotError("continue_play can only be used to recover a paused program")
        self.play()

    def get_current_mode(self) -> str:
        """
        Get current program's status

        Returns:
            Choice of [STOPPED, PLAYING, PAUSED]
        """
        return self.send_cmd("robotmode")

    @property
    def loaded_program(self) -> Optional[str]:
        """
        Get the path of currently loaded program
        """
        response = self.send_cmd("get loaded program")
        return response if "No program loaded" not in response else None

    def is_remote_mode(self) -> bool:
        """
        Check if the machine is in remote mode
        """
        return bool(self.send_cmd("is in remote control").capitalize())

    def get_safety_status(self):
        """
        Get current safety status
        Returns:
            Choice of [NORMAL, REDUCED, PROTECTIVE_STOP, RECOVERY, SAFEGUARD_STOP,
                SYSTEM_EMERGENCY_STOP, ROBOT_EMERGENCY_STOP, VIOLATION, FAULT,
                AUTOMATIC_MODE_SAFEGUARD_STOP, SYSTEM_THREE_POSITION_ENABLING_STOP]
        """
        return self.send_cmd("safetystatus")

    @staticmethod
    def _raise_for_unexpected_prefix(response: str, prefix: str):
        if not response.startswith(prefix):
            raise URRobotError(response)

from abc import ABC, abstractmethod
from typing import List
import serial
import time
import re
import numpy as np
from functools import partial


class RobotXYZ(ABC):
    #### Required Attributes #####
    POLLINGDELAY = 0.001  # the delay (in seconds) between sending a message and polling for a reply
    TIMEOUT = 5  # the timeout (in seconds) for waiting for a reply
    POSITIONTOLERANCE = 0.1  # the tolerance (in mm) between the target and actual position. Positions which are close within this value will be considered equal.
    ZHOP_HEIGHT = 5  # the height (in mm) to raise the z-axis between lateral movements. This is to avoid collisions.
    XLIM = 200  # the limit (in mm) of the x-axis
    YLIM = 235  # the limit (in mm) of the y-axis
    ZLIM = 150  # the limit (in mm) of the z-axis
    MAX_XY_FEEDRATE = 10000  # the maximum feedrate (in mm/min) of the x and y axes
    MAX_Z_FEEDRATE = (
        25 * 60
    )  # the maximum feedrate (in mm/min) of the z axis. Unless specified, we assume this is equal to the MAX_XY_FEEDRATE.

    ##### Class methods #####
    def __init__(self, port: str = None):
        """Connects to the robot. Note that you may need to home the robot after connecting before you can move!

        Args:
            port (str): The port to connect to the robot.
        """
        # communication variables
        self.port = port
        self.position = [
            None,
            None,
            None,
        ]  # start at None's to indicate stage has not been homed.
        self.__targetposition = [None, None, None]
        self.connect()  # connect by default

    @property
    def speed(self) -> float:
        """The speed (as a fraction of the maximum speed, 0-1) of the robot.

        Returns:
            float: Fraction (0-1) of the maximum speed.
        """
        return self._speed_fraction

    @speed.setter
    def speed(self, speed: float):
        """Sets the speed of the robot.

        Args:
            speed (float): Fraction (0-1) of the maximum speed.

        Raises:
            ValueError: If the speed is not between 0 and 1.
        """
        if (speed <= 0) or (speed > 1):
            raise ValueError(
                f"Speed must be between 0 and 1 (fraction of the maximum speed, which is {self.MAX_XY_FEEDRATE} mm/min)."
            )
        self._speed_fraction = speed
        # self.write(f"M220 F{int(speed*100)}")
        self.write(f"G0 F{self.speed_mm_per_min}")

    @property
    def speed_mm_per_min(self) -> float:
        """The speed (in mm/min) of the robot."""
        return round(self.speed * self.MAX_XY_FEEDRATE, 3)

    @speed_mm_per_min.setter
    def speed_mm_per_min(self, speed: float):
        """Sets the speed of the robot in mm/min.

        Args:
            speed (float): The speed (in mm/min) of the robot.

        Raises:
            ValueError: If the speed is not between 0 and the maximum speed.
        """
        if (speed <= 0) or (speed > self.MAX_XY_FEEDRATE):
            raise ValueError(
                f"Speed must be between 0 and {self.MAX_XY_FEEDRATE} mm/min."
            )
        self.speed = speed / self.MAX_XY_FEEDRATE

    @property
    def has_been_homed(self):
        return self.position != [None, None, None]
    # communication methods
    def connect(self):
        self._handle = serial.Serial(port=self.port, timeout=1, baudrate=115200)
        self.update()
        # self.update_gripper()
        if self.position == [
            self.XLIM,
            self.YLIM,
            self.ZLIM,
        ]:  # this is what it shows when initially turned on, but not homed
            self.position = [
                None,
                None,
                None,
            ]  # start at None's to indicate stage has not been homed.

        self._set_defaults()
        print("Connected!")

    def disconnect(self):
        self._handle.close()
        del self._handle

    def _set_defaults(self):
        self.write(
            f"M203 X{round(self.MAX_XY_FEEDRATE/60, 2)} Y{round(self.MAX_XY_FEEDRATE/60, 2)} Z{round(self.MAX_Z_FEEDRATE/60, 2)}"
        )
        self.speed = 0.8  # set the default speed to 80% of the maximum speed

    def write(self, msg):
        self._handle.write(f"{msg}\n".encode())
        time.sleep(self.POLLINGDELAY)
        output = []
        while self._handle.in_waiting:
            line = self._handle.readline().decode("utf-8").strip()
            if line != "ok":
                output.append(line)
            time.sleep(self.POLLINGDELAY)
        return output

    def _enable_steppers(self):
        self.write("M17")

    def _disable_steppers(self):
        self.write("M18")

    def update(self):
        found_coordinates = False
        while not found_coordinates:
            output = self.write("M114")  # get current position
            for line in output:
                if line.startswith("X:"):
                    x = float(re.findall(r"X:(\S*)", line)[0])
                    y = float(re.findall(r"Y:(\S*)", line)[0])
                    z = float(re.findall(r"Z:(\S*)", line)[0])
                    found_coordinates = True
                    break
        self.position = [x, y, z]

    # gantry methods
    def gohome(self):
        self.write("G28 X Y Z")
        self.update()

    def premove(self, x, y, z):
        """
        checks to confirm that all target positions are valid
        """
        if self.position == [None, None, None]:
            raise Exception(
                "Stage has not been homed! Home with self.gohome() before moving please."
            )
        if x is None:
            x = self.position[0]
        if y is None:
            y = self.position[1]
        if z is None:
            z = self.position[2]

        # check if this is a valid coordinate
        if not (0 <= x <= self.XLIM):
            raise ValueError(f"X coordinate {x} is out of range {self.XLIM}.")
        if not (0 <= y <= self.YLIM):
            raise ValueError(f"Y coordinate {y} is out of range {self.YLIM}.")
        if not (0 <= z <= self.ZLIM):
            raise ValueError(f"Z coordinate {z} is out of range {self.ZLIM}.")
        return x, y, z

    def moveto(self, x=None, y=None, z=None, zhop=False):
        """
        moves to target position in x,y,z (mm)
        """
        x, y, z = self.premove(x, y, z)  # will error out if invalid move
        if (x == self.position[0]) and (y == self.position[1]):
            zhop = False  # no use zhopping for no lateral movement

        if zhop:
            z_ceiling = max(self.position[2], z) + self.ZHOP_HEIGHT
            z_ceiling = min(
                z_ceiling, self.ZLIM
            )  # cant z-hop above build volume. mostly here for first move after homing.
            x0, y0, z0 = self.position
            self._movecommand(x0, y0, z_ceiling)
            self._waitformovement()
            self._movecommand(x, y, z_ceiling)
            self._waitformovement()
            self._movecommand(x, y, z)
            self._waitformovement()
        else:
            self._movecommand(x, y, z)
            self._waitformovement()

    def _movecommand(self, x: float, y: float, z: float):
        """internal command to execute a direct move from current location to new location"""
        if self.position == [x, y, z]:
            return True  # already at target position
        else:
            self.__targetposition = [x, y, z]
            self.write(f"G0 X{x} Y{y} Z{z}")
            return self._waitformovement()

    def moverel(self, x=0, y=0, z=0, zhop=False):
        """
        moves by coordinates relative to the current position
        """
        x += self.position[0]
        y += self.position[1]
        z += self.position[2]
        self.moveto(x, y, z, zhop)

    def moveto_sequence(self, coordinates: List[List[float]]):
        """
        moves to a sequence of coordinates

        coordinates: list of lists of x,y,z coordinates to move to
        """
        for (x, y, z) in coordinates:
            self.premove(x, y, z)  # will error out if invalid coordinates

        for (x, y, z) in coordinates:
            self._movecommand(x, y, z)
        self._waitformovement()

    def _waitformovement(self):
        """
        confirm that gantry has reached target position. returns False if
        target position is not reached in time allotted by self.TIMEOUT
        """
        self.inmotion = True
        start_time = time.time()
        time_elapsed = time.time() - start_time
        self._handle.write(f"M400\n".encode())
        self._handle.write(f"M118 E1 FinishedMoving\n".encode())
        reached_destination = False
        while not reached_destination and time_elapsed < self.TIMEOUT:
            time.sleep(self.POLLINGDELAY)
            while self._handle.in_waiting:
                line = self._handle.readline().decode("utf-8").strip()
                if line == "echo:FinishedMoving":
                    self.update()
                    if (
                        np.linalg.norm(
                            [
                                a - b
                                for a, b in zip(self.position, self.__targetposition)
                            ]
                        )
                        < self.POSITIONTOLERANCE
                    ):
                        reached_destination = True
                time.sleep(self.POLLINGDELAY)
            time_elapsed = time.time() - start_time

        self.inmotion = not reached_destination
        self.update()
        return reached_destination

    
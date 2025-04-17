from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np
import serial
import serial.tools.list_ports as lp


class BaseGcodeRobot(ABC):
    @property
    @abstractmethod
    def POLLINGDELAY(self) -> float:
        """The delay (in seconds) between sending a message and polling for a reply."""
        raise NotImplementedError

    @property
    @abstractmethod
    def TIMEOUT(self) -> float:
        """The timeout (in seconds) for waiting for a reply."""
        raise NotImplementedError

    @property
    @abstractmethod
    def POSITIONTOLERANCE(self) -> float:
        """The tolerance (in mm) between the target and actual position. Positions which are close within this value will be considered equal."""
        raise NotImplementedError

    @property
    @abstractmethod
    def ZHOP_HEIGHT(self) -> float:
        """The height (in mm) to raise the z-axis between lateral movements. This is to avoid collisions."""
        raise NotImplementedError

    @property
    @abstractmethod
    def XLIM(self) -> float:
        """The limit (in mm) of the x-axis."""
        raise NotImplementedError

    @property
    @abstractmethod
    def YLIM(self) -> float:
        """The limit (in mm) of the y-axis."""
        raise NotImplementedError

    @property
    @abstractmethod
    def ZLIM(self) -> float:
        """The limit (in mm) of the z-axis."""
        raise NotImplementedError

    @property
    @abstractmethod
    def MAX_XY_FEEDRATE(self) -> float:
        """The maximum feedrate (in mm/min) of the x and y axes."""
        raise NotImplementedError

    @property
    @abstractmethod
    def MAX_Z_FEEDRATE(self) -> float:
        """The maximum feedrate (in mm/min) of the z axis. Unless specified, we assume this is equal to the MAX_XY_FEEDRATE."""
        return self.MAX_XY_FEEDRATE

    def __init__(self, port: Optional[str | float] = None):
        """Connects to the robot. Note that you may need to home the robot after connecting before you can move!

        Args:
            port: Optional port to connect to the robot.
        """
        self.port = port
        self._position: tuple[float, float, float] = (
            np.nan,
            np.nan,
            np.nan,
        )  # not homed
        self.__targetposition: tuple[float, float, float] = (np.nan, np.nan, np.nan)
        self.connect()  # connect by default

    def connect(self) -> None:
        """Connects to the robot. If a port was not specified, this will prompt the user to select a port."""
        if self.port is None:
            self.port = select_port_cli()

        self._handle = serial.Serial(port=self.port, timeout=1, baudrate=115200)
        self.get_current_position()

        if self._position == (
            self.XLIM,
            self.YLIM,
            self.ZLIM,
        ):
            self._position = (np.nan, np.nan, np.nan)  # not homed

        self._set_defaults()

        print("Connected to robot!")

    def disconnect(self) -> None:
        """Disconnects from the robot."""
        self._handle.close()
        del self._handle
        print("Disconnected from robot!")

    def moveto(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        zhop: bool = False,
    ):
        """Moves to target position in x,y,z (mm). If a particular target coordinate is not supplied, automatically
        returns the current position for that coordinate.

        Args:
            x (float): Target x position (mm)
            y (float): Target y position (mm)
            z (float): Target z position (mm)
            zhop (bool): Whether to z-hop (raise the z-axis) before moving to the target position. This is useful to avoid collisions.
        """
        x, y, z = self.check_move_is_valid(x, y, z)  # check for invalid move

        ######################################################
        # Uncomment next line to print positions for each movement request

        #print("Moving to " + str((x, y, z)))


        if (x == self.position[0]) and (y == self.position[1]):
            zhop = False  # turn off zhopping if we're not moving in x or y

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

    def moverel(self, x=0, y=0, z=0, zhop=False):
        """
        moves by coordinates relative to the current position
        """
        try:
            if len(x) == 3:
                x, y, z, = x #split 3 coordinates into appropriate variables
        except:
            pass
        x += self.position[0]
        y += self.position[1]
        z+= self.position[2]
        self.moveto(x, y, z, zhop)

    def moveto_sequence(
        self, coordinates: List[tuple[float | None, float | None, float | None]]
    ) -> None:
        """Moves to a sequence of coordinates.

        Args:
            coordinates: list of lists of x,y,z coordinates to move to
        """
        for x, y, z in coordinates:
            self.check_move_is_valid(x, y, z)  # will error out if invalid coordinates

        for x, y, z in coordinates:
            self.moveto(x, y, z)

        self._waitformovement()

    def get_current_position(self) -> None:
        """Updates the position of the robot. Calls the M114 command to get the current position."""
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

        self._position = (x, y, z)

    def gohome(self) -> None:
        """Homes the robt (calls the G28 command) and updates the position."""
        self.write("G28 Z")
        self.write("G28 X Y Z")
        self.get_current_position()

    def gohome_x(self) -> None:
        """Homes the x-axis (calls the G28 command) and updates the position."""
        self.write("G28 X")
        self.get_current_position()

    def gohome_y(self) -> None:
        """Homes the y-axis (calls the G28 command) and updates the position."""
        self.write("G28 Y")
        self.get_current_position()
        
    def gohome_z(self) -> None:
        """Homes the z-axis (calls the G28 command) and updates the position."""
        self.write("G28 Z")
        self.get_current_position()

    def check_move_is_valid(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
    ) -> tuple[float, float, float]:
        """
        Checks to confirm that all target positions are valid. If a particular target coordinate is not supplied,
        automatically returns the current position for that coordinate.

        Args:
            x (float): Target x position (mm)
            y (float): Target y position (mm)
            z (float): Target z position (mm)
        """
        if not self.has_been_homed:
            raise Exception(
                "Stage has not been homed! Please call gohome() before moving."
            )
        if x is None:
            x = self.position[0]
        if y is None:
            y = self.position[1]
        if z is None:
            z = self.position[2]

        # check if this is a valid coordinate
        if not (0 <= x <= self.XLIM):
            raise ValueError(f"X coordinate {x} is out of range [0, {self.XLIM}].")
        if not (0 <= y <= self.YLIM):
            raise ValueError(f"Y coordinate {y} is out of range [0, {self.YLIM}].")
        if not (0 <= z <= self.ZLIM):
            raise ValueError(f"Z coordinate {z} is out of range [0, {self.ZLIM}].")

        return (x, y, z)

    def write(self, msg: str) -> List[str]:
        """Writes a message (in serial) to the robot and returns the response.

        Args:
            msg: The message to send to the robot (i.e., a G-code command)
        """
        self._handle.write(f"{msg}\n".encode())
        time.sleep(self.POLLINGDELAY)

        output = []
        while self._handle.in_waiting:
            line = self._handle.readline().decode("utf-8").strip()
            if line != "ok":
                output.append(line)
            time.sleep(self.POLLINGDELAY)
        return output

    @property
    def position(self) -> tuple[float, float, float]:
        """The current position of the robot."""
        return self._position

    @property
    def has_been_homed(self) -> bool:
        """Checks if the robot has been homed.)"""
        return self.position != (np.nan, np.nan, np.nan)

    @property
    def speed(self) -> float:
        """The speed (as a fraction of the maximum speed, 0-1) of the robot.

        Returns:
            float: Fraction (0-1) of the maximum speed.
        """
        return self._speed_fraction

    @speed.setter
    def speed(self, speed: float) -> None:
        """Sets the speed of the robot. Raises a ValueError if the speed is not between 0 and 1.

        Args:
            speed (float): Fraction (0-1) of the maximum speed.
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
    def speed_mm_per_min(self, speed: float) -> None:
        """Sets the speed of the robot in mm/min. Raises a ValueError if the speed is not between 0 and the maximum
        speed.

        Args:
            speed (float): The speed (in mm/min) of the robot.
        """
        if (speed <= 0) or (speed > self.MAX_XY_FEEDRATE):
            raise ValueError(
                f"Speed must be between 0 and {self.MAX_XY_FEEDRATE} mm/min."
            )
        self.speed = speed / self.MAX_XY_FEEDRATE

    def _set_defaults(self) -> None:
        self.write(
            f"M203 X{round(self.MAX_XY_FEEDRATE/60, 2)} Y{round(self.MAX_XY_FEEDRATE/60, 2)} Z{round(self.MAX_Z_FEEDRATE/60, 2)}"
        )
        self.speed = 0.8  # set the default speed to 80% of the maximum speed

    def _enable_steppers(self) -> None:
        """Enable steppers (M17 command)"""
        self.write("M17")

    def _disable_steppers(self) -> None:
        """Disable steppers (M18 command)"""
        self.write("M18")

    def _movecommand(self, x: float, y: float, z: float) -> bool:
        """Moves to a target position in x,y,z (mm). Uses the G0 command (non-print linear move).

        Args:
            x (float): Target x position (mm)
            y (float): Target y position (mm)
            z (float): Target z position (mm)

        Returns:
            bool: True if the target position was reached within TIMEOUT, False otherwise.
        """
        if self.position == (x, y, z):
            return True
        else:
            self.__targetposition = (x, y, z)
            self.write(f"G0 X{x} Y{y} Z{z}")
            return self._waitformovement()

    def _waitformovement(self) -> bool:
        """Confirm that gantry has reached target position.

        Returns False if target position is not reached in time allotted by self.TIMEOUT.
        """
        self.inmotion = True
        start_time = time.time()
        time_elapsed = time.time() - start_time
        self._handle.write("M400\n".encode())
        self._handle.write("M118 E1 FinishedMoving\n".encode())
        reached_destination = False
        while not reached_destination and time_elapsed < self.TIMEOUT:
            time.sleep(self.POLLINGDELAY)
            while self._handle.in_waiting:
                line = self._handle.readline().decode("utf-8").strip()
                if line == "echo:FinishedMoving":
                    self.get_current_position()
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
        self.get_current_position()
        return reached_destination


def select_port_cli() -> str:
    """Selects a port from a list of available ports. This is a command-line interface.

    Returns:
        str: Name of the port to connect to this device
    """
    ports = lp.comports()
    for i, p in enumerate(ports):
        print(f"[{i}] {p}, {p.hwid}")
    selection = int(input("Select a port: "))
    if selection < 0 or selection > i:
        raise ValueError("Invalid selection")
    return ports[selection].device

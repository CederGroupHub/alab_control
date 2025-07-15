from .._base_gcode_robot import BaseGcodeRobot


class Ender3(BaseGcodeRobot):
    """A class for controlling the Ender3 3D printer."""

    POLLINGDELAY = (
        0.001  # delay (in seconds) between sending a message and polling for a reply
    )
    TIMEOUT = 5  # timeout (in seconds) for waiting for a reply
    POSITIONTOLERANCE = 0.1  # tolerance (in mm) between the target and actual position. Positions which are close within this value will be considered equal.
    ZHOP_HEIGHT = 5  # height (in mm) to raise the z-axis between lateral movements. This is to avoid collisions.
    XLIM = 235  # limit (in mm) of the x-axis
    YLIM = 235  # limit (in mm) of the y-axis
    ZLIM = 150  # limit (in mm) of the z-axis
    MAX_XY_FEEDRATE = 10000  # maximum feedrate (in mm/min) of the x and y axes
    MAX_Z_FEEDRATE = (
        25 * 60
    )  # maximum feedrate (in mm/min) of the z axis. Unless specified, we assume this is equal to the MAX_XY_FEEDRATE.

import unittest
from alab_control import robot_arm_ur5e


class TestUR5e(unittest.TestCase):
    def setUp(self):
        self.robot = robot_arm_ur5e.URRobot(ip="192.168.182.135")

    def tearDown(self):
        self.robot.close()  # close the connection

    def test_is_running(self):
        is_running = self.robot.is_running()
        self.assertFalse(is_running, msg="The robot should not be running now.")

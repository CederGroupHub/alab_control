import time
import unittest
from alab_control import robot_arm_ur5e


class TestUR5e(unittest.TestCase):
    def setUp(self):
        self.robot = robot_arm_ur5e.BaseURRobot(ip="192.168.182.135")

    def tearDown(self):
        self.robot.close()  # close the connection

    def test_is_running(self):
        is_running = self.robot.is_running()
        self.assertFalse(is_running, msg="The robot should not be running now.")

    def test_run_program(self):
        self.robot.run_program("send_to_furnace_test")
        time.sleep(1)
        self.assertTrue(self.robot.is_running(), msg="The program does not start successfully.")
        self.robot.pause()
        time.sleep(1)
        self.robot.continue_play()
        self.assertFalse(self.robot.is_running(), msg="The program has not stop.")

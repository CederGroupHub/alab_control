import time

from alab_control.dh_robotic_gripper.dh_robotic_gripper import GripperController
from alab_control.robot_arm_ur5e import URRobotDashboard


class Capper:
    def __init__(self, capper_address):
        self.gripper = GripperController(port=capper_address)
        self.gripper.initialize()

    def open(self):
        self.gripper.open_to(position=500)

    def close(self):
        self.gripper.grasp()


capper = Capper("COM13")
robot_arm = URRobotDashboard("192.168.1.24")


def load_crucible_to_capper():
    robot_arm.run_program("auto_program/pick_crucible_near_bdis.auto.urp")
    robot_arm.run_program("auto_program/place_cru_capper.auto.urp")


def unload_crucible_to_capper():
    robot_arm.run_program("auto_program/pick_cru_capper.auto.urp")
    robot_arm.run_program("auto_program/place_crucible_near_bdis.auto.urp")


def capping(pos):
    load_crucible_to_capper()
    capper.close()
    robot_arm.run_program(f"auto_program/pick_hole_plug/pick_hole_plug_{pos}.auto.urp")
    robot_arm.run_program("auto_program/capping.auto.urp")
    capper.open()
    unload_crucible_to_capper()


def decapping(pos):
    load_crucible_to_capper()
    capper.close()
    robot_arm.run_program("auto_program/decapping.auto.urp")
    robot_arm.run_program(
        f"auto_program/place_hole_plug/place_hole_plug_{pos}.auto.urp"
    )
    capper.open()
    unload_crucible_to_capper()


if __name__ == "__main__":
    counter = 0
    while True:
        for p in ["A", "B"]:
            counter += 1
            start = time.time()
            print(f"Loop {counter}", end=" : ")
            capping(p)
            decapping("A" if p == "B" else "B")
            end = time.time()
            print(f"Time: {end - start} s")

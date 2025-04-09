import random
import time

from alab_control.dh_robotic_gripper.dh_robotic_gripper import GripperController
from alab_control.robot_arm_ur5e import URRobotDashboard


class Capper:
    def __init__(self, capper_address):
        self.gripper = GripperController(port=capper_address)
        self.gripper.initialize()

    def open(self):
        self.open_fully()
        time.sleep(0.2)
        self.gripper.open_to(position=500)

    def open_fully(self):
        self.gripper.open_to(position=1000)

    def close(self):
        self.open_fully()
        time.sleep(0.2)
        self.gripper.grasp()


capper = Capper("/dev/tty.usbserial-BG00U7A3")
robot_arm = URRobotDashboard("192.168.1.24")


def move_to_crucible_holder(pos):
    robot_arm.run_program(
        f"auto_program/pick_crucible_furnace_rack/pick_crucible_furnace_rack_{pos}.auto.urp"
    )
    capper.open_fully()
    robot_arm.run_program("auto_program/place_cru_capper.auto.urp")
    capper.close()
    capper.open()
    robot_arm.run_program("auto_program/pick_cru_capper.auto.urp")
    robot_arm.run_program("auto_program/place_crucible_near_bdis.auto.urp")


def put_back_crucible_holder(pos):
    robot_arm.run_program("auto_program/pick_crucible_near_bdis.auto.urp")
    robot_arm.run_program(
        f"auto_program/place_crucible_furnace_rack/place_crucible_furnace_rack_{pos}.auto.urp"
    )


def load_crucible_to_capper():
    robot_arm.run_program("auto_program/pick_crucible_near_bdis.auto.urp")
    robot_arm.run_program("auto_program/place_cru_capper.auto.urp")


def unload_crucible_to_capper():
    robot_arm.run_program("auto_program/pick_cru_capper.auto.urp")
    robot_arm.run_program("auto_program/place_crucible_near_bdis.auto.urp")


def capping(pos):
    capper.open()
    load_crucible_to_capper()
    robot_arm.run_program(f"auto_program/pick_hole_plug/pick_hole_plug_{pos}.auto.urp")
    robot_arm.run_program("auto_program/capping.auto.urp")
    unload_crucible_to_capper()


def decapping(pos):
    capper.open()
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
    SLOTS = ["A", "B", "C", "D"]
    while True:
        for furnace_rack in range(1, 9):
            counter += 1
            slot_to_use = random.choice(SLOTS)
            print(
                f"Loop: {counter}: Furnace Rack position {furnace_rack}, Hole Plug slot {slot_to_use}",
                end=" ",
            )
            start_time = time.time()
            move_to_crucible_holder(furnace_rack)
            decapping(slot_to_use)
            capping(slot_to_use)
            put_back_crucible_holder(furnace_rack)
            end_time = time.time()
            print(f"Time taken: {end_time - start_time:.2f} seconds")

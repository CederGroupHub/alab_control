import random
import time

from alab_control.robot_arm_ur5e import URRobotDashboard
from alab_control.speedmixer_hauschild_smart_dac400.dac import HauschildDAC400
from alab_control.dh_robotic_gripper.dh_robotic_gripper import GripperController


class Capper:
    def __init__(self, capper_address):
        self.gripper = GripperController(port=capper_address)
        self.gripper.initialize()

    def open(self):
        self.gripper.open_to(position=1000)
        self.gripper.open_to(position=500)

    def close(self):
        self.gripper.open_to(position=1000)
        self.gripper.grasp()


dac = HauschildDAC400("COM11")
robot_arm = URRobotDashboard("192.168.1.24")
capper = Capper("COM13")


def load_crucible_to_capper():
    robot_arm.run_program("auto_program/pick_crucible_near_bdis.auto.urp")
    robot_arm.run_program("auto_program/place_cru_capper.auto.urp")


def unload_crucible_to_capper():
    robot_arm.run_program("auto_program/pick_cru_capper.auto.urp")
    robot_arm.run_program("auto_program/place_crucible_near_bdis.auto.urp")


def capping(pos):
    capper.open()
    load_crucible_to_capper()
    capper.open()
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



def load_crucible_to_dac():
    robot_arm.run_program("auto_program/pick_crucible_near_bdis.auto.urp")
    dac.homing()
    robot_arm.run_program("auto_program/place_cru_dac.auto.urp")


def put_lid():
    robot_arm.run_program("auto_program/put_lid_on_dac.auto.urp")


def take_lid():
    robot_arm.run_program("auto_program/take_lid_on_dac.auto.urp")


def unload_crucible_to_dac():
    dac.homing()
    robot_arm.run_program("auto_program/pick_cru_dac.auto.urp")
    robot_arm.run_program("auto_program/place_crucible_near_bdis.auto.urp")


def run_dac():
    load_crucible_to_dac()
    put_lid()
    dac.run_program(200, 30)
    take_lid()
    unload_crucible_to_dac()


def open_rack(level):
    robot_arm.run_program(
        f"auto_program/open_consumable_rack/open_level_{level}.auto.urp"
    )


def close_rack(level):
    robot_arm.run_program(
        f"auto_program/close_consumable_rack/close_level_{level}.auto.urp"
    )


def pick_consumable(level, row, consum):
    robot_arm.run_program(
        f"auto_program/pick_consumable/pick_level_{level}_row_{row}_{consum}.auto.urp"
    )


def place_consumable(level, row, consum):
    robot_arm.run_program(
        f"auto_program/place_consumable/place_level_{level}_row_{row}_{consum}.auto.urp"
    )


def take_one_crucible(level, row):
    open_rack(level)
    pick_consumable(level, row, "crucible")
    robot_arm.run_program("auto_program/place_crucible_near_bdis.auto.urp")
    close_rack(level)


def put_back_crucible(level, row):
    open_rack(level)
    robot_arm.run_program("auto_program/pick_crucible_near_bdis.auto.urp")
    place_consumable(level, row, "crucible")
    close_rack(level)


if __name__ == "__main__":
    counter = 0
    prev_level = 0
    prev_row = 0
    while True:
        counter += 1

        start = time.time()
        take_one_crucible(prev_level, prev_row)

        print(f"Loop {counter}", end=" : ")
        capping("A")
        run_dac()
        level = random.randint(1, 7)
        row = random.randint(1, 5)
        decapping("A")
        put_back_crucible(level, row)
        prev_level = level
        prev_row = row
        end = time.time()
        print(f"Time: {end - start} s")

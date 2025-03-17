import random
import time

from alab_control.robot_arm_ur5e import URRobotDashboard
from alab_control.speedmixer_hauschild_smart_dac400.dac import HauschildDAC400

dac = HauschildDAC400("COM5")
robot_arm = URRobotDashboard("192.168.1.24")


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
    dac.run_program(500, 30)
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
    robot_arm.run_program("auto_program/pick_cru_dac.auto.urp")
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
        run_dac()
        level = random.randint(0, 7)
        row = random.randint(0, 5)
        put_back_crucible(level, row)
        prev_level = level
        prev_row = row
        end = time.time()
        print(f"Time: {end - start} s")

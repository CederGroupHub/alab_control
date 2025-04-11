import time

from alab_control.robot_arm_ur5e import URRobotDashboard
from alab_control.shaker_with_motor_controller.shaker_with_motor_controller import (
    ShakerWMC,
)

shaker = ShakerWMC("192.168.1.191")
robot_arm = URRobotDashboard("192.168.1.24")


def load_to_shaker():
    robot_arm.run_program("auto_program/pick_crucible_by_side.auto.urp")
    robot_arm.run_program("auto_program/load_cru_shaker.auto.urp")


def unload_from_shaker():
    robot_arm.run_program("auto_program/unload_cru_shaker.auto.urp")
    robot_arm.run_program("auto_program/place_crucible_by_side.auto.urp")


def shaking():
    shaker.close_gripper()
    shaker.shaking(10, 27)


if __name__ == "__main__":
    for i in range(10):
        print(f"Loop: {i}", end=" ")
        start_time = time.time()
        load_to_shaker()
        shaking()
        unload_from_shaker()
        print(f"Time: {time.time() - start_time:.2f} seconds")

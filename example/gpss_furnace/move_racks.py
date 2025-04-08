import random
import time

from alab_control.door_controller.door_controller_gpss import DoorController
from alab_control.robot_arm_ur5e import URRobotDashboard

furnace_door_controller = DoorController("192.168.1.88")
robot_arm = URRobotDashboard("192.168.1.24")

POSSIBLE_POSITIONS = ["A", "B", "in_fur_A", "in_fur_B", "loading"]


def pick_furnace_rack(from_):
    need_open_door = from_.startswith("in_fur")
    if need_open_door:
        furnace_door_controller.open_furnace(from_[-1])

    if from_ in {"A", "B"}:
        robot_arm.run_program(
            f"auto_program/pick_furnace_rack_f_side/pick_furnace_rack_{from_}.auto.urp"
        )
    else:
        robot_arm.run_program(f"auto_program/pick_furnace_rack_{from_}.auto.urp")

    if need_open_door:
        furnace_door_controller.close_furnace(from_[-1])


def place_furnace_rack(to_):
    need_open_door = to_.startswith("in_fur")
    if need_open_door:
        furnace_door_controller.open_furnace(to_[-1])

    if to_ in {"A", "B"}:
        robot_arm.run_program(
            f"auto_program/place_furnace_rack_f_side/place_furnace_rack_{to_}.auto.urp"
        )
    else:
        robot_arm.run_program(f"auto_program/place_furnace_rack_{to_}.auto.urp")

    if need_open_door:
        furnace_door_controller.close_furnace(to_[-1])


def pick_furnace_handle():
    robot_arm.run_program("auto_program/pick_furnace_handle.auto.urp")


def place_furnace_handle():
    robot_arm.run_program("auto_program/place_furnace_handle.auto.urp")


if __name__ == "__main__":
    prev_position = "loading"
    for i in range(10):
        next_position = random.choice(POSSIBLE_POSITIONS)
        print(f"Loop: {i}: {prev_position} -> {next_position}", end=" ")
        start_time = time.time()
        pick_furnace_handle()
        pick_furnace_rack(prev_position)
        place_furnace_rack(next_position)
        prev_position = next_position
        place_furnace_handle()
        print(f"Time taken: {time.time() - start_time:.2f} seconds")

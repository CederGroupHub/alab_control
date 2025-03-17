import random
import re
import time

from alab_control.labman_dosing_head_rack.labman_dosing_head_rack import DosingHeadRack
from alab_control.linear_rail_gpss.linear_rail_gpss import LinearRailGPSS
from alab_control.mt_auto_balance.auto_balance import MTAutoBalance
from alab_control.robot_arm_ur5e import URRobotDashboard

# Create a dosing head rack object
rack = DosingHeadRack("COM4")
linear_rail = LinearRailGPSS("COM10")
robot_arm = URRobotDashboard("192.168.1.23")
balance = MTAutoBalance("http://192.168.1.13:81")

SLOTS = ["A", "B", "C", "D"]


def pick_dosing_head(slot: str):
    robot_arm.run_program(f"auto_program/pick_dose_head_{slot}.auto.urp")


def place_dosing_head(slot: str):
    robot_arm.run_program(f"auto_program/place_dose_head_{slot}.auto.urp")


def load_crucible_to_balance():
    linear_rail.move_right()
    robot_arm.run_program("auto_program/pick_trans_rack_cru.auto.urp")
    balance.open_door("LeftOuter")
    robot_arm.run_program("auto_program/place_cru_balance.auto.urp")
    balance.close_door("LeftOuter")


def unload_crucible_to_balance():
    balance.open_door("LeftOuter")
    robot_arm.run_program("auto_program/pick_cru_balance.auto.urp")
    balance.close_door("LeftOuter")
    linear_rail.move_right()
    robot_arm.run_program("auto_program/place_trans_rack_cru.auto.urp")


def load_dosing_head_to_balance(pos):
    slot = re.search(r"\d+", pos).group()
    level = re.search(r"[A-D]", pos).group()
    rack.move_to_slot(int(slot))
    pick_dosing_head(level)
    place_dosing_head("balance")


def unload_dosing_head_to_balance(pos):
    slot = re.search(r"\d+", pos).group()
    level = re.search(r"[A-D]", pos).group()
    pick_dosing_head("balance")
    rack.move_to_slot(int(slot))
    place_dosing_head(level)


def dosing(prev_pos):
    load_crucible_to_balance()
    load_dosing_head_to_balance(prev_pos)
    balance.automatic_dosing(0.0, 10, 10)
    position = f"{random.choice(list(range(1, 15)))}{random.choice(SLOTS)}"
    unload_dosing_head_to_balance(position)
    unload_crucible_to_balance()
    return position


def capping():
    linear_rail.move_left()
    linear_rail.move_right()
    robot_arm.run_program("auto_program/pick_trans_rack_cap_A.auto.urp")
    robot_arm.run_program("auto_program/place_cap_B.auto.urp")
    robot_arm.run_program("auto_program/pick_trans_rack_vial.auto.urp")
    robot_arm.run_program("auto_program/decapping.auto.urp")
    robot_arm.run_program("auto_program/place_cap_A.auto.urp")
    robot_arm.run_program("auto_program/pick_cap_B.auto.urp")
    robot_arm.run_program("auto_program/capping.auto.urp")
    linear_rail.move_left()
    linear_rail.move_right()
    robot_arm.run_program("auto_program/place_trans_rack_vial.auto.urp")
    robot_arm.run_program("auto_program/pick_cap_A.auto.urp")
    robot_arm.run_program("auto_program/place_trans_rack_cap_A.auto.urp")


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


def pick_transfer_rack(consum):
    robot_arm.run_program(
        f"auto_program/pick_trans_rack/pick_trans_rack_{consum}.auto.urp"
    )


def place_transfer_rack(consum):
    robot_arm.run_program(
        f"auto_program/place_trans_rack/place_trans_rack_{consum}.auto.urp"
    )


def take_one_set(level, row):
    open_rack(level)
    for consum in ["cap_A", "cap_B", "crucible", "vial"]:
        pick_consumable(level, row, consum)
        place_transfer_rack(consum)
        pick_transfer_rack(consum)
        place_consumable(level, (row + 1) % 5, consum)
    close_rack(level)


if __name__ == "__main__":
    rack.reference_search()

    cnt = 0
    dosing_head_position = "1D"
    while True:
        cnt += 1
        print(f"Loop {cnt}", end=" : ")

        start = time.time()
        dosing_head_position = dosing(dosing_head_position)
        end = time.time()
        print(f"Dosing time: {end - start}", end=" , ")

        start = time.time()
        capping()
        end = time.time()
        print(f"Capping time: {end - start}")

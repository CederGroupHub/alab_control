import random
import re
import time

from alab_control.labman_dosing_head_rack.labman_dosing_head_rack import DosingHeadRack
from alab_control.linear_rail_gpss.linear_rail_gpss import LinearRailGPSS
from alab_control.mt_auto_balance.auto_balance import MTAutoBalance
from alab_control.robot_arm_ur5e import URRobotDashboard

# Create a dosing head rack object
rack = DosingHeadRack("/dev/tty.usbmodemTMCSTEP1")
linear_rail = LinearRailGPSS("/dev/tty.usbmodem6")
robot_arm = URRobotDashboard("192.168.1.23")
balance = MTAutoBalance("http://192.168.1.13:81")

SLOTS = ["A", "B", "C", "D"]


def pick_dosing_head(slot: str):
    robot_arm.run_program(f"pick_dose_head_{slot}.urp")


def place_dosing_head(slot: str):
    robot_arm.run_program(f"place_dose_head_{slot}.urp")


def load_crucible_to_balance():
    linear_rail.move_right()
    robot_arm.run_program("pick_trans_rack_cru.urp")
    balance.open_door("LeftOuter")
    robot_arm.run_program("place_cru_balance.urp")
    balance.close_door("LeftOuter")


def unload_crucible_to_balance():
    balance.open_door("LeftOuter")
    robot_arm.run_program("pick_cru_balance.urp")
    balance.close_door("LeftOuter")
    linear_rail.move_right()
    robot_arm.run_program("place_trans_rack_cru.urp")


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
    linear_rail.move_right()
    robot_arm.run_program("pick_trans_rack_cap_A.urp")
    robot_arm.run_program("place_cap_B.urp")
    robot_arm.run_program("pick_trans_rack_vial.urp")
    robot_arm.run_program("decapping.urp")
    robot_arm.run_program("place_cap_A.urp")
    robot_arm.run_program("pick_cap_B.urp")
    robot_arm.run_program("capping.urp")
    linear_rail.move_right()
    robot_arm.run_program("place_trans_rack_vial.urp")
    robot_arm.run_program("pick_cap_A.urp")
    robot_arm.run_program("place_trans_rack_cap_A.urp")


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

from itertools import product

from alab_control.labman_dosing_head_rack.labman_dosing_head_rack import DosingHeadRack
from alab_control.robot_arm_ur5e import URRobotDashboard

# Create a dosing head rack object
rack = DosingHeadRack("/dev/tty.usbmodemTMCSTEP1")
robot_arm = URRobotDashboard("192.168.0.22")

SLOTS = ["A", "B", "C", "D"]


def pick_dosing_head(slot: str):
    robot_arm.run_program(f"pick_dose_head_{slot}.urp")


def place_dosing_head(slot: str):
    robot_arm.run_program(f"place_dose_head_{slot}.urp")


def test_dosing_rack_rotation():
    for i in range(1, 15):
        rack.move_to_slot(i)


def test_moving_between_dosing_head_rack():
    # put the dosing head in 1D slot
    # moving dosing heads between slots on dosing head rack
    rack.move_to_slot(1)
    last_slot = "D"
    for slot in SLOTS:
        pick_dosing_head(last_slot)
        place_dosing_head(slot)
        last_slot = slot


def test_moving_between_dosing_head_rack_and_balance():
    # put the dosing head in 1D slot
    # moving the dosing head between slots on dosing head rack and balance
    rack.move_to_slot(1)
    last_slot = "D"
    for slot in SLOTS:
        pick_dosing_head(last_slot)
        place_dosing_head("balance")
        pick_dosing_head("balance")
        place_dosing_head(slot)
        last_slot = slot


def moving_load_unload_moving(last_slot, slot_):
    print(f"Moving from {last_slot} to {slot_}")
    rack.move_to_slot(int(last_slot[:-1]))
    pick_dosing_head(last_slot[-1])
    place_dosing_head("balance")
    pick_dosing_head("balance")
    rack.move_to_slot(int(slot_[:-1]))
    place_dosing_head(slot_[-1])


def test_moving_between_all_dosing_head_rack_slots_and_balance():
    # put the dosing head in 1D slot
    # moving the dosing head between slots on dosing head rack and balance

    last_pos = "1D"
    for rack_pos in list(range(2, 15)) + [1]:
        for slot in SLOTS:
            pos = f"{rack_pos}{slot}"
            moving_load_unload_moving(last_pos, pos)
            last_pos = pos


if __name__ == "__main__":
    # test_moving_between_all_dosing_head_rack_slots_and_balance()
    # moving_load_unload_moving("6D", "7A")
    test_moving_between_all_dosing_head_rack_slots_and_balance()

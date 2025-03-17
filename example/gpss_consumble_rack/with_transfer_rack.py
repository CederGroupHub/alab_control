from alab_control.robot_arm_ur5e import URRobotDashboard

robot_arm = URRobotDashboard("192.168.1.24")


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


if __name__ == "__main__":
    open_rack(4)
    close_rack(4)
    # make sure the linear rail is at the left position
    for level in range(5, 7):
        open_rack(level)
        print(f"Level {level}")
        for row in range(5):
            for consum in ["cap_A", "cap_B", "crucible", "vial"]:
                print(f"Level {level} Row {row} Consumable {consum}")
                pick_consumable(level, row, consum)
                place_transfer_rack(consum)
                pick_transfer_rack(consum)
                place_consumable(level, (row + 1) % 5, consum)
                # touch_consumable(level, row, consum)
        close_rack(level)

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


def touch_consumable(level, row, consum):
    robot_arm.run_program(
        f"auto_program/touch_consumable/touch_level_{level}_row_{row}_{consum}.auto.urp"
    )


def place_consumable(level, row, consum):
    robot_arm.run_program(
        f"auto_program/place_consumable/place_level_{level}_row_{row}_{consum}.auto.urp"
    )


if __name__ == "__main__":
    for level in range(5, 6):
        open_rack(level)
        print(f"Level {level}")
        for row in range(1, 6):
            for consum in ["vial", "crucible", "cap_A", "cap_B"]:
                print(f"Level {level} Row {row} Consumable {consum}")
                # pick_consumable(level, row, consum)
                # place_consumable(level, row, consum)
                touch_consumable(level, row, consum)
        close_rack(level)

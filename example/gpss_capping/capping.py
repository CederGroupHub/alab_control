import time

from alab_control.linear_rail_gpss.linear_rail_gpss import LinearRailGPSS
from alab_control.robot_arm_ur5e import URRobotDashboard

robot_arm = URRobotDashboard("192.168.1.23")
linear_rail = LinearRailGPSS("/dev/tty.usbmodemTMCSTEP1")


def test_moving_vials():
    linear_rail.move_right()
    robot_arm.run_program("pick_trans_rack_vial.urp")
    robot_arm.run_program("place_trans_rack_vial.urp")


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
    # test_moving_vials()
    cnt = 0
    while True:
        cnt += 1
        print(f"Loop {cnt}", end=" ")
        start = time.time()
        capping()
        end = time.time()
        print(f"Time: {end - start}")

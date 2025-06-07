import time

from alab_control.robot_arm_ur5e import URRobotDashboard

robot_arm = URRobotDashboard("192.168.1.23")


def capping():
    robot_arm.run_program("auto_program/pick_cap_A.auto.urp")
    robot_arm.run_program("auto_program/capping.auto.urp")
    robot_arm.run_program("auto_program/decapping.auto.urp")
    robot_arm.run_program("auto_program/place_cap_A.auto.urp")

    robot_arm.run_program("auto_program/pick_cap_B.auto.urp")
    robot_arm.run_program("auto_program/capping.auto.urp")
    robot_arm.run_program("auto_program/decapping.auto.urp")
    robot_arm.run_program("auto_program/place_cap_B.auto.urp")


    # robot_arm.run_program("pick_trans_rack_vial.urp")
    # robot_arm.run_program("place_cap_A.urp")
    # robot_arm.run_program("pick_cap_B.urp")
    # robot_arm.run_program("place_trans_rack_vial.urp")
    # robot_arm.run_program("pick_cap_A.urp")
    # robot_arm.run_program("place_trans_rack_cap_A.urp")


if __name__ == "__main__":
    cnt = 0
    while True:
        cnt += 1
        print(f"Loop {cnt}", end=" ")
        start = time.time()
        capping()
        end = time.time()
        print(f"Time: {end - start}")

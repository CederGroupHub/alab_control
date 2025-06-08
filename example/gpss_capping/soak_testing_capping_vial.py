import time

from alab_control.robot_arm_ur5e import URRobotDashboard
from xmlrpc.client import ServerProxy

robot_arm = URRobotDashboard("192.168.1.23")
capper = ServerProxy("http://192.168.1.89:8872")


def capping():
    robot_arm.run_program("auto_program/pick_cap_A.auto.urp")
    robot_arm.run_program("auto_program/capping.auto.urp")

    capper.open_fully()
    robot_arm.run_program("auto_program/place_vial_capper.auto.urp")
    capper.open()
    robot_arm.run_program("auto_program/pick_vial_capper.auto.urp")

    robot_arm.run_program("auto_program/decapping.auto.urp")
    robot_arm.run_program("auto_program/place_cap_A.auto.urp")

    ##

    robot_arm.run_program("auto_program/pick_cap_B.auto.urp")
    robot_arm.run_program("auto_program/capping.auto.urp")

    capper.open_fully()
    robot_arm.run_program("auto_program/place_vial_capper.auto.urp")
    capper.open()
    robot_arm.run_program("auto_program/pick_vial_capper.auto.urp")

    robot_arm.run_program("auto_program/decapping.auto.urp")
    robot_arm.run_program("auto_program/place_cap_B.auto.urp")


if __name__ == "__main__":
    cnt = 0
    while True:
        cnt += 1
        print(f"Loop {cnt}", end=" ")
        start = time.time()
        capping()
        end = time.time()
        print(f"Time: {end - start}")

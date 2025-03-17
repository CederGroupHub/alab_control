import time

from alab_control.robot_arm_ur5e import URRobotDashboard
from alab_control.speedmixer_hauschild_smart_dac400.dac import HauschildDAC400

dac = HauschildDAC400("COM5")
robot_arm = URRobotDashboard("192.168.1.24")


def load_crucible_to_dac():
    robot_arm.run_program("auto_program/pick_crucible_near_bdis.auto.urp")
    dac.homing()
    robot_arm.run_program("auto_program/place_cru_dac.auto.urp")


def put_lid():
    robot_arm.run_program("auto_program/put_lid_on_dac.auto.urp")


def take_lid():
    robot_arm.run_program("auto_program/take_lid_on_dac.auto.urp")


def unload_crucible_to_dac():
    dac.homing()
    robot_arm.run_program("auto_program/pick_cru_dac.auto.urp")
    robot_arm.run_program("auto_program/place_crucible_near_bdis.auto.urp")


def run_dac():
    dac.run_program(500, 30)


if __name__ == "__main__":
    counter = 0
    while True:
        counter += 1
        start = time.time()
        print(f"Loop {counter}", end=" : ")
        load_crucible_to_dac()
        put_lid()
        run_dac()
        take_lid()
        unload_crucible_to_dac()
        end = time.time()
        print(f"Time: {end - start} s")

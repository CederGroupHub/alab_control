import time

from alab_control.mt_auto_balance.auto_balance import MTAutoBalance
from alab_control.robot_arm_ur5e import URRobotDashboard

robot_arm = URRobotDashboard("192.168.1.23")
balance = MTAutoBalance("http://192.168.1.13:81")



def move_dosing_head():
    robot_arm.run_program("pick_dose_head_balance.urp")
    robot_arm.run_program("place_dose_head_balance.urp")


def load_crucible_to_balance():
    balance.open_door("LeftOuter")
    robot_arm.run_program("pick_cru_balance.urp")
    balance.close_door("LeftOuter")
    balance.open_door("LeftOuter")
    robot_arm.run_program("place_cru_balance.urp")
    balance.close_door("LeftOuter")


def dosing():
    move_dosing_head()
    load_crucible_to_balance()
    balance.automatic_dosing(0.05, 10, 10)



if __name__ == "__main__":
    cnt = 0
    for _ in range(20):
        cnt += 1
        print(f"Loop {cnt}", end=" ")
        start = time.time()
        dosing()
        end = time.time()
        print(f"Time: {end - start}")

from alab_control.dh_robotic_gripper.dh_robotic_gripper import GripperController
import time
for i in range(10):
    controller = GripperController("COM8")
    # print(1)
    controller.close()
    time.sleep(1)
    # controller.client.close()
    print(controller.read_gripper_position())
    # controller = None
    # controller.initialize()
    # print(controller.open_to(position=1000))
    # input("Press Enter to continue...")
    # try:
    #     controller.close()
    # except Exception as e:
    #     print(e)
    #     print("Error closing gripper")
    #     input("Press Enter to continue...")
    #     continue

    # input("Press Enter to continue...")

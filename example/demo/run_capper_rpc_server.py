from traceback import print_exc
from xmlrpc.server import SimpleXMLRPCServer

from alab_control.dh_robotic_gripper.dh_robotic_gripper import (
    GripperController,
    GripperStatus,
    RotationDirection,
)


class CapperXMLRPCServer:
    def __init__(self, capper_address):
        self.gripper = GripperController(port=capper_address)
        self.gripper.initialize()

    def open(self):
        self.gripper.open_to(position=925)
        self.gripper.rotate(-90, check_gripper=False)

    def close(self):
        self.gripper.grasp()

    def cap(self):
        self.gripper.set_gripper_force(90)
        self.gripper.set_rotation_speed(20)
        self.gripper.set_rotation_force(80)
        self.gripper.set_rotation_angle(-360 * 5)

    def decap(self):
        try:
            self.gripper.set_gripper_force(100)
            self.gripper.set_rotation_speed(20)
            self.gripper.set_rotation_force(100)
            self.gripper.set_rotation_angle(360 * 5)
        except Exception as e:
            print_exc()
            # self.gripper.stop_rotation()


# make an RPC server here
# gripeper = CapperXMLRPCServer(capper_address="/dev/tty.usbserial-BG005IB3")
# gripeper.cap()
gripper_client = CapperXMLRPCServer(capper_address="COM7")
server = SimpleXMLRPCServer(("", 8000), allow_none=True)
server.register_introspection_functions()
server.register_instance(gripper_client)
server.serve_forever()

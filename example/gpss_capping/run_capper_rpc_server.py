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

    def open(self):
        self.gripper.open_to(position=925)

    def close(self):
        self.gripper.grasp(check_gripper=True)

    def cap(self):
        self.gripper.set_gripper_force(100)
        self.gripper.set_gripper_speed(5)
        self.gripper.set_rotation_angle(-720)

    def decap(self):
        try:
            self.gripper.set_gripper_force(100)
            self.gripper.set_gripper_speed(5)
            self.gripper.set_rotation_angle(720)
        except Exception as e:
            print_exc()
            # self.gripper.stop_rotation()


# make an RPC server here
gripper_client = CapperXMLRPCServer(capper_address="/dev/tty.usbserial-BG005IB3")
server = SimpleXMLRPCServer(("", 8000), allow_none=True)
server.register_introspection_functions()
server.register_instance(gripper_client)
server.serve_forever()

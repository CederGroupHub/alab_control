from alab_control.dh_robotic_gripper.dh_robotic_gripper import (
    GripperController,
)
from xmlrpc.server import SimpleXMLRPCServer

gripper = GripperController(
    port="/dev/tty.usbserial-BG005IB3"
)  # Update the port based on your setu


# make an RPC server here
server = SimpleXMLRPCServer(("", 8000), allow_none=True)
server.register_introspection_functions()

server.register_instance(gripper)
server.serve_forever()
gripper.open_to()
gripper.initialize()
gripper.save_configuration()
gripper.open_to(position=925)
time.sleep(5)
gripper.grasp()
gripper.rotate(
    RotationDirection.CLOCKWISE, 1080, force=100, check_gripper=False, speed=10
)

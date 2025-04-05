from alab_control.robot_arm_ur5e import URRobotDashboard

robot_arm = URRobotDashboard("192.168.1.24")

for i in range(5):
    robot_arm.run_program("pick_furnace_handle.urp")
    robot_arm.run_program("pick_furnace_rack_loading.urp")
    robot_arm.run_program("place_furnace_rack_loading.urp")
    robot_arm.run_program("place_furnace_handle.urp")

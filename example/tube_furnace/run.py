from datetime import datetime
import time
from xmlrpc.client import ServerProxy
from alab_control.robot_arm_ur5e.robots import FurnaceDummy
from alab_control import furnace_2416
from alab_control.furnace_2416.furnace_driver import Segment, SegmentType, ProgramEndType, TimeUnit
from datetime import timedelta

robot = FurnaceDummy("192.168.0.22")
bf_a = furnace_2416.FurnaceController(port="COM3", timeout=1)
bf_b = furnace_2416.FurnaceController(port="COM4", timeout=1)
bf_c = furnace_2416.FurnaceController(port="COM5", timeout=1)
bf_d = furnace_2416.FurnaceController(port="COM6", timeout=1)
tb_e = ServerProxy("http://192.168.0.11:4001")
tb_f = ServerProxy("http://192.168.0.11:4002")
tb_g = ServerProxy("http://192.168.0.11:4004")
tb_h = ServerProxy("http://192.168.0.11:4003")

tube_furnaces = [tb_e, tb_g, tb_h]
box_furnaces = [bf_c]

tb_e.write_heating_profile(
    {
        "C01": 0,
        "T01": 98,
        "C02": 1000,
        "T02": 60,
        "C03": 1000,
        "T03": -121
    }
)

tb_g.write_heating_profile(
   {
        "C01": 0,
        "T01": 68,
        "C02": 700,
        "T02": 120,
        "C03": 700,
        "T03": -121
    }
)

tb_h.write_heating_profile(
    {
        "C01": 0,
        "T01": 98,
        "C02": 1000,
        "T02": 60,
        "C03": 1000,
        "T03": -121
    }
)

bf_c_segments = [
    Segment(segment_type=SegmentType.RAMP_RATE, target_setpoint=800,ramp_rate_per_min=10),
    Segment(segment_type=SegmentType.DWELL, duration=timedelta(hours=2)),
    Segment(segment_type=SegmentType.END, endt=ProgramEndType.STOP)
]

bf_c.configure_segments(*bf_c_segments)

# for tb in tube_furnaces:
#     tb.open_door()

for i in range(1,5):
    robot.run_program(f"Pick_Crucible_LBCS_{i}.urp", block=True)
    robot.run_program(f"Place_Crucible_TF_E_{i}.urp", block=True)

for i in range(5,9):
    robot.run_program(f"Pick_Crucible_LBCS_{i}.urp", block=True)
    robot.run_program(f"Place_Crucible_BFRACK_3_{i-4}.urp", block=True)

robot.run_program("OpenDoor_C.urp", block=True)
robot.run_program("Pick_BFRACK_3.urp", block=True)
robot.run_program("Place_BF_C.urp", block=True)
robot.run_program("CloseDoor_C.urp", block=True)

for i in range(9,13):
    robot.run_program(f"Pick_Crucible_LBCS_{i}.urp", block=True)
    robot.run_program(f"Place_Crucible_TF_G_{i-8}.urp", block=True)

for i in range(13,15):
    robot.run_program(f"Pick_Crucible_LBCS_{i}.urp", block=True)
    robot.run_program(f"Place_Crucible_TF_H_{i-12}.urp", block=True)

for tb in tube_furnaces:
    tb.start_program()

for bf in box_furnaces:
    bf.play(block=False)

status = [tb.is_running() for tb in tube_furnaces]
status += [bf.is_running() for bf in box_furnaces]
while any(status):
    time.sleep(5)
    status = [tb.is_running() for tb in tube_furnaces]
    status += [bf.is_running() for bf in box_furnaces]
    print("Waiting for tube furnaces and box furnaces to finish: {} Time: {}".format(status, datetime.now()))

print("All tube and box furnaces finished. Time: {}".format(datetime.now()))

# for tb in tube_furnaces:
#     tb.open_door()

for i in range(1,5):
    robot.run_program(f"Pick_Crucible_TF_E_{i}.urp", block=True)
    robot.run_program(f"Place_Crucible_BFTR_{i}.urp", block=True)

for i in range(1,5):
    robot.run_program(f"Pick_Crucible_TF_G_{i}.urp", block=True)
    robot.run_program(f"Place_Crucible_BFTR_{i+4}.urp", block=True)

robot.run_program("OpenDoor_C.urp", block=True)
robot.run_program("Pick_BF_C.urp", block=True)
robot.run_program("Place_BFRACK_3.urp", block=True)
robot.run_program("CloseDoor_C.urp", block=True)


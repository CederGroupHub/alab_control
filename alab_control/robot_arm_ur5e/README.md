# robot_arm_ur5e
This module is intended for running ur program via dashboard server.

## Usage

```python
from robot_arm_ur5e import URRobot

ur_robot = URRobot("192.168.132.154")
if not ur_robot.is_remote_mode():
    raise OSError("The robot arm should be in remote mode.")

# You may run the program by specifying the path.
ur_robot.run_program("send_to_furnace_test")

# when necessary, you can pause a running program
ur_robot.pause()
# and continue to play it
ur_robot.continue_play()

# If you want, you can also use raw command mode,
# which will return the response string
ur_robotend_cmd("get operational mode")
```

## Programs in CharDummy
dumping_combined
-	dumping

move_cru_B
-	pick_cru_B
-	place_cru_B

tapping
-	before_tapping
-	after_tapping

weighing
-	before_weighing
-	after_weighing

ball_dispensing
-	before_ball_dispensing
-	after_ball_dispensing

shaking_cru
-	before_shaking_cru
-	after_shaking_cru

shaking_vial
-   before_shaking_vial
-   after_shaking_vial

dumping2capper_vial
-	move_vial_dumping_capper
-	move_vial_capper_dumping

move_vial_dumping_station
-	pick_vial_dumping_station
-	place_vial_dumping_station

move_vial_tapping_station
-	pick_vial_tapping_station
-	place_vial_tapping_station

move_cap_B
-	pick_cap_B
-	place_cap_B

capping_combi
-	capping

decapping_combi
-	decapping

move_cap_A
-   pick_cap_A
-   place_cap_A
  
move_cap_cru_B
-   pick_cap_cru_B
-   place_cap_cru_B

start_trans
-   vertical_to_horizonal
-   horizonal_to_vertical

xrd_powder_dispensing_combi
-   after_weighing_vial
-   before_weighing_vial
-   place_vial_dumping_station_reverse
-   pick_vial_dumping_station_reverse
-   xrd_powder_dispensing

xrd_sample_flattening_combi
-   xrd_sample_flattening

move_xrd_dispense_station
-   pick_xrd_dispense_station
-   place_xrd_dispense_station

move_xrd_holder_machine
-   pick_xrd_holder_machine
-   place_xrd_holder_machine

pick_cap_dispensers
-   pick_cap_dispenser_A
-   pick_cap_dispenser_B
-   pick_cap_dispenser_C

dispose

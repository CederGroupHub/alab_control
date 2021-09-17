# robot_arm_ur5e
This module is intended for running ur program via dashboard server.

## Usage

```python
from robot_arm_ur5e import URRobot

ur_robot = URRobot("192.168.132.154")
if not ur_robot.is_remote_mode():
    raise OSError("The robot arm should be in remote mode.")

# You may run the program by specifying the path.
ur_robot.run_program("Red_rack_in_fsuccess.urp")

# when necessary, you can pause a running program
ur_robot.pause()
# and continue to play it
ur_robot.continue_play()

# If you want, you can also use raw command mode,
# which will return the response string
ur_robot.send_cmd("get operational mode")
```

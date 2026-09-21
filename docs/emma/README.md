# Mobile robot (alab_control)

After merging `emma_mobile_robot` into `main`, this is the supported stack:

- Runtime routing in `alab_control.mobile_robot_arm.programs` / `driver`
- Ability programs on the controller: `base_*` (drive) and `robotarm_*` (pick/place)
- Manual-mode handshake and charge settle on `MobileRobotArm`

Pair with `alab_one` `RobotArmMobile` (`program_mode = "split"`).

The older library-split attempt (`Shared` / `Station_*` / `Run_*`) is obsolete and
should not be deployed.

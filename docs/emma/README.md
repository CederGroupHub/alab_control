# Mobile robot (alab_control)

After merging `emma_mobile_robot` into `main`, this is the supported stack:

- Split Ability programs under `scripts/mobile_robot_program_split/`
- Runtime routing in `alab_control.mobile_robot_arm.programs` / `run_program`
- Manual-mode handshake and charge settle on `MobileRobotArm`

Pair with `alab_one` `RobotArmMobile` (`program_mode = "split"`).

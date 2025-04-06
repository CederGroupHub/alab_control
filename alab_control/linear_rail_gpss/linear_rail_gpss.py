import time

from alab_control._base_tmcl_stepper_motor_controller import (
    AxisParameters,
    Commands,
    TMCLStepperMotorController,
)


class LinearRailGPSS(TMCLStepperMotorController):
    """
    The wrapper class for TMCM-1140.

    ..Note ::
    In current GPSS setting, if you stand near the linear rail side,
    the moving to right command will move the rail to the left.
    """

    _has_external_encoder = False

    LEFT = 1
    RIGHT = -1

    def update_motor_config(self):
        """
        Update the motor configuration.
        """
        self.set_axis_parameter(AxisParameters.MAX_POSITIONING_SPEED, 200)
        self.set_axis_parameter(AxisParameters.MAX_ACCELERATION, 200)
        # REF_SEARCH_MODE = 7: search home switch in positive direction, ignore end switches
        # self.set_axis_parameter(AxisParameters.REF_SEARCH_MODE, 7)
        self.set_axis_parameter(AxisParameters.REF_SEARCH_SPEED, 200)
        # Set the microstep resolution to 8, which is 64 microsteps per full step
        self.set_axis_parameter(AxisParameters.MICROSTEP_RESOLUTION, 6)
        # stop right at the end switch
        self.set_axis_parameter(AxisParameters.SOFT_STOP_FLAG, 0)

        # Switch off the pull ups for receiving the stop_L, stop_R switch signal
        # type number 0: no pull ups
        self.send_command(Commands.SIO, type_number=0, motor_number=0, value=0)

        # enable both end switches
        self.set_axis_parameter(AxisParameters.RIGHT_LIMIT_SWITCH_DISABLED, 0)
        self.set_axis_parameter(AxisParameters.LEFT_LIMIT_SWITCH_DISABLED, 0)

    def move_right(self):
        def move_right_until_end_switch(speed: int):
            self.send_command(Commands.ROL, motor_number=0, value=speed)
            start_time = time.time()
            while (
                self.get_axis_parameter(AxisParameters.LEFT_LIMIT_SWITCH_STATE) == 0
                and time.time() - start_time < 60
            ):
                time.sleep(0.1)
            else:
                self.send_command(Commands.MST, motor_number=0)
                if time.time() - start_time >= 60:
                    raise TimeoutError(
                        "Failed to reach end switch within 120 seconds. Stopped."
                    )

        move_right_until_end_switch(2047)
        current_position = self.get_axis_parameter(AxisParameters.ACTUAL_POSITION)
        self.move_to_position(current_position + 2500 * self.LEFT, block=True)

        # do a finer calibration
        move_right_until_end_switch(100)

    def move_left(self):
        def move_left_until_end_switch(speed: int):
            self.send_command(Commands.ROR, motor_number=0, value=speed)
            start_time = time.time()
            while (
                self.get_axis_parameter(AxisParameters.RIGHT_LIMIT_SWITCH_STATE) == 0
                and time.time() - start_time < 60
            ):
                time.sleep(0.1)
            else:
                self.send_command(Commands.MST, motor_number=0)
                if time.time() - start_time >= 60:
                    raise TimeoutError(
                        "Failed to reach end switch within 120 seconds. Stopped."
                    )

        move_left_until_end_switch(2047)
        current_position = self.get_axis_parameter(AxisParameters.ACTUAL_POSITION)
        self.move_to_position(current_position + 2500 * self.RIGHT, block=True)

        # do a finer calibration
        move_left_until_end_switch(100)


if __name__ == "__main__":
    linear_rail = LinearRailGPSS("/dev/tty.usbmodemTMCSTEP1")
    linear_rail.move_left()
    # for i in range(10):
    #     start_time = time.time()
    #     linear_rail.move_right()
    #     end_time = time.time()
    #     print(f"Time to move right: {end_time - start_time}")
    #     time.sleep(1)
    #     start_time = time.time()
    #     linear_rail.move_left()
    #     end_time = time.time()
    #     print(f"Time to move left: {end_time - start_time}")
    # # while True:
    # #     print(linear_rail.send_command(Commands.GIO, motor_number=0, type_number=1))
    # #     time.sleep(0.5)

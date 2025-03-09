from __future__ import annotations

from alab_control._base_tmcl_stepper_motor_controller import (
    AxisParameters,
    Commands,
    TMCLStepperMotorController,
)


class DosingHeadRack(TMCLStepperMotorController):
    RACK_OFFSET = 3
    _has_external_encoder = True

    def update_motor_config(self):
        """
        Update the motor configuration.
        """
        self.set_axis_parameter(AxisParameters.MAX_POSITIONING_SPEED, 1500)
        self.set_axis_parameter(AxisParameters.MAX_ACCELERATION, 200)
        # REF_SEARCH_MODE = 7: search home switch in positive direction, ignore end switches
        self.set_axis_parameter(AxisParameters.REF_SEARCH_MODE, 7)
        self.set_axis_parameter(AxisParameters.REF_SEARCH_SPEED, 1000)
        # Set the microstep resolution to 8, which is 256 microsteps per full step
        self.set_axis_parameter(AxisParameters.MICROSTEP_RESOLUTION, 8)

        # Set the external encoder prescale factor to 256
        self.set_axis_parameter(AxisParameters.EXTERNAL_ENCODER_PRESCALE_FACTOR, 8192)
        # disable the max external encoder deviation
        self.set_axis_parameter(AxisParameters.MAX_EXTERNAL_ENCODER_DEVIATION, 0)

        # Switch off the pull ups for receiving the home switch signal
        # type number 0: no pull ups
        self.send_command(Commands.SIO, type_number=0, motor_number=0, value=0)

    def move_to_slot(self, slot_id: int):
        if not 1 <= slot_id <= 14:
            raise ValueError("The slot ID should be between 1 and 14.")

        slot_id = (slot_id + self.RACK_OFFSET) % 14
        if slot_id <= 0:
            slot_id = 14 + slot_id

        # The slot ID is the position in microsteps
        position = int(256_000 / 14 * (slot_id - 1))
        self.move_to_position(position, block=True)


if __name__ == "__main__":
    rack = DosingHeadRack("/dev/tty.usbmodemTMCSTEP1")
    # rack.move_to_position(0, block=True)
    # rack.stop()
    rack.reference_search()
    #
    # for i in range(1000):
    #     # move 10000 microsteps
    #     rack.move_to_position(1000 * i, block=True)
    #     print(
    #         f"Actual position: {rack.get_axis_parameter(AxisParameters.ACTUAL_POSITION)}\n"
    #         f"External encoder position: {rack.get_external_encoder_position()}\n"
    #     )

    # rack.move_to_position(0)
    # print(f"External encoder position: {rack.get_external_encoder_position()}")
    # rack.move_to_position(256_000)
    # print(f"External encoder position: {rack.get_external_encoder_position()}")
    # while True:
    #     print(
    #         f"Actual position: {rack.get_axis_parameter(AxisParameters.ACTUAL_POSITION)}\n"
    #         f"External encoder position: {rack.get_external_encoder_position()}\n"
    #     )
    # # print(rack.send_command(Commands.RFS, type_number=2)["value"])
    # rack.move_to_slot(7)
    # for i in range(1, 15):
    #     rack.move_to_slot(i)
    #     time.sleep(1)
    # rack.move_to_slot(1)
    # time.sleep(600)
    # rack.move_to_slot(5)
    # time.sleep(5)
    # rack.move_to_slot(5)
    # print(rack.get_axis_parameter(AxisParameters.STANDBY_CURRENT))

    # for i in range(14):
    #     rack.move_to_slot(i + 1)
    #     print(
    #         f"Actual position: {rack.get_axis_parameter(AxisParameters.ACTUAL_POSITION)}\n"
    #         f"External encoder position: {rack.get_external_encoder_position()}\n"
    #     )

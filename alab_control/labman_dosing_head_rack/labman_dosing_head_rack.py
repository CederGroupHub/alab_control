from __future__ import annotations

import time
from enum import IntEnum

from serial import Serial
from struct import pack, unpack


class Commands(IntEnum):
    MST = 3
    MVP = 4
    SAP = 5
    GAP = 6
    RFS = 13
    SIO = 14
    WAIT = 27


class AxisParameters(IntEnum):
    TARGET_POSITION = 0
    ACTUAL_POSITION = 1
    TARGET_SPEED = 2
    ACTUAL_SPEED = 3
    MAX_POSITIONING_SPEED = 4
    MAX_ACCELERATION = 5
    ABSOLUTE_MAX_CURRENT = 6
    STANDBY_CURRENT = 7
    TARGET_POSITION_REACHED = 8
    MICROSTEP_RESOLUTION = 140
    REF_SEARCH_MODE = 193
    REF_SEARCH_SPEED = 194
    POWER_DOWN_DELAY = 214


class ChecksumError(Exception):
    """Raised when the checksum of a frame is incorrect."""


class CommandError(Exception):
    """Raised when a command fails."""


class DosingHeadRack:
    RACK_OFFSET = 3

    def __init__(self, port: str):
        self.port = port
        self.update_motor_config()

    def update_motor_config(self):
        """
        Update the motor configuration.
        """
        self.set_axis_parameter(AxisParameters.MAX_POSITIONING_SPEED, 1500)
        self.set_axis_parameter(AxisParameters.MAX_ACCELERATION, 250)
        # REF_SEARCH_MODE = 7: search home switch in positive direction, ignore end switches
        self.set_axis_parameter(AxisParameters.REF_SEARCH_MODE, 7)
        self.set_axis_parameter(AxisParameters.REF_SEARCH_SPEED, 1000)
        # Set the microstep resolution to 8, which is 256 microsteps per full step
        self.set_axis_parameter(AxisParameters.MICROSTEP_RESOLUTION, 8)

        # Increase the standby current to 10%
        self.set_axis_parameter(AxisParameters.STANDBY_CURRENT, 10)
        # Increase the standby timeout to 60 seconds [6000 * 10ms]
        self.set_axis_parameter(AxisParameters.POWER_DOWN_DELAY, 6000)
        # Switch on the pull ups for receiving the home switch signal
        # type number 0: pull ups
        self.send_command(Commands.SIO, type_number=0, motor_number=0, value=0)

    def move_to_slot(self, slot_id: int):
        if not 1 <= slot_id <= 14:
            raise ValueError("The slot ID should be between 1 and 14.")

        slot_id = (slot_id + self.RACK_OFFSET) % 14
        if slot_id <= 0:
            slot_id = 14 + slot_id

        # The slot ID is the position in microsteps
        position = int(256_000 / 14 * (14 - slot_id + 1))

        # a reference search is needed to move to the slot
        self.move_to_position(0, block=True)
        self.reference_search(timeout=120)

        self.move_to_position(position, block=True)

    def reference_search(self, timeout: float = None):
        """
        Perform a reference search. It will block until the reference search is completed.
        """
        # type number 0: start reference search
        # type number 1: stop reference search
        # type number 2: status of reference search
        self.send_command(Commands.RFS, type_number=0)

        while True:  # wait until the reference search is started
            if self.send_command(Commands.RFS, type_number=2)["value"] != 0:
                break
        start_time = time.time()
        while True:
            if self.send_command(Commands.RFS, type_number=2)["value"] == 0:
                break
            if timeout is not None and time.time() - start_time > timeout:
                self.send_command(Commands.RFS, type_number=1)
                raise TimeoutError(
                    "Timeout while waiting for the reference search to be completed."
                    " Stopping the motor."
                )

    def move_to_position(
        self, position: int, block: bool = True, timeout: float = None
    ):
        """
        Move the dosing head to the specified position.
        Args:
            position: the target position
            block: whether to block until the target position is reached
            timeout: the timeout in seconds
        """
        # type number 0: absolute positioning
        self.send_command(Commands.MVP, type_number=0, value=position)

        while True:  # wait until the movement is started
            if self.get_axis_parameter(AxisParameters.TARGET_POSITION) == position:
                break

        if block:
            start_time = time.time()
            while True:
                if self.get_axis_parameter(AxisParameters.TARGET_POSITION_REACHED):
                    break
                if timeout is not None and time.time() - start_time > timeout:
                    self.stop()
                    raise TimeoutError(
                        "Timeout while waiting for the target position to be reached."
                        " Stopping the motor."
                    )
                time.sleep(0.1)

    def stop(self):
        """
        Stop the dosing head.
        """
        self.send_command(Commands.MST)

    def get_axis_parameter(self, axis_parameter: AxisParameters) -> int:
        """
        Get the axis parameter.
        Returns:
            the axis parameter
        """
        return self.send_command(Commands.GAP, type_number=axis_parameter.value)[
            "value"
        ]

    def set_axis_parameter(self, axis_parameter: AxisParameters, value: int):
        """
        Set the axis parameter.
        """
        self.send_command(Commands.SAP, type_number=axis_parameter.value, value=value)

    def send_command(
        self,
        command: Commands,
        type_number: int = 0,
        motor_number: int = 0,
        value: int = 0,
        raise_failure: bool = True,
    ) -> dict[str, int]:
        """
        The basic function to send a command to the dosing head rack.

        The command should be encoded into 9 bytes:
            1 Module address
            1 Command number
            1 Type number
            1 Motor or Bank number
            4 Value (MSB first!)
            1 Checksum

        Args:
            command: the command number
            type_number: the type number
            motor_number: the motor number
            value: the value of the command
            raise_failure: whether to raise an exception if the command fails

        Returns:
            A dictionary with the following:
                reply_address: the reply address
                module_address: the module address
                status: the status
                command_number: the command number
                value: the value
                checksum: the checksum
        """
        print(f"Sending command {command} with value {value}")
        with Serial(self.port, 9600, timeout=1) as ser:
            struct = pack(">BBBBI", 1, command.value, type_number, motor_number, value)
            checksum = sum(struct) % 256
            struct = struct + pack("B", checksum)
            ser.write(struct)
            ser.flush()

            time.sleep(0.1)

            # delay 100ms if receive is blank, just waiting 5s.
            n = 0
            while ser.inWaiting() == 0:
                time.sleep(0.1)
                n = n + 1
                if n > 50:
                    # send frame again
                    ser.write(value)
                    break
            # every 100ms check the data receive is ready
            byte_number_1 = 0
            byte_number_2 = 1
            while byte_number_1 != byte_number_2:
                byte_number_1 = ser.inWaiting()
                time.sleep(0.1)
                byte_number_2 = ser.inWaiting()

            receive_frame = ser.read_all()
            (
                reply_address,
                module_address,
                status,
                command_number,
                value,
                checksum,
            ) = unpack(">BBBBIB", receive_frame)
            if checksum != sum(receive_frame[:-1]) % 256:
                raise ChecksumError(
                    "Different checksum detected in the received frame."
                )
            if status != 100 and raise_failure:
                raise CommandError(f"Command {command} failed with status {status}")
            return {
                "reply_address": reply_address,
                "module_address": module_address,
                "status": status,
                "command_number": command_number,
                "value": value,
                "checksum": checksum,
            }


if __name__ == "__main__":
    rack = DosingHeadRack("/dev/tty.usbmodemTMCSTEP1")
    # rack.move_to_position(0, block=True)
    # rack.stop()
    # rack.reference_search()
    # # print(rack.send_command(Commands.RFS, type_number=2)["value"])
    rack.move_to_slot(7)
    # for i in range(1, 15):
    #     rack.move_to_slot(i)
    #     time.sleep(1)
    # rack.move_to_slot(1)
    # time.sleep(600)
    # rack.move_to_slot(5)
    # time.sleep(5)
    # rack.move_to_slot(5)
    # print(rack.get_axis_parameter(AxisParameters.STANDBY_CURRENT))

from __future__ import annotations

import time
from enum import IntEnum
from struct import pack, unpack

from serial import Serial
from serial.tools.list_ports import comports


class Commands(IntEnum):
    ROR = 1
    ROL = 2
    MST = 3
    MVP = 4
    SAP = 5
    GAP = 6
    RFS = 13
    SIO = 14
    GIO = 15
    WAIT = 27
    FIRMWARE_VERSION = 136


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
    RIGHT_LIMIT_SWITCH_STATE = 10
    LEFT_LIMIT_SWITCH_STATE = 11
    RIGHT_LIMIT_SWITCH_DISABLED = 12
    LEFT_LIMIT_SWITCH_DISABLED = 13
    MICROSTEP_RESOLUTION = 140
    SOFT_STOP_FLAG = 149
    END_SWITCH_POWER_DOWN_MODE = 150
    REF_SEARCH_MODE = 193
    REF_SEARCH_SPEED = 194
    POWER_DOWN_DELAY = 214
    EXTERNAL_ENCODER_POSITION = 216
    EXTERNAL_ENCODER_PRESCALE_FACTOR = 217
    MAX_EXTERNAL_ENCODER_DEVIATION = 218


class ChecksumError(Exception):
    """Raised when the checksum of a frame is incorrect."""


class CommandError(Exception):
    """Raised when a command fails."""


class TMCLStepperMotorController:
    _has_external_encoder = False
    _VID = 0x2A3C

    def __init__(self, firmware_version: int) -> None:
        self.firmware_version = firmware_version
        self.port = None
        self.port = self._determine_comport_by_firmware_version()
        self.update_motor_config()

    def update_motor_config(self):
        raise NotImplementedError()

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

        # after the reference search is completed, set the external encoder position to 0
        if self._has_external_encoder:
            self.set_external_encoder_position(0)

    def get_external_encoder_position(self) -> float:
        """
        Get the external encoder position.
        Returns:
            the external encoder position
        """
        if not self._has_external_encoder:
            raise ValueError("The motor does not have an external encoder.")

        # we add the factor here to get the correct position
        return self.get_axis_parameter(AxisParameters.EXTERNAL_ENCODER_POSITION) * 1.6

    def set_external_encoder_position(self, position: int):
        """
        Set the external encoder position.
        """
        if not self._has_external_encoder:
            raise ValueError("The motor does not have an external encoder.")
        self.set_axis_parameter(AxisParameters.EXTERNAL_ENCODER_POSITION, position)

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
        if self._has_external_encoder:
            external_encoder_position = int(self.get_external_encoder_position())
            position = (position - external_encoder_position) % 256_000
            actual_position = self.get_axis_parameter(AxisParameters.ACTUAL_POSITION)
            # type number 0: relative positioning
            self.send_command(Commands.MVP, type_number=1, value=position)
        else:
            actual_position = 0
            # type number 0: absolute positioning
            self.send_command(Commands.MVP, type_number=0, value=position)

        while True:  # wait until the movement is started
            if (
                self.get_axis_parameter(AxisParameters.TARGET_POSITION)
                == position + actual_position
            ):
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

    def is_running(self):
        return self.get_axis_parameter(AxisParameters.TARGET_POSITION_REACHED) == 0

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
        # print(f"Sending command {command} with value {value}")
        with Serial(self.port, 9600, timeout=1) as ser:
            struct = pack(">BBBBi", 1, command.value, type_number, motor_number, value)
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
            ) = unpack(">BBBBiB", receive_frame)
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

    def get_firmware_version(self) -> int:
        """
        Get the firmware version of the motor.
        Returns:
            The firmware version as a int.
        """
        version = self.send_command(
            Commands.FIRMWARE_VERSION, type_number=1, motor_number=0, value=0
        )["value"]
        return version

    def _determine_comport_by_firmware_version(self) -> str:
        tmcl_devices_port = [
            com_port for com_port in comports() if com_port.vid == self._VID
        ]
        for port in tmcl_devices_port:
            self.port = port.device
            if self.firmware_version == self.get_firmware_version():
                return port.device
        raise RuntimeError(f"Firmware version {self.firmware_version} not found.")

    def __del__(self):
        # stop the motor when the object is deleted
        self.stop()

    def close(self):
        """
        Close the serial port.
        """
        self.stop()

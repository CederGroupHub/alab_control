from __future__ import annotations

import time
from enum import Enum

from pymodbus.client.sync import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusException


class InitializationStatus(Enum):
    NOT_INITIALIZED = 0
    INITIALIZED = 1
    INITIALIZING = 2


class RotationDirection(Enum):
    CLOCKWISE = 1
    COUNTERCLOCKWISE = -1


class RotationMode(Enum):
    RELATIVE = 0
    ABSOLUTE = 1


class RotationStatus(Enum):
    MOVING = 0
    REACHED = 1
    BLOCKED_MOVING = 2
    BLOCKED = 3


class GripperStatus(Enum):
    MOVING = 0
    ARRIVED = 1
    GRASPED = 2
    DROPPED = 3


class GripperController:
    def __init__(self, port, slave_address=1, baudrate=115200):
        # Setup Modbus RTU client
        self.client = ModbusClient(
            method="rtu",
            port=port,
            baudrate=baudrate,
            timeout=1,
            stopbits=1,
            bytesize=8,
            parity="N",
        )
        self.slave_address = slave_address
        if not self.client.connect():
            raise ModbusException("Unable to connect to the gripper")

        self.load_defaults()

    def load_defaults(self):
        # stop when gripper is blocked
        self.client.write_register(0x0505, 1, unit=self.slave_address)
        # disable auto initialization
        self.client.write_register(0x0504, 0, unit=self.slave_address)

    def set_rotating_blocking(self, enabled: bool):
        # 0: do not stop when gripper is blocked
        # 1: stop when gripper is blocked
        self.client.write_register(0x0505, int(enabled), unit=self.slave_address)

    def initialize(self, wait=True, mode: int = 0xA5):
        if self.check_initialization() == InitializationStatus.INITIALIZED:
            return
        # Command: Initialize the gripper (0x0100 register, write A5)
        response = self.client.write_register(
            0x0100, value=mode, unit=self.slave_address
        )
        self._check_response(response)
        start_time = time.time()

        while self.check_initialization() != InitializationStatus.INITIALIZING and (
            time.time() - start_time < 5
        ):
            time.sleep(0.5)
        if wait:
            start_wait = time.time()
            while self.check_initialization() != InitializationStatus.INITIALIZED:
                if self.read_rotation_status() == RotationStatus.BLOCKED:
                    raise ValueError("Gripper is blocked during initialization.")
                if time.time() - start_wait > 60:  # set 60s for time out
                    raise TimeoutError("Gripper initialization timeout.")
                time.sleep(0.5)

    def save_configuration(self):
        # save the configuration
        response = self.client.write_register(0x0300, 1, unit=self.slave_address)
        self._check_response(response)

    def check_initialization(self) -> InitializationStatus:
        # Command: Check if the gripper is initialized (0x0100 register)
        response = self.client.read_holding_registers(
            0x0200, 1, unit=self.slave_address
        )
        self._check_response(response)
        return InitializationStatus(response.registers[0])

    def set_gripper_force(self, force_percentage):
        # Command: Set the gripper force (0x0101 register, value 20-100%)
        if 20 <= force_percentage <= 100:
            response = self.client.write_register(
                0x0101, force_percentage, unit=self.slave_address
            )
            self._check_response(response)
        else:
            raise ValueError("Force must be between 20 and 100 percent.")

    def set_gripper_position(self, position_thousandths):
        if self.check_initialization() != InitializationStatus.INITIALIZED:
            raise RuntimeError("Gripper is not initialized.")
        # Command: Set the gripper position (0x0103 register, value 0-1000‰)
        if 0 <= position_thousandths <= 1000:
            response = self.client.write_register(
                0x0103, position_thousandths, unit=self.slave_address
            )
            self._check_response(response)
        else:
            raise ValueError("Position must be between 0 and 1000.")

    def set_gripper_speed(self, speed_percentage):
        # Command: Set the gripper speed (0x0104 register, value 1-100%)
        if 1 <= speed_percentage <= 100:
            response = self.client.write_register(
                0x0104, speed_percentage, unit=self.slave_address
            )
            self._check_response(response)
        else:
            raise ValueError("Speed must be between 1 and 100 percent.")

    def read_gripper_position(self):
        if self.check_initialization() != InitializationStatus.INITIALIZED:
            raise RuntimeError("Gripper is not initialized.")
        # Command: Read the current position (0x0202 register)
        response = self.client.read_holding_registers(
            0x0202, 1, unit=self.slave_address
        )
        self._check_response(response)
        return response.registers[0]  # Position value in thousandths (0-1000‰)

    def read_gripper_status(self) -> GripperStatus:
        # Command: Read gripper status (0x0201 register)
        response = self.client.read_holding_registers(
            0x0201, 1, unit=self.slave_address
        )
        self._check_response(response)
        return GripperStatus(response.registers[0])

    def set_rotation_speed(self, speed_percentage):
        # Command: Set the rotation speed (0x0501 register, value 1-100%)
        if 1 <= speed_percentage <= 100:
            response = self.client.write_register(
                0x0107, speed_percentage, unit=self.slave_address
            )
            self._check_response(response)
        else:
            raise ValueError("Speed must be between 1 and 100 percent.")

    def set_rotation_force(self, force_percentage):
        # Command: Set the rotation force (0x0108 register, value 1-100%)
        if 20 <= force_percentage <= 100:
            response = self.client.write_register(
                0x0108, force_percentage, unit=self.slave_address
            )
            self._check_response(response)
        else:
            raise ValueError("Force must be between 20 and 100 percent.")

    def set_rotation_angle(self, deg: int, mode: RotationMode = RotationMode.RELATIVE):
        if self.check_initialization() != InitializationStatus.INITIALIZED:
            raise RuntimeError("Gripper is not initialized.")
        if -32768 <= deg <= 32767:
            if deg < 0:
                deg = 0xFFFF + deg + 1  # - integer change to 2's complement
            if mode == RotationMode.ABSOLUTE:
                response = self.client.write_register(
                    0x0105, deg, unit=self.slave_address
                )
            else:
                response = self.client.write_register(
                    0x0109, deg, unit=self.slave_address
                )
            self._check_response(response)
        else:
            raise ValueError("Angle must be between -32768 and 32767 degrees.")

    def stop_rotation(self):
        # Command: Stop the rotation (0x0502 register, write 1)
        response = self.client.write_register(0x0502, 1, unit=self.slave_address)
        self._check_response(response)

    def read_rotation_status(self):
        # Command: Read the rotation status (0x0503 register)
        response = self.client.read_holding_registers(
            0x020B, 1, unit=self.slave_address
        )
        self._check_response(response)
        return RotationStatus(response.registers[0])

    def read_current_angle(self) -> int:
        # Command: Read the current angle (0x020A register)
        response = self.client.read_holding_registers(
            0x0208, 1, unit=self.slave_address
        )
        self._check_response(response)
        return response.registers[0]

    def rotate(
        self,
        deg: int = 0,
        force: int = 30,
        speed: int = 100,
        check_gripper: bool = True,
        mode: RotationMode = RotationMode.RELATIVE,
    ) -> RotationStatus:
        if mode == RotationMode.ABSOLUTE:
            current_deg = self.read_current_angle()
            if current_deg == deg:
                return RotationStatus.REACHED

        # Set rotation force and speed
        self.set_rotation_force(force)
        self.set_rotation_speed(speed)

        try:
            # Perform the rotation
            self.set_rotation_angle(deg, mode=mode)
            start_time = time.time()

            while self.read_rotation_status() != RotationStatus.MOVING and (
                time.time() - start_time < 5
            ):
                if (
                    check_gripper
                    and self.read_gripper_status() != GripperStatus.GRASPED
                ):
                    raise ValueError(
                        f"Gripper status changed to {self.read_gripper_status()} during rotating"
                    )
                time.sleep(0.5)

            while self.read_rotation_status() == RotationStatus.MOVING:
                time.sleep(0.5)
                if (
                    check_gripper
                    and self.read_gripper_status() != GripperStatus.GRASPED
                ):
                    raise ValueError(
                        f"Gripper status changed to {self.read_gripper_status()} during rotating"
                    )
            else:
                if self.read_rotation_status() == RotationStatus.BLOCKED:
                    raise ValueError("Rotation is blocked.")

            return self.read_rotation_status()
        except Exception as e:
            print(f"An error occurred: {e}")
            self.stop_rotation()
            raise

    def grasp(self, speed_percentage=100, force_percentage=100):
        self.set_gripper_speed(speed_percentage)
        self.set_gripper_force(force_percentage)
        self.set_gripper_position(0)

        start_time = time.time()
        while self.read_gripper_status() != GripperStatus.MOVING and (
            time.time() - start_time < 1
        ):
            time.sleep(0.1)

        while self.read_gripper_status() == GripperStatus.MOVING:
            time.sleep(0.1)

    def open_to(self, speed_percentage=100, force_percentage=100, position=1000):
        self.set_gripper_speed(speed_percentage)
        self.set_gripper_force(force_percentage)
        self.set_gripper_position(position)

        start_time = time.time()
        while self.read_gripper_status() != GripperStatus.MOVING and (
            time.time() - start_time < 1
        ):
            time.sleep(0.1)

        while self.read_gripper_status() == GripperStatus.MOVING:
            time.sleep(0.1)

    @staticmethod
    def _check_response(response):
        if response.isError():
            raise ModbusException(f"Modbus Error: {response}")

    def close(self):
        # Close the client connection
        self.stop_rotation()
        self.client.close()


# Example usage
if __name__ == "__main__":
    # Initialize the gripper on COM port, assuming port name is 'COM3' or '/dev/ttyUSB0'
    gripper = GripperController(
        ## Update the port based on your setup ("/dev/tty.usbserial-BG005IB3")
        port="COM9"
    )

    try:
        # Initialize the gripper
        gripper.initialize()
        gripper.save_configuration()
        gripper.open_to(position=925)
        # time.sleep(5)
        # gripper.grasp()
        gripper.rotate(RotationDirection.CLOCKWISE, 180, force=100, check_gripper=False)
        gripper.open_to(position=925)
    except ModbusException as e:
        print(f"An error occurred: {e}")
    finally:
        gripper.close()

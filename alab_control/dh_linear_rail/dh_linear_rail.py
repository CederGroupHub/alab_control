from __future__ import annotations

import time
from enum import Enum

from pymodbus.client.sync import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusException


class RailInitializationStatus(Enum):
    NOT_INITIALIZING = 1
    INITIALIZING = 0


class RailStatus(Enum):
    MOVING = 1
    ARRIVED = 0


class LinearRailController:
    """
    DH Robotics MCE-4G with external encoder
    """

    MAX_DISTANCE = 75  # mm

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

    def load_defaults(self):
        # set up MODBUS control
        self.client.write_register(0x1409, 2, unit=self.slave_address)
        self.client.write_register(0x1108, 2, unit=self.slave_address)
        # set initialization direction
        self.client.write_register(0x0301, 1, unit=self.slave_address)

    def initialize(self, wait=True):
        # write control word
        # move to zero, enable robot
        # 0100 0100 0000 0000
        # run return to zero command
        self.clear_alarm()
        self.set_control_words(0x22)
        time.sleep(0.2)
        start_time = time.time()
        while (
            self.read_initialization_status() != RailInitializationStatus.INITIALIZING
            and (time.time() - start_time < 2)
        ):
            time.sleep(0.5)
        if wait:
            while (
                self.read_initialization_status()
                != RailInitializationStatus.NOT_INITIALIZING
            ):
                if self.read_alarm_code() != 0:
                    raise RuntimeError(
                        f"Alarm detected during initialization. "
                        f"The alarm code is {self.read_alarm_code()}"
                    )
                time.sleep(0.5)

    def get_control_words(self):
        response = self.client.read_holding_registers(0x1605, unit=self.slave_address)
        self._check_response(response)
        return response.registers[0]

    def set_control_words(self, command):
        response = self.client.write_register(0x1605, command, unit=self.slave_address)
        self._check_response(response)

    def get_status(self):
        response = self.client.read_holding_registers(0x1611, unit=self.slave_address)
        self._check_response(response)
        return response.registers[0]

    def read_motion_state(self) -> RailStatus:
        response = self.client.read_holding_registers(0x1611, unit=self.slave_address)
        self._check_response(response)
        state = bin(response.registers[0])[2:]
        return RailStatus(int(state[7]))

    def read_initialization_status(self) -> RailInitializationStatus:
        response = self.client.read_holding_registers(0x1611, unit=self.slave_address)
        self._check_response(response)
        state = bin(response.registers[0])[2:]
        return RailInitializationStatus(int(state[9]))

    def move_to(
        self,
        position,
        max_speed: float = 250,
        max_acceleration: float = 2000,
        wait: bool = True,
    ):
        if position < 0 or position > self.MAX_DISTANCE:
            raise ValueError(f"Position must be between 0 and {self.MAX_DISTANCE} mm.")

        response = self.client.write_register(
            0x1602, int(max_speed * 10), unit=self.slave_address
        )
        self._check_response(response)

        response = self.client.write_register(
            0x1603, int(max_acceleration), unit=self.slave_address
        )
        self._check_response(response)

        response = self.client.write_register(
            0x1600, int(position * 100), unit=self.slave_address
        )
        self._check_response(response)
        time.sleep(0.3)
        # this is moving commands
        self.set_control_words(0x21)
        time.sleep(0.2)
        start_time = time.time()
        while self.read_motion_state() != RailStatus.MOVING and (
            time.time() - start_time < 2
        ):
            time.sleep(0.2)
        if wait:
            while self.read_motion_state() != RailStatus.ARRIVED:
                if self.read_alarm_code() != 0:
                    raise RuntimeError(
                        f"Alarm detected during motion. "
                        f"The alarm code is {self.read_alarm_code()}"
                    )
                time.sleep(0.2)
        self.set_control_words(0x20)

    def read_alarm_code(self):
        response = self.client.read_holding_registers(0x160F, unit=self.slave_address)
        self._check_response(response)
        return response.registers[0]

    def clear_alarm(self):
        self.set_control_words(0x30)

    @staticmethod
    def _check_response(response):
        if response.isError():
            raise ModbusException(f"Modbus Error: {response}")

    def close(self):
        # Close the client connection
        self.client.close()


# Example usage
if __name__ == "__main__":
    # Update the port based on your setup
    rail = LinearRailController(port="COM6")
    rail.initialize(wait=True)
    rail.move_to(70, max_acceleration=50, wait=True)
    rail.move_to(0, max_acceleration=50, wait=True)

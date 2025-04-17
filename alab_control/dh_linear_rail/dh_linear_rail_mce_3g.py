from __future__ import annotations

import time
from enum import Enum

from pymodbus.client.sync import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusException


class InitializationStatus3G(Enum):
    NOT_INITIALIZED = 0
    INITIALIZED = 1
    INITIALIZING = 2


class RailStatus3G(Enum):
    MOVING = 0
    ARRIVED = 1
    BLOCKED = 2


class LinearRailController3G:
    """
    DH Robotics MCE-3G with internal encoder
    """

    MAX_DISTANCE = 50  # mm

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

    def check_initialization(self) -> InitializationStatus3G:
        # Command: Check if the gripper is initialized (0x0100 register)
        response = self.client.read_holding_registers(
            0x0200, 1, unit=self.slave_address
        )
        self._check_response(response)
        return InitializationStatus3G(response.registers[0])

    def read_motion_state(self) -> RailStatus3G:
        response = self.client.read_holding_registers(
            0x0201, 1, unit=self.slave_address
        )
        self._check_response(response)
        return RailStatus3G(response.registers[0])

    @staticmethod
    def _check_response(response):
        if response.isError():
            raise ModbusException(f"Modbus Error: {response}")

    def initialize(self, wait=True):
        # Command: Initialize the gripper (0x0100 register, write A5)
        response = self.client.write_register(0x0100, value=1, unit=self.slave_address)
        self._check_response(response)
        start_time = time.time()

        while self.check_initialization() != InitializationStatus3G.INITIALIZING and (
            time.time() - start_time < 5
        ):
            time.sleep(0.5)
        if wait:
            start_wait = time.time()
            while self.check_initialization() != InitializationStatus3G.INITIALIZED:
                if time.time() - start_wait > 60:  # set 10s for time out
                    raise TimeoutError("Rail initialization timeout.")
                time.sleep(0.5)

    def set_force(self, force_percentage):
        # Command: Set the rotation force (0x0108 register, value 1-100%)
        if 1 <= force_percentage <= 100:
            response = self.client.write_register(
                0x0101, force_percentage, unit=self.slave_address
            )
            self._check_response(response)
        else:
            raise ValueError("Force must be between 20 and 100 percent.")

    def set_speed(self, speed_percentage):
        # Command: Set the rotation speed (0x0501 register, value 1-100%)
        if 1 <= speed_percentage <= 100:
            response = self.client.write_register(
                0x0104, speed_percentage, unit=self.slave_address
            )
            self._check_response(response)
        else:
            raise ValueError("Speed must be between 1 and 100 percent.")

    def set_acceleration(self, acceleration_percentage):
        # Command: Set the rotation acceleration (0x0105 register, value 1-100%)
        if 1 <= acceleration_percentage <= 100:
            response = self.client.write_register(
                0x0105, acceleration_percentage, unit=self.slave_address
            )
            self._check_response(response)
        else:
            raise ValueError("Acceleration must be between 1 and 100 percent.")

    def set_position(self, position_mm: float):
        if self.check_initialization() != InitializationStatus3G.INITIALIZED:
            raise RuntimeError("Gripper is not initialized.")
        if not 0 <= position_mm <= self.MAX_DISTANCE:
            raise ValueError(f"Position must be between 0 and {self.MAX_DISTANCE} mm.")
        position = int(position_mm * 100)  # Convert mm to 0.01 mm
        response = self.client.write_register(0x0103, position, unit=self.slave_address)
        self._check_response(response)

    def get_current_position(self) -> float:
        response = self.client.read_holding_registers(
            0x0202, 1, unit=self.slave_address
        )
        self._check_response(response)
        position = response.registers[0] / 100.0
        return position

    def move_to(
        self,
        position: float,
        force: int = 10,
        max_speed: int = 50,
        max_acceleration: int = 50,
        wait: bool = True,
    ):
        self.set_force(force)
        self.set_speed(max_speed)
        self.set_acceleration(max_acceleration)
        self.set_position(position)
        time.sleep(0.5)
        if wait:
            while (
                self.get_current_position() != round(position, 2)
                or self.read_motion_state() != RailStatus3G.ARRIVED
            ):
                if self.read_motion_state() == RailStatus3G.BLOCKED:
                    raise RuntimeError("Rail is blocked.")
                time.sleep(0.2)

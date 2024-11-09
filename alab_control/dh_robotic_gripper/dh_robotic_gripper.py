import time

from pymodbus.client.sync import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusException

from enum import Enum


class RailInitializationStatus(Enum):
    NOT_INITIALIZED = 0
    INITIALIZED = 1
    INITIALIZING = 2


class RailStatus(Enum):
    MOVING = 0
    ARRIVED = 1


class LinearRailController:
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

        # self.load_defaults()

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
        self.set_control_words(0x22)
        time.sleep(0.2)
        start_time = time.time()
        while self.read_motion_state() != RailStatus.MOVING and (
            time.time() - start_time < 5
        ):
            time.sleep(0.5)
        if wait:
            while self.read_motion_state() != RailStatus.ARRIVED:
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
        return RailStatus(int(state[4]))

    def move_to(
        self,
        position,
        max_speed: float = 250,
        max_acceleration: float = 2000,
        wait: bool = True,
    ):
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
        # this is moving commands
        self.set_control_words(0x21)
        time.sleep(0.5)
        if wait:
            print(self.read_motion_state())
            while self.read_motion_state() != RailStatus.ARRIVED:
                print(1)
                time.sleep(0.1)
        self.set_control_words(0x20)

    def read_alarm_code(self):
        response = self.client.read_holding_registers(0x160F, unit=self.slave_address)
        self._check_response(response)
        return response.registers[0]

    def clear_alarm(self):
        self.set_control_words(0x8)

    @staticmethod
    def _check_response(response):
        if response.isError():
            raise ModbusException(f"Modbus Error: {response}")

    def close(self):
        # Close the client connection
        self.client.close()


# Example usage
if __name__ == "__main__":
    # Initialize the gripper on COM port, assuming port name is 'COM3' or '/dev/ttyUSB0'
    rail = LinearRailController(
        port="/dev/tty.usbserial-BG004CS1"
    )  # Update the port based on your setup
    # print(bin(rail.get_status())[2:][::-1])
    # print(rail.clear_alarm())
    for _ in range(50):
        print(rail.move_to(0))
        print(rail.move_to(50))
    # rail.set_control_words(0x120)
    # rail.set_control_words(0)
    # time.sleep(5)
    # rail.set_control_words(0x4)
    # print(rail.initialize(wait=True))
    # # print(rail.get_state())
    # print(rail.read_alarm_code())
    # print(rail.clear_alarm())

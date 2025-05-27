import logging
import time
from csv import DictReader
from datetime import timedelta
from enum import Enum, unique
from pathlib import Path
from threading import Lock
from typing import NamedTuple, Optional, Dict, Any, Callable, List

from pymodbus.client.sync import ModbusSerialClient

logger = logging.getLogger(__name__)


@unique
class ProgramMode(Enum):
    """
    The current state of machine (if it is running a program)
    """

    RES = 0
    RUN = 1
    HOLD = 2


@unique
class ProgramEndType(Enum):
    """
    What to do when a program ends
    """

    DWELL = 1
    SP2 = 2
    RESET = 3
    CHN = 4


class SegmentFurnace3216P(NamedTuple):
    """
    The arguments for configuring
    """

    dwell_time_min: Optional[int]
    ramp_rate: Optional[float]
    target_temperature: int

    def as_dict(self):
        """
        Returns the dict format of the segment args
        """
        return self._asdict()


class RegisterInfo(NamedTuple):
    name: str
    access: int
    address: int


class FurnaceError(Exception):
    """
    General exception for furnace
    """


class FurnaceReadError(FurnaceError):
    """
    Error raised when failing to read register
    """


class FurnaceWriteError(FurnaceError):
    """
    Error raised when failing to write to register
    """


class FurnaceRegister:
    """
    An abstraction of furnace register
    """

    def __init__(
        self,
        *,
        port: str = "COM3",
        baudrate: int = 9600,
        timeout: Optional[float] = 30.0,
    ):
        """
        Args:
            port: the port of modbus communication
            baudrate: the baud rate for serial communication
            timeout: waiting time for response
        """
        self._port = port
        self._modbus_client = ModbusSerialClient(
            method="rtu", port=port, timeout=timeout, baudrate=baudrate
        )
        self._modbus_client.connect()
        self._mutex_lock = Lock()
        self._register = self.load_register_list()

    @staticmethod
    def load_register_list() -> Dict[str, RegisterInfo]:
        """
        Load register list from file, which includes the address, name, description
        """
        with (Path(__file__).parent / "modbus_addr.csv").open(
            "r", encoding="utf-8"
        ) as f:
            csv_reader = DictReader(f)

            registers = {}

            for registry_entry in csv_reader:
                registers[registry_entry["parameter"]] = RegisterInfo(
                    name=registry_entry["parameter"],
                    access=int(registry_entry["access"]),
                    address=int(registry_entry["address"]),
                )

        return registers

    @property
    def registers(self) -> Dict[str, int]:
        """
        Get all the registers name and address
        """
        return {name: info.address for name, info in self._register.items()}

    def close(self):
        """
        Close the modbus connection
        """
        self._modbus_client.close()

    def __getitem__(self, register_name: str) -> int:
        """
        Read value from register

        Raises:
            KeyError: when the specified register_name is not in the register list
            FurnaceReadError: when the read request was not conducted successfully
        """
        if register_name not in self._register:
            raise KeyError("{} is not a valid register name".format(register_name))
        register_info = self._register[register_name]

        self._mutex_lock.acquire()

        try:
            value = self._modbus_client.read_holding_registers(
                register_info.address, 1, unit=1
            )
            if isinstance(value, Exception):
                raise FurnaceReadError(
                    "Cannot read register {} ({})".format(
                        register_name, register_info.address
                    )
                ) from value

            value = value.registers
        finally:
            time.sleep(0.1)
            self._mutex_lock.release()

        logger.debug("Read register {}: {}".format(register_name, value))
        return value[0]

    def __setitem__(self, register_name: str, value: int):
        """
        Write to register

        Raises:
            KeyError: when the specified register_name is not in the register list
            FurnaceWriteError: when the write request was not conducted successfully
        """
        if register_name not in self._register:
            raise KeyError("{} is not a valid register name".format(register_name))

        if not isinstance(value, int):
            raise TypeError("Expect value as int, but get {}".format(type(value)))
        register_info = self._register[register_name]

        self._mutex_lock.acquire()

        try:
            response = self._modbus_client.write_registers(
                address=register_info.address, values=value, unit=1
            )
        finally:
            time.sleep(0.1)
            self._mutex_lock.release()

        logger.debug("Write to register {}: {}".format(register_name, value))

        if isinstance(response, Exception):
            raise FurnaceWriteError(
                "Fails to write to register: {}".format(register_name)
            ) from response


class FurnaceController(FurnaceRegister):
    """
    Implement higher-level functionalities over 2416 heat controller register
    """

    # temperature that allows for safe operations (in degree C)
    _SAFETY_TEMPERATURE = 100

    @property
    def current_temperature(self) -> int:
        """
        Current temperature in degree C
        """
        temperature = self["INPUT.PVInValue"]
        return temperature

    @property
    def current_target_temperature(self) -> int:
        """
        Current target temperature in degree C
        """
        temperature = self["SP.TargetSP"]
        return temperature

    @property
    def program_mode(self) -> ProgramMode:
        """
        Current program status
        """
        return ProgramMode(self["PROGRAMMER.Status"])

    @program_mode.setter
    def program_mode(self, program_mode: ProgramMode):
        self["PROGRAMMER.Status"] = program_mode.value

    def run_program(self, *segments: SegmentFurnace3216P):
        """
        Set and run the program specified in segments
        """
        self.configure_segments(*segments)
        self.play()
        print(f"{self.get_current_time()} Running Program on port {self._port}")

    def play(self):
        """
        Start to run current program

        Notes:
            We only use the first program for convenience
        """
        if self.is_running():
            raise FurnaceError("A program is still running")
        if self["PROGRAMMER.EndType"] != ProgramEndType.RESET.value:
            self["PROGRAMMER.EndType"] = ProgramEndType.RESET.value
        self.program_mode = ProgramMode.RUN
        logger.info("Current program starts to run")
        time.sleep(5)
        start_time = time.time()
        while not self.is_running():
            current_time = time.time()

            if current_time - start_time > 60:
                raise FurnaceError("Program is not running after 60 seconds")

    def hold_program(self):
        """
        Hold current program
        """
        self.program_mode = ProgramMode.HOLD

    def stop(self):
        self.program_mode = ProgramMode.RES

    def resume(self):
        self.program_mode = ProgramMode.RUN

    def is_running(self) -> bool:
        """
        Whether the program is running
        """
        return (
            self.program_mode == ProgramMode.RUN
            or self.current_temperature >= self._SAFETY_TEMPERATURE
        )

    def _read_segment_i(self, i: int) -> Dict[str, Any]:
        if self["PROGRAMMER.DwellUnits"] != 1:  # 0 is hour, 1 is minute
            self["PROGRAMMER.DwellUnits"] = 1
        if self["SP.RampUnits"] != 0:  # 0 is minute, 1 is hour, 2 is second
            self["SP.RampUnits"] = 0

        return {
            "sp": self[f"PROGRAMMER.SP{i}"],
            "dwell_time": self[f"PROGRAMMER.Dwell{i}"],
            "ramp_rate": self[f"PROGRAMMER.Ramp{i}"] / 10,
        }

    def read_configured_segments(self) -> List[Dict[str, Any]]:
        """
        Read all the configured segments and return them
        """
        segments = []
        for i in range(1, 9):
            segment = self._read_segment_i(i)
            segments.append(segment)

        for j in list(range(8))[::-1]:
            if segments[j]["dwell_time"] or segments[j]["ramp_rate"]:
                return segments[: (j + 1)]
        return []

    def configure_segments(self, *segments: SegmentFurnace3216P):
        """
        Configure a program with several segments

        Notes:
            If there is no end segment in the end, we will add one automatically.
            If there is end segment in the middle, a warning will be thrown.
        """
        _EMPTY_SEGMENT = SegmentFurnace3216P(
            dwell_time_min=None, ramp_rate=None, target_temperature=0
        )
        segments = list(segments) + [_EMPTY_SEGMENT] * (8 - len(segments))
        if len(segments) > 8:
            raise ValueError("The maximum number of segments is 8")

        if self["PROGRAMMER.DwellUnits"] != 0:  # 0 is hour, 1 is minute
            self["PROGRAMMER.DwellUnits"] = 0
        if self["SP.RampUnits"] != 0:  # 0 is minute, 1 is hour, 2 is second
            self["SP.RampUnits"] = 0

        for i, segment in enumerate(segments, 1):
            self[f"PROGRAMMER.SP{i}"] = segment.target_temperature
            self[f"PROGRAMMER.Dwell{i}"] = (
                segment.dwell_time_min if segment.dwell_time_min else 0
            )
            self[f"PROGRAMMER.Ramp{i}"] = (
                int(segment.ramp_rate * 10) if segment.ramp_rate else 0
            )

    def get_current_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


if __name__ == "__main__":
    furnace_register = FurnaceController(port="COM9")
    furnace_register.run_program(
        SegmentFurnace3216P(dwell_time_min=10, ramp_rate=10, target_temperature=30),
        SegmentFurnace3216P(dwell_time_min=10, ramp_rate=20, target_temperature=50),
    )
    time.sleep(10)
    furnace_register.stop()

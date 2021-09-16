import logging
import struct
from csv import DictReader
from enum import Enum, unique
from pathlib import Path
from threading import Lock
from typing import NamedTuple, Optional, Dict, Any, List, Callable

from pyModbusTCP.client import ModbusClient

logger = logging.getLogger(__name__)

_BYTE_ORDER = ">"  # big endian


@unique
class RegisterPermission(Enum):
    RO = 0
    RW = 1


@unique
class RegisterDType(Enum):
    BOOL = "?"
    EINT32 = "i"
    FLOAT32 = "f"
    INT16 = "h"
    INT32 = "i"
    STRING_T = "s"
    TIME_T = "i"
    UINT8 = "B"


@unique
class ProgramMode(Enum):
    """
    The current state of machine (if it is running a program)
    """
    RESET = 1
    RUN = 2
    HOLD = 4
    HOLDBACK = 8
    COMPLETE = 16


@unique
class TimeUnit(Enum):
    """
    The time unit
    """
    SECOND = 0
    MINUTE = 1
    HOUR = 2

    def convert(self, target: "TimeUnit") -> Callable[[float], float]:
        return lambda t: t * 60 ** (self.value - target.value)


@unique
class TemperatureUnit(Enum):
    DEGREE_C = 0
    DEGREE_F = 1
    KELVIN = 2

    def convert(self, target: "TimeUnit") -> Callable[[float], float]:
        if self == target:
            return lambda t: t

        elif self == TemperatureUnit.DEGREE_C:
            if target == TemperatureUnit.KELVIN:
                return lambda t: t + 273.15
            elif target == TemperatureUnit.DEGREE_F:
                return lambda t: t * 1.8 + 32

        elif self == TemperatureUnit.DEGREE_F:
            if target == TemperatureUnit.DEGREE_C:
                return lambda t: (t - 32) * 1.8
            elif target == TemperatureUnit.KELVIN:
                return lambda t: (t + 459.67) * 5 / 9

        elif self == TemperatureUnit.KELVIN:
            if target == TemperatureUnit.DEGREE_C:
                return lambda t: t - 273.15
            elif target == TemperatureUnit.DEGREE_F:
                return lambda t: (t - 273.15) * 1.8 + 32

        raise TypeError("Unsupported type for conversion: {} to {}".format(self, target))


@unique
class SegmentType(Enum):
    """
    Different type of segment
    """
    END = 0
    RAMP_RATE = 1
    RAMP_TIME = 2
    DWELL = 3
    STEP = 4
    CALL = 5


class RegisterInfo(NamedTuple):
    name: str
    description: str
    address: int
    dtype: RegisterDType
    permission: RegisterPermission

    @property
    def real_address(self) -> int:
        return 2 * self.address + 0x8000

    @property
    def dtype_struct(self) -> struct.Struct:
        return struct.Struct("{0}{1}".format(_BYTE_ORDER, self.dtype.value))

    @property
    def bytes(self) -> int:
        return struct.calcsize(self.dtype.value)

    @property
    def register_length(self) -> int:
        """
        Returns the number of registers to store this value
        """
        return (self.bytes + 1) // 2


class WriteError(Exception):
    """
    Error raised when failing to write to register
    """


class FurnaceRegister:
    """
    An abstraction of furnace register
    """

    def __init__(
            self,
            address: str = "192.168.111.222",
            *,
            slave_id: Optional[int] = 1,
            port: int = 502,
            timeout: Optional[float] = 30.,
    ):
        """
        Args:
            address: the ip address to the furnace, default to 192.168.111.222
            slave_id: the slave id of the furnace, default to 0x01
            port: the port of modbus communication
            timeout: waiting time for response
        """
        self._address = address
        self._port = port
        self._slave_id = slave_id
        self._modbus_client = ModbusClient(
            host=self._address,
            port=self._port,
            unit_id=slave_id,
            timeout=timeout,
        )
        self._mutex_lock = Lock()
        self._register = self.load_register_list()

    @staticmethod
    def load_register_list() -> Dict[str, RegisterInfo]:
        """
        Load register list from file, which includes the address, name, description
        """
        with (Path(__file__).parent / "modbus_addr.csv").open("r", encoding="utf-8") as f:
            csv_reader = DictReader(f)

            registers = {}

            for registry_entry in csv_reader:
                registers[registry_entry["parameter"]] = RegisterInfo(
                    name=registry_entry["parameter"],
                    description=registry_entry["description"],
                    dtype=RegisterDType[registry_entry["type"].upper()],
                    address=int(registry_entry["address"]),
                    permission=RegisterPermission[registry_entry["alterability"]],
                )

        return registers

    @property
    def registers(self) -> Dict[str, int]:
        """
        Get all the registers name and address
        """
        return {name: info.address for name, info in self._register.items()}

    def __getitem__(self, register_name: str) -> Any:
        """
        Read value from register

        Raises:
            KeyError: when the specified register_name is not in the register list
        """
        if register_name not in self._register:
            raise KeyError("{} is not a valid register name".format(register_name))
        register_info = self._register[register_name]
        dtype = register_info.dtype

        self._mutex_lock.acquire()

        try:
            # for bool type, we use read_coils
            if dtype == RegisterDType.BOOL:
                value = self._modbus_client.read_coils(register_info.address)[0]
                if value is None:
                    raise KeyError("{} is not a valid register name".format(register_name))
            else:
                reg_list: List[int] = self._modbus_client.read_holding_registers(
                    register_info.address, reg_nb=register_info.register_length
                )
                if None in reg_list:
                    raise KeyError("{} is not a valid register name".format(register_name))

                value = register_info.dtype_struct.unpack(
                    b''.join(struct.pack(">H", reg) for reg in reg_list)
                )[0]
        finally:
            self._mutex_lock.release()

        logger.debug("Read register {}: {}".format(register_name, value))
        return value

    def __setitem__(self, register_name: str, value: Any):
        """
        Write to register

        Raises:
            KeyError: when the specified register_name is not in the register list
            WriteError: when the write request was not conducted successfully
        """
        if register_name not in self._register:
            raise KeyError("{} is not a valid register name".format(register_name))

        register_info = self._register[register_name]
        dtype = register_info.dtype

        if register_info.permission == RegisterPermission.RO:
            raise PermissionError("Register {} is read-only.".format(register_name))

        self._mutex_lock.acquire()

        try:
            # for bool type, we use write_single_coil
            if dtype == RegisterDType.BOOL:
                if not isinstance(value, bool):
                    raise TypeError("{} requires bool value, but get {}".format(register_name, type(value)))
                response = self._modbus_client.write_single_coil(register_info.address, value)
            elif register_info.register_length == 1:  # for 16-bit data type
                # first convert the value to uint16
                packed_value = struct.unpack(">H", register_info.dtype_struct.pack(value))[0]
                response = self._modbus_client.write_single_register(register_info.address, packed_value)
            else:
                # first convert the value to list of uint16
                packed_values = list(struct.unpack(
                    ">" + "H" * register_info.register_length,
                    register_info.dtype_struct.pack(value)
                ))
                response = self._modbus_client.write_multiple_registers(register_info.address, packed_values)
        finally:
            self._mutex_lock.release()

        logger.debug("Write to register {}: {}".format(register_name, value))

        if response is None:
            raise WriteError("Fails to write to register: {}".format(register_name))


class FurnaceController(FurnaceRegister):
    """
    Implement higher-level functionalities over EPC 3016 heat controller register
    """
    @property
    def address(self):
        """
        The address to the modbus server
        """
        return self._address

    def close(self):
        self._modbus_client.close()

    @property
    def current_temperature(self) -> float:
        """
        Current temperature in degree C
        """
        temperature = self["Loop.Main.PV"]
        return temperature

    @property
    def current_target_temperature(self) -> float:
        """
        Current target temperature in degree C
        """
        temperature = self["Loop.Main.SP"]
        return temperature

    @property
    def program_mode(self) -> ProgramMode:
        """
        Current program status
        """
        return ProgramMode(self["Programmer.Run.Mode"])

    def run_program(self):
        """
        Start to run current program

        We only use the first program for convenience
        """
        if self["Programmer.Run.ProgramNumber"] != 1:
            self["Programmer.Run.ProgramNumber"] = 1
        self["Programmer.Setup.Run"] = 1

    def hold_program(self):
        """
        Hold current program
        """
        self["Programmer.Setup.Hold"] = 1

    def reset_program(self):
        """
        Reset current program
        """
        self["Programmer.Setup.Reset"] = 1

    def is_running(self) -> bool:
        """
        Whether the program is running
        """
        return self.program_mode == ProgramMode.RUN

    @property
    def left_time(self) -> int:
        """
        Left time of current running program (program 1)

        if no program is running, return 0
        """
        if not self.is_running():
            return 0
        return self["Programmer.Run.ProgramTimeLeft"]

    @property
    def current_segment(self) -> int:
        """
        Current segment that is running (start from 1)
        """
        return self["Programmer.Run.SegmentNumber"]

    @property
    def configured_segment_num(self) -> int:
        """
        Currently configured segment number
        """
        return self["WorkingProgram.NumConfSegments"]

    def _configure_segment_i(
            self,
            i: int,
            segment_type: SegmentType,
            target_setpoint: Optional[float] = None,
            duration_min: Optional[int] = None,
            ramp_rate_per_sec: Optional[float] = None,
            time_to_target_min: Optional[int] = None,
    ):
        """
        Build segment i with all the parameters given

        Args:
            i: the order of segment
            segment_type: refer to :obj:`SegmentType`
            target_setpoint: the temperature you want to reach in the
                end of the segment (only for RAMP_RATE/RAMP_TIME)
            duration_min: the duration in min (only for DWELL)
            ramp_rate_per_sec: the rate of temperature change per sec
                (degree C / sec) (only for RAMP_RATE)
            time_to_target_min: the time needed to reach the final
                temperate (only for RAMP_TIME)
        """
        if not 1 <= i <= 25:
            raise ValueError("i should be in 1 ~ 25, but get {}.".format(i))

        self["Segment.{}.SegmentType".format(i)] = segment_type.value

        if segment_type is SegmentType.RAMP_RATE:
            if self["Program.1.RampUnit"] != TimeUnit.SECOND.value:
                self["Program.1.RampUnit"] = TimeUnit.SECOND.value
            self["Segment.{}.TargetSetpointt".format(i)] = target_setpoint
            self["Segment.{}.RampRate".format(i)] = ramp_rate_per_sec

        elif segment_type is SegmentType.RAMP_TIME:
            if self["Program.1.DwellUnits"] != TimeUnit.MINUTE.value:
                self["Program.1.DwellUnits"] = TimeUnit.MINUTE.value
            self["Segment.{}.TargetSetpoint".format(i)] = target_setpoint
            self["Segment.{}.TimeToTarget".format(i)] = time_to_target_min

        elif segment_type is SegmentType.DWELL:
            if self["Program.1.DwellUnits"] != TimeUnit.MINUTE.value:
                self["Program.1.DwellUnits"] = TimeUnit.MINUTE.value
            self["Segment.{}.Duration".format(i)] = duration_min

        else:
            if segment_type is not segment_type.END:
                raise NotImplementedError("We have not implemented {} segment type".format(segment_type.name))


if __name__ == '__main__':
    FurnaceRegister()

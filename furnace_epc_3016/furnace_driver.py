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

    @property
    def address(self):
        """
        The address to the modbus server
        """
        return self._address

    def close(self):
        self._modbus_client.close()

    @property
    def current_temperature(self):



if __name__ == '__main__':
    FurnaceRegister()

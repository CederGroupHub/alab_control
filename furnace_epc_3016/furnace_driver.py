from csv import DictReader
from enum import Enum, unique
from pathlib import Path
from threading import Lock
from typing import NamedTuple, Optional, Dict, Any
from pyModbusTCP.client import ModbusClient
import struct

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

    def __getitem__(self, item: str) -> Any:
        if item not in self._register:
            raise KeyError("{} is not a valid register name".format(item))
        register_info = self._register[item]
        return self._modbus_client.read_holding_registers()

    def __setitem__(self, key: str, value: Any):
        ...

    @property
    def address(self):
        """
        The address to the modbus server
        """
        return self._address

    def close(self):
        self._modbus_client.close()


if __name__ == '__main__':
    FurnaceRegister()

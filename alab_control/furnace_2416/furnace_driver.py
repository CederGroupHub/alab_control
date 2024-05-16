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
    OFF = 1
    RUN = 2
    HOLD = 4
    STOP = 16


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
class ProgramEndType(Enum):
    """
    What to do when a program ends
    """
    DWELL = 0
    RESET = 1
    STOP = 2


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

    def __call__(
            self,
            target_setpoint: Optional[float] = None,
            duration: Optional[timedelta] = None,
            ramp_rate_per_min: Optional[float] = None,
            endt: Optional[ProgramEndType] = None,
    ) -> "Segment":
        """
        A convenient method to create a segment configuration
        """
        return Segment(
            segment_type=self,
            target_setpoint=target_setpoint,
            duration=duration,
            ramp_rate_per_min=ramp_rate_per_min,
            endt=endt,
        )


class Segment(NamedTuple):
    """
    The arguments for configuring
    """
    segment_type: SegmentType
    target_setpoint: Optional[float] = None
    duration: Optional[timedelta] = None
    ramp_rate_per_min: Optional[float] = None
    endt: Optional[ProgramEndType] = None

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
            timeout: Optional[float] = 30.,
    ):
        """
        Args:
            port: the port of modbus communication
            baudrate: the baud rate for serial communication
            timeout: waiting time for response
        """
        self._port = port
        self._modbus_client = ModbusSerialClient(method='rtu', port=port, timeout=timeout, baudrate=baudrate)
        self._modbus_client.connect()
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
                    "Cannot read register {} ({})".format(register_name, register_info.address)
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
            raise FurnaceWriteError("Fails to write to register: {}".format(register_name)) from response


class FurnaceController(FurnaceRegister):
    """
    Implement higher-level functionalities over 2416 heat controller register
    """
    # temperature that allows for safe operations (in degree C)
    _SAFETY_TEMPERATURE = 300

    @property
    def current_temperature(self) -> int:
        """
        Current temperature in degree C
        """
        temperature = self["Operator.MAIN.PV"]
        return temperature

    @property
    def current_target_temperature(self) -> int:
        """
        Current target temperature in degree C
        """
        temperature = self["Operator.MAIN.tSP"]
        return temperature

    @property
    def program_mode(self) -> ProgramMode:
        """
        Current program status
        """
        return ProgramMode(self["Operator.RUN.StAt"])

    @program_mode.setter
    def program_mode(self, program_mode: ProgramMode):
        self["Operator.RUN.StAt"] = program_mode.value

    def run_program(self, *segments: Segment):
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
        if self["Operator.RUN.Prg"] != 1:
            self["Operator.RUN.Prg"] = 1
        if self.is_running():
            raise FurnaceError("A program is still running")
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
        self.program_mode = ProgramMode.OFF

    def resume(self):
        self.program_mode = ProgramMode.RUN

    def is_running(self) -> bool:
        """
        Whether the program is running
        """
        return (self.program_mode == ProgramMode.RUN
                or self.current_temperature >= self._SAFETY_TEMPERATURE)

    def _read_segment_i(self, i: int) -> Dict[str, Any]:
        return {
            "segment_type": SegmentType(self["Programmer.Program_01.Segment_{:02}.tYPE".format(i)]),
            "target_setpoint": float(self["Programmer.Program_01.Segment_{:02}.tGt".format(i)]),
            "duration": timedelta(minutes=float(self["Programmer.Program_01.Segment_{:02}.dur".format(i)]) / 10),
            "ramp_rate_per_min": float(self["Programmer.Program_01.Segment_{:02}.rAtE".format(i)]) * 0.1,
            "endt": ProgramEndType(self["Programmer.Program_01.Segment_{:02}.endt".format(i)])
            if self["Programmer.Program_01.Segment_{:02}.endt".format(i)] in set(item.value for item in ProgramEndType)
            else None
        }

    def read_configured_segments(self) -> List[Dict[str, Any]]:
        """
        Read all the configured segments and return them
        """
        current_segment_type: Optional[SegmentType] = None
        configured_segments = []
        while (len(configured_segments) < 25
               and (current_segment_type is None
                    or current_segment_type != SegmentType.END)):
            current_segment = self._read_segment_i(len(configured_segments) + 1)
            current_segment_type = current_segment["segment_type"]
            configured_segments.append(current_segment)
        return configured_segments

    def configure_segments(self, *segments: Segment):
        """
        Configure a program with several segments

        Notes:
            If there is no end segment in the end, we will add one automatically.
            If there is end segment in the middle, a warning will be thrown.
        """
        segments = list(segments)
        if segments[-1].segment_type != SegmentType.END:
            segments.append(Segment(segment_type=SegmentType.END, endt=ProgramEndType.STOP))
        if self["Programmer.Program_01.dwLU"] != TimeUnit.MINUTE.value:
            self["Programmer.Program_01.dwLU"] = TimeUnit.MINUTE.value
        if self["Programmer.Program_01.rmPU"] != TimeUnit.MINUTE.value:
            self["Programmer.Program_01.rmPU"] = TimeUnit.MINUTE.value

        for i, segment_arg in enumerate(segments, start=1):
            if i != len(segments) and segment_arg.segment_type == SegmentType.END:
                logger.warning("Unexpected END segment in the middle of segment ({}/{}), are you sure this is really "
                               "what you want?".format(i, len(segments)))
            self._configure_segment_i(i=i, **segment_arg.as_dict())

    def _configure_segment_i(
            self,
            i: int,
            segment_type: SegmentType,
            target_setpoint: Optional[float] = None,
            duration: Optional[timedelta] = None,
            ramp_rate_per_min: Optional[float] = None,
            endt: Optional[ProgramEndType] = None,
    ):
        """
        Build segment i with all the parameters given

        Args:
            i: the order of segment
            segment_type: refer to :obj:`SegmentType`
            target_setpoint: the temperature you want to reach in the
                end of the segment (only for RAMP_RATE/RAMP_TIME)
            duration: the duration (only for DWELL)
            ramp_rate_per_min: the rate of temperature change per sec
                (degree C / sec) (only for RAMP_RATE)
            endt: ProgramEndType
        """

        def _warn_for_extra_arg(name: str, _locals):
            """
            Warning when some variable should not be set for this segment type
            """
            if name not in _locals:
                raise KeyError("Unexpect name {} in locals.".format(name))
            if _locals[name] is not None:
                value = _locals[name]
                logger.warning("{} should not be set for {}, but get {}.".format(name, segment_type, value))

        if not 1 <= i <= 16:
            raise ValueError("i should be in 1 ~ 16, but get {}.".format(i))

        self["Programmer.Program_01.Segment_{:02}.tYPE".format(i)] = segment_type.value

        if segment_type is SegmentType.RAMP_RATE:
            self["Programmer.Program_01.Segment_{:02}.tGt".format(i)] = int(target_setpoint)
            self["Programmer.Program_01.Segment_{:02}.rAtE".format(i)] = int(ramp_rate_per_min * 10)
            _warn_for_extra_arg("duration", locals())
            _warn_for_extra_arg("endt", locals())

        elif segment_type is SegmentType.RAMP_TIME:
            self["Programmer.Program_01.Segment_{:02}.tGt".format(i)] = int(target_setpoint)
            self["Programmer.Program_01.Segment_{:02}.dur".format(i)] = int(duration.total_seconds() / 6)
            _warn_for_extra_arg("ramp_rate_per_min", locals())
            _warn_for_extra_arg("endt", locals())

        elif segment_type is SegmentType.DWELL:
            self["Programmer.Program_01.Segment_{:02}.dur".format(i)] = int(duration.total_seconds() / 6)
            _warn_for_extra_arg("target_setpoint", locals())
            _warn_for_extra_arg("ramp_rate_per_min", locals())
            _warn_for_extra_arg("endt", locals())

        elif segment_type is SegmentType.STEP:
            self["Programmer.Program_01.Segment_{:02}.tGt".format(i)] = int(target_setpoint)
            _warn_for_extra_arg("ramp_rate_per_min", locals())
            _warn_for_extra_arg("duration", locals())
            _warn_for_extra_arg("endt", locals())

        elif segment_type is SegmentType.END:
            self["Programmer.Program_01.Segment_{:02}.endt".format(i)] = endt.value

            _warn_for_extra_arg("target_setpoint", locals())
            _warn_for_extra_arg("ramp_rate_per_min", locals())
            _warn_for_extra_arg("duration", locals())

        else:
            raise NotImplementedError(
                "We have not implemented {} segment type".format(segment_type.name)
            )

        logger.info("Set segment {} with {}".format(i, dict(
            segment_type=segment_type,
            target_setpoint=target_setpoint,
            duration=duration,
            ramp_rate_per_min=ramp_rate_per_min,
            endt=endt.value if endt is not None else endt,
        )))

    def get_current_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

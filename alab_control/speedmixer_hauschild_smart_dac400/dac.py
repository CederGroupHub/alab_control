from __future__ import annotations

import logging

from retry import retry
import time
from typing import Literal
from serial import Serial
from serial.serialutil import SerialException

logging.basicConfig(level=logging.DEBUG)


class DACError(Exception):
    pass


class DACDriver:
    def __init__(self, com_port: str, timeout: int = 1):
        self.com_port = com_port
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    @retry(SerialException, tries=10, delay=0.2)
    def send_command(
        self, mode: Literal["read", "write"], code: int, value: int | None = None
    ):
        if mode == "read":
            address = b"\x20"
            if value is not None:
                raise ValueError("Value must be None when mode is 'read'.")
        elif mode == "write":
            address = b"\x21"
            if value is None:
                raise ValueError("Value must not be None when mode is 'write'.")
        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'read' or 'write'.")

        if value is not None and not isinstance(value, int):
            raise ValueError("Value must be an integer.")

        # unpack the code as ascii
        # if the code is an integer, convert it to a string with 2 digits (padded by 0)
        code = f"{code:02d}"
        code = code.encode("ascii")

        if value is not None:
            value = f"{value:05d}"
        else:
            value = "00000"

        value = value.encode("ascii")
        # combine the command
        # It should be:
        # 04H address 02H code value 03H 05H
        # 04H: start byte
        # address: the address of the device
        # 02H: command byte
        # 02H: start of text
        # code: the code
        # value: the value
        # 03H: end of text
        # 05H: end byte

        command = b"\x04" + address + b"\x02" + code + value + b"\x03\x05"
        # send the command
        with Serial(
            self.com_port,
            baudrate=19200,
            parity="N",
            bytesize=8,
            stopbits=1,
            timeout=self.timeout,
        ) as ser:
            ser.write(command)
            ser.flush()
            time.sleep(0.2)
            response = ser.read_all()
            while response == b"":
                time.sleep(0.2)
                response = ser.read_all()
            time.sleep(0.2)
            # the frame of the response should be:
            # 02H code value 03H
            # 02H: start of text
            # code: the code (2 bytes)
            # value: the value (8 bytes)
            # 03H: end of text

            # unpack the response
            try:
                code = int(response[1:3])
                value = int(response[3:-1])
            except ValueError as e:
                raise DACError("Invalid response.") from e
            self.logger.debug(
                f"Received response: {response}. Code: {code}, Value: {value}"
            )
            if not code:
                if value == 1:
                    raise DACError(
                        "Mixer is not running remote "
                        "program 0 (can occur if setting speed)."
                    )
                elif value == 2:
                    raise DACError("No valid code.")
                elif value == 3:
                    raise DACError("Program is still running (Run=1)")
            return code, value

    def init_drive(self):
        return self.send_command("write", 9, 1)[1] == 1

    def start(self) -> bool:
        return self.send_command("write", 11, 1)[1] == 1

    def stop(self) -> bool:
        return self.send_command("write", 12, 1)[1] == 1

    def get_acc_ramp(self) -> int:
        return self.send_command("read", 14)[1]

    def set_acc_ramp(self, acc_ramp: int) -> bool:
        if acc_ramp < 5 or acc_ramp > 30:
            raise ValueError("The acceleration ramp must be between 5 and 30.")
        return self.send_command("write", 14, acc_ramp)[1] == acc_ramp

    def get_dec_ramp(self) -> int:
        return self.send_command("read", 15)[1]

    def set_dec_ramp(self, dec_ramp: int) -> bool:
        if dec_ramp < 5 or dec_ramp > 30:
            raise ValueError("The deceleration ramp must be between 5 and 30.")
        return self.send_command("write", 15, dec_ramp)[1] == dec_ramp

    def get_speed(self) -> int:
        return self.send_command("read", 16)[1]

    def set_speed(self, speed: int) -> bool:
        if speed < 0 or speed > 2500:
            raise ValueError("The speed must be between 0 and 2500.")
        return self.send_command("write", 16, speed)[1] == speed

    def is_ready(self) -> bool:
        code, value = self.send_command("read", 18)
        return value == 1

    def is_running(self) -> bool:
        code, value = self.send_command("read", 19)
        if error := self.get_error():
            raise DACError("Detect error with code: {}".format(error))
        return value == 1

    def get_error(self):
        return self.send_command("read", 20)[1]

    def clear_error(self):
        self.send_command("write", 20, 1)


class HauschildDAC400:
    def __init__(self, com_port: str, timeout: int = 1, homing_retries: int = 5):
        self.dac = DACDriver(com_port=com_port, timeout=timeout)
        self.homing_retries = homing_retries

    def stop(self):
        for i in range(10):
            if self.dac.get_error():
                self.dac.clear_error()
                time.sleep(0.1)
                self.dac.set_speed(0)
                time.sleep(0.1)
            self.dac.stop()
            time.sleep(1)

        time.sleep(10)
        if self.dac.get_error():
            raise DACError(
                "Could not stop the device. Get error code: {}".format(
                    self.dac.get_error()
                )
            )

    def run_program(self, speed: int, time_sec: int):
        try:
            self.dac.set_speed(speed)
            self.dac.set_acc_ramp(10)
            self.dac.set_dec_ramp(10)
            self.dac.start()
            time.sleep(0.5)

            for _ in range(10):
                if self.dac.is_running():
                    break
                time.sleep(1)

            start = time.time()
            while self.dac.is_running():
                time.sleep(0.1)
                if time.time() - start > time_sec:
                    break
            else:
                raise DACError("The program did not finish properly.")
            self.dac.set_speed(0)
            time.sleep(5)
            self.stop()
            start = time.time()
            while self.dac.is_running():
                time.sleep(0.5)
                if time.time() - start > 60:
                    raise DACError("The program did not finish properly.")
        finally:
            self.stop()

    def homing(self):
        for _ in range(self.homing_retries):
            if self.dac.init_drive():
                time.sleep(0.5)
                for i in range(50):
                    if self.dac.is_running():
                        break
                    time.sleep(0.1)
                for i in range(500):
                    if not self.dac.is_running():
                        break
                    time.sleep(0.1)
                break
        else:
            raise DACError("Could not home the device.")
        # for some reason, the device is not ready the not is running detected
        time.sleep(5)

    def is_running(self):
        return self.dac.is_running()


if __name__ == "__main__":
    dac = HauschildDAC400(com_port="/dev/tty.usbserial-B0029CTO")
    dac.homing()
    # dac.dac.init_drive()
    # # time.sleep(10)
    # # #
    # while 1:
    #     print(dac.dac.is_ready())
    #     if dac.dac.is_ready():
    #         break
    # dac.dac.set_speed(400)
    # dac.dac.start()
    # time.sleep(5)
    # dac.stop()
    # # print(dac.dac.is_ready())

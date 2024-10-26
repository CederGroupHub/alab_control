from __future__ import annotations

import re
import socket
import time
from enum import IntEnum


class DoorMode(IntEnum):
    CLOSE_ALL = 0
    OPEN_RIGHT = 1
    OPEN_LEFT = 2
    OPEN_ALL = 4


class DoorStatus(IntEnum):
    CLOSE_ALL = 0
    OPEN_RIGHT = 1
    OPEN_LEFT = 2
    OPEN_ALL = 4
    ERROR = 8
    INTERMEDIATE = 9


class BalanceError(Exception):
    pass


class MettlerToledoAutoBalance:
    def __init__(self, host: str, port: int, timeout: int = 120):
        self.host = host
        self.port = port
        self.timeout = timeout

    def send_request(self, request: str):
        request += "\r\n"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))
            s.settimeout(self.timeout)
            s.send(request.encode("ascii"))
            time.sleep(1)
            result = s.recv(2048).decode("ascii")

            if re.search(r"^\w+ I", result):
                raise BalanceError("Command understood but currently not executable.")
            elif re.search(r"^\w+ L", result):
                raise BalanceError("Command understood but not executable.")
            elif re.search(r"^ES", result):
                raise BalanceError("Command not understood.")
            else:
                return result

    def move_door(self, mode: DoorMode):
        return self.send_request(f"WS {mode}")

    def get_door_status(self) -> DoorStatus:
        response = self.send_request("WS")
        print(response)
        return DoorStatus(int(response[2]))

    def set_target_weight_tolerance(self, target_weight_g: float | None = None,
                                    tolerance_pos_percent: float | None = None,
                                    tolerance_neg_percent: float | None = None):
        if target_weight_g is not None:
            target_weight_g = round(target_weight_g, 5)
            self.send_request(f"A10 0 {target_weight_g} g")
        if tolerance_pos_percent is not None:
            tolerance_pos_percent = round(tolerance_neg_percent, 3)
            self.send_request(f"A10 1 {tolerance_pos_percent} %")
        if tolerance_neg_percent is not None:
            tolerance_neg_percent = round(tolerance_neg_percent, 3)
            self.send_request(f"A10 2 {tolerance_neg_percent} %")

    def get_target_weight_tolerance(self) -> dict[str, float | str]:
        response = self.send_request("A10")
        result = re.findall(
            r"A10 [AB] [012] ([0-9.]+) ([a-z%]+)", response
        )

        parsed_result = {
            "target_weight_g": float(result[0][0])
            if result[0][1] == "g" else f"{result[0][0]} {result[0][1]}",
            "tolerance_pos_percent": float(result[1][0])
            if result[1][1] == "%" else f"{result[1][0]} {result[1][1]}",
            "tolerance_neg_percent": float(result[2][0])
            if result[2][1] == "%" else f"{result[2][0]} {result[2][1]}"
        }
        return parsed_result


if __name__ == '__main__':
    auto_balance = MettlerToledoAutoBalance("192.168.1.10", port=8001)
    # auto_balance.set_target_weight_tolerance(
    #     target_weight_g=0.231432424,
    #     tolerance_pos_percent=0.5,
    #     tolerance_neg_percent=0.1
    # )
    # print(auto_balance.get_target_weight_tolerance())
    print(auto_balance.send_request("I0"))

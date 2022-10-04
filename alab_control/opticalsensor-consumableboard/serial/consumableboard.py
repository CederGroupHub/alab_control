import re
from threading import Thread
from time import time
import serial


class ConsumableBoard:
    BAUDRATE = 9600
    TIMEOUT = 2
    INTERVAL = 1  # seconds between queries to the arduino

    def __init__(self, port: str, rows: int, columns: int):
        self.rows = rows
        self.columns = columns
        self.__available = [[False for _ in range(columns)] for _ in range(rows)]
        self.port = port

    ## Arduino communication
    def connect(self):
        self._arduino = serial.Serial(self.port, self.BAUDRATE, timeout=self.TIMEOUT)
        self.listener_thread = self.start_listener_worker()
        self._request_all_updates()

    def disconnect(self):
        if hasattr(self, "_arduino"):
            self._arduino.close()
            del self._arduino

    def _request_all_updates(self):
        self._arduino.write("a\n".encode("utf-8"))  # request _a_ll updates

    def _request_update(self, row: int, col: int):
        self._arduino.write(
            f"s {row} {col}\n".encode("utf-8")
        )  # request _s_ingle update at row,column.

    def _parse_incoming_line(self, data: str):
        row = int(re.search(r"row=(\d+)", data).group(1))
        col = int(re.search(r"col=(\d+)", data).group(1))
        state = (
            int(re.search(r"state=(\d+)", data).group(1)) == 1
        )  # 1 = filled, 0 = empty
        self.__available[row][col] = state

    def _start_listener(self):
        listener_thread = Thread(target=self.__listener, daemon=True)
        listener_thread.start()
        return listener_thread

    def __listener(self):
        while True:
            if self._arduino.in_waiting > 0:
                data = self._arduino.readline().decode("utf-8").strip()
                self._parse_incoming_line(data)
            time.sleep(self.INTERVAL)

    ## User-facing
    @property
    def num_available(self):
        return sum([sum(row) for row in self.__available])

    @property
    def available(self):
        return self.__available

    def is_available(self, row: int, column: int):
        return self.available[row][column]

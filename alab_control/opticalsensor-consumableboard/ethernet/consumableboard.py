from lib2to3.pytree import Base
from alab_control._base_arduino_device import BaseArduinoDevice
import re
from threading import Thread
from time import time

#TODO catch 404/bad connection from arduino over ethernet

class ConsumableBoard(BaseArduinoDevice):
    TIMEOUT = 2
    INTERVAL = 1  # seconds between queries to the arduino
    ENDPOINTS = {
        "update": "/update",
    }

    def __init__(self, ip_address: str, port: int, rows: int, columns: int):
        super(self, ConsumableBoard).__init__(ip_address, port)
        self.rows = rows
        self.columns = columns
        self.__available = [[False for _ in range(columns)] for _ in range(rows)]
        self._start_listener()

    def _update(self):
        reply = self.send_request(self.ENDPOINTS["update"], method="GET")
        for i, row in enumerate(reply["filled"]):
            for j, state in enumerate(row):
                self.__available[i][j] = state == 1  # 1 == filled == available

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
            self._update()
            time.sleep(self.INTERVAL)

    ## User-facing
    @property
    def num_available(self):
        return sum([sum(row) for row in self.__available])

    @property
    def available(self):
        # TODO do we want to use (row,col) or incremental indexing?
        return [
            (i, j)
            for i, row in enumerate(self.__available)
            for j, state in enumerate(row)
            if state
        ]

        return avail

    def is_available(self, row: int, column: int):
        return self.__available[row][column]

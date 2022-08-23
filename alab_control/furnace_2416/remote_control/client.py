import requests
import time

from alab_control.furnace_2416.furnace_driver import FurnaceError, ProgramMode, Segment


class BoxFurnaceRemoteClient:
    update_window = (
        1  # wont update if the most recent update was within this window (seconds)
    )

    def __init__(self, furnace_name: str, address: str, port: str):
        self.furnace_name = furnace_name
        self.__check_if_valid_furnace(
            furnace_name=furnace_name, address=address, port=port
        )
        self.api_root = f"http://{address}:{port}/furnace_name/"
        self.last_updated_at = 0

    def __check_if_valid_furnace(
        self, furnace_name: str, address: str, port: str
    ) -> bool:
        url = "http://" + address + ":" + port + "/available_furnaces"
        response = requests.get(url=url).json()
        if furnace_name not in response.get("available_furnaces", []):
            raise Exception(
                f"{furnace_name} is not valid to connect to BoxFurnaceServer!"
            )

    def get_status(self):
        now = time.time()
        if now - self.last_updated_at > self.update_window:
            url = self.api_root + "status"
            status = requests.get(url=url).json()
            self._is_running = status["is_running"]
            self._current_temperature = status["current_temperature"]
            self._current_target_temperature = status["current_target_temperature"]
            self._program_mode = ProgramMode(status["program_mode"])
            self.last_updated_at = now

    @property
    def is_running(self):
        self.get_status()
        return self._is_running

    @property
    def current_temperature(self):
        self.get_status()
        return self._current_temperature

    @property
    def current_target_temperature(self):
        self.get_status()
        return self._current_target_temperature

    @property
    def program_mode(self):
        self.get_status()
        return self._program_mode

    def run_program(self, *segments:Segment):
        url = self.api_root + "run_program"
        response = requests.post(url=url, json={
            "segments":[seg.as_dict() for seg in segments]
        })
        if response["status"] != "success":
            raise FurnaceError(f"Error during POST to run program on remote box furnace by name of {self.furnace_name}: {response}")

    def stop(self):
        
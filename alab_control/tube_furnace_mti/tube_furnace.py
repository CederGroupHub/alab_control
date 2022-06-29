import time
from pathlib import Path, PureWindowsPath
from subprocess import Popen
from typing import Union, Optional, Dict

import requests
import win32com.client


class FlangeError(Exception):
    ...


class TubeFurnace:
    URLS = {
        "autostart": "/auto_start",
        "autostop": "/auto_stop",
        "flange": "/flange",
        "read_data": "/read_data",
        "write_data": "/write_data",
    }

    def __init__(self,
                 exe_path: Union[str, Path],
                 main_vi_name: str,
                 temperature_vi_name: str,
                 active_x_name: str,
                 base_url: str):
        if isinstance(exe_path, str):
            exe_path = Path(exe_path)
        self.exe_path: Path = exe_path
        self.main_vi_name = main_vi_name
        self.temperature_vi_name = temperature_vi_name
        self.active_x_name = active_x_name
        self.base_url = base_url

        self._process: Optional[Popen] = None
        self._labview = None
        self._main_vi = None
        self._temperature_vi = None
        self.start_exe()
        time.sleep(5)
        self._init()

    def start_exe(self):
        """
        Start the Labview executable binary in another process.
        """
        self._process = Popen(self.exe_path.as_posix())

    def _init(self):
        """
        Get the reference of the labview process
        """
        self._labview = win32com.client.Dispatch(self.active_x_name)
        # the file separator must be \ instead of /
        # so we use replace to change the file separator
        self._main_vi = self._labview.getvireference((self.exe_path / self.main_vi_name).as_posix().replace("/", "\\"))
        self._temperature_vi = self._labview.getvireference(
            (self.exe_path / "AI BUS Driver" / self.temperature_vi_name).as_posix().replace("/", "\\"))

    def read_variable_from_main_vi(self, name):
        return self._main_vi.getcontrolvalue(name)

    def write_variable_to_main_vi(self, name, value):
        self._main_vi.setcontrolvalue(name, value)

    def read_variable_from_temperature_vi(self, name):
        return self._temperature_vi.getcontrolvalue(name)

    def write_variable_to_temperature_vi(self, name, value):
        self._temperature_vi.setcontrolvalue(name, value)

    def autostart(self):
        url = self.base_url + self.URLS["autostart"]
        response = requests.get(url)
        response.raise_for_status()
        time.sleep(1)

    def sample_loaded(self):
        self._main_vi.setcontrolvalue('Sample change completed', True)  # Set Input 1

    def start_program(self):
        self.autostart()
        self.sample_loaded()

    def open_door(self, safety_open_temperature=100, pressure_min=90000, pressure_max=110000):
        if self.PV > safety_open_temperature or self.pressure > pressure_max or self.pressure < pressure_min:
            return False
        url = self.base_url + self.URLS["flange"]
        response = requests.get(url, params={"action": "WriteFlangeOpen"})
        response.raise_for_status()
        time.sleep(30)
        if not self.flange_state:
            raise FlangeError("Cannot open the door")

    def close_door(self):
        url = self.base_url + self.URLS["flange"]
        response = requests.get(url, params={"action": "WriteFlangeClose"})
        response.raise_for_status()
        time.sleep(30)
        if not self.flange_state:
            raise FlangeError("Cannot close the door")

    def pause_door(self):
        url = self.base_url + self.URLS["flange"]
        response = requests.get(url, params={"action": "WriteFlangeStop"})
        response.raise_for_status()

    @property
    def flange_state(self):
        return self.read_variable_from_main_vi("Flange state")

    def read_heating_profile(self):
        url = self.base_url + self.URLS["read_data"]
        response = requests.get(url)
        response.raise_for_status()
        time.sleep(15)
        data = {}
        for i in range(1, 11):
            for j in ("C", "T"):
                name = f"{j}{i:02}"
                data[name] = self.read_variable_from_temperature_vi(name)
        return data

    def write_heating_profile(self, setpoints: Dict[str, int]):
        url = self.base_url + self.URLS["write_data"]
        response = requests.post(url, data=setpoints)
        response.raise_for_status()
        time.sleep(5)

    @property
    def PV(self):
        return self.read_variable_from_main_vi("PV")

    @property
    def SV(self):
        return self.read_variable_from_main_vi("SV")

    @property
    def pressure(self):
        return self.read_variable_from_main_vi("Vacuum degree")


    @property
    def flow_PV(self):
        return self.read_variable_from_main_vi("Real time flow")

    @property
    def flow_SV(self):
        return self.read_variable_from_main_vi("Set flow")

    @property
    def autostate(self):
        return self.read_variable_from_main_vi("Autostate")


if __name__ == '__main__':

    tube_furnace_2 = TubeFurnace(
        exe_path=r"C:\Users\Yuxing Fei\projects\OTF-1200X-ASD\builds\2\Automatic loading furnace_2.exe",
        main_vi_name="Automatic loading tube furnace_2.vi",
        temperature_vi_name="AIbus2.vi",
        active_x_name="AutomaticLoadingFurnace2.Application",
        base_url="http://localhost:8002/Automatic_loading_2",
    )
    print(tube_furnace_2.read_heating_profile())
    tube_furnace_2.write_heating_profile({"C01": 1})
    print(tube_furnace_2.read_heating_profile())

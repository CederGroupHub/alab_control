import re
import time
from enum import Enum
from pathlib import Path
from subprocess import Popen
from typing import Optional, Dict, Any

import requests
import win32com.client


class FlangeError(Exception):
    """
    Error about the flange of tube furnace
    """
    ...


class TubeFurnaceState(Enum):
    """
    Current state of tube furnace
    """
    PAUSED = -1
    WAITING_FOR_SAMPLE = -2
    STOPPED = 0
    STEP1 = 1
    STEP2 = 2
    STEP3 = 3
    STEP4 = 4
    STEP5 = 5
    STEP6 = 6


class TubeFurnace:
    """
    Driver code for MTI OTF-1200X-ASD Automatic Tube Furnace

    In this class, we use custom API exposed from the LabView User Interface and ActiveX framework
    to read/write data.
    """

    URLS = {
        "autostart": "/auto_start",
        "autostop": "/auto_stop",
        "flange": "/flange",
        "read_data": "/read_data",
        "write_data": "/write_data",
    }

    def __init__(self, furnace_index: int):
        """
        Args:
            furnace_index: the index of tube furnace, should be the same as the number in the real tube furnace
        """
        if furnace_index < 1 or furnace_index > 4:
            raise ValueError("Currently only support 4 furnaces")
        self._furnace_index = furnace_index
        self.exe_path: Path = Path(__file__).parent / "tube_furnace_MTI" / "builds" / \
                              f"{furnace_index}" / f"Automatic loading furnace_{furnace_index}.exe"
        self.main_vi_name = f"Automatic loading tube furnace_{furnace_index}.vi"
        self.temperature_vi_name = f"AIbus{furnace_index}.vi"
        self.active_x_name = f"AutomaticLoadingFurnace{furnace_index}.Application"
        self.base_url = f"http://localhost:800{furnace_index + 4}/Automatic_loading_{furnace_index}"

        self._process: Optional[Popen] = None
        self._labview = None
        self._main_vi = None
        self._temperature_vi = None

        # start the tube furnace software,
        # if it has already started, it will do nothing
        self._start_exe()
        time.sleep(5)
        self._init()

    @property
    def furnace_index(self) -> int:
        return self._furnace_index

    def _start_exe(self):
        """
        Start the Labview executable binary in another process.
        """
        self._process: Popen = Popen(self.exe_path.as_posix())

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

    def read_variable_from_main_vi(self, name: str) -> Any:
        """
        Read a control value in the main interface

        Args:
            name: the label property of a controller/indicator
        """
        return self._main_vi.getcontrolvalue(name)

    def write_variable_to_main_vi(self, name: str, value: Any):
        """
        Write a control value to the main interface
        Args:
            name: the label property of a controller
            value: the value you want to write
        """
        self._main_vi.setcontrolvalue(name, value)

    def read_variable_from_temperature_vi(self, name):
        """
        Read a control value in the temperature control page

        Args:
            name: the label property of a controller/indicator
        """
        return self._temperature_vi.getcontrolvalue(name)

    def write_variable_to_temperature_vi(self, name, value):
        """
        Write a control value to the temperature control page
        Args:
            name: the label property of a controller
            value: the value you want to write
        """
        self._temperature_vi.setcontrolvalue(name, value)

    def autostart(self):
        """
        Click the autostart button in the main interface.

        The furnace will enter autorunning mode and wait for sample loading.
        If it is clicked for multiple times, nothing will happen.
        """
        url = self.base_url + self.URLS["autostart"]
        response = requests.get(url)
        response.raise_for_status()
        time.sleep(1)

    def sample_loaded(self):
        """
        Indicate the sample is loaded. If the machine is in autorunning mode,
        it will go from "Waiting for sample loading" to step 1.
        """
        self._main_vi.setcontrolvalue('Sample change completed', True)  # Set Input 1

    def start_program(self):
        """
        Start the program. The machine will start to run and we assume the sample has been loaded.
        """
        self.autostart()
        time.sleep(1)
        self.sample_loaded()
        time.sleep(2)

    def open_door(self, safety_open_temperature=100, pressure_min=90000, pressure_max=110000, timeout=120):
        """
        Open the flange when some conditions are met. If these conditions (temperature & pressure) are not met,
        this method will return False. If timeout is reached and the furnace still does not start to open,
        a ``FlangeError`` will be raised.

        Args:
            safety_open_temperature: Highest temperature to open the door in degree C
            pressure_min: minimum pressure to open the door in Pa
            pressure_max: maximum pressure to open the door in Pa
            timeout: timeout in seconds

        Returns:
            True if the door opens successfully; False if some conditions has not been met.
        """
        if self.PV > safety_open_temperature or self.pressure > pressure_max or self.pressure < pressure_min:
            return False
        url = self.base_url + self.URLS["flange"]
        response = requests.get(url, params={"action": "WriteFlangeOpen"})
        response.raise_for_status()
        seconds = 0
        while seconds <= timeout:
            if not self.flange_state:
                time.sleep(40)
                return True
            time.sleep(1)
            seconds += 1
        raise FlangeError("Timeout: cannot open the door")

    def close_door(self, timeout=60):
        """
        Close the door. If the door cannot be closed in ``timeout`` seconds, a ``FlangeError`` will be raised.

        Args:
            timeout: max time to close the door

        Returns:
            True if the door closes successfully.
        """
        url = self.base_url + self.URLS["flange"]
        response = requests.get(url, params={"action": "WriteFlangeClose"})
        response.raise_for_status()
        seconds = 0
        while seconds < timeout:
            if self.flange_state:
                return True
            time.sleep(1)
            seconds += 1
        raise FlangeError("Timeout: cannot close the door")

    def pause_door(self):
        """
        Stop door motion
        Returns:
            True if the door is paused successfully.
        """
        url = self.base_url + self.URLS["flange"]
        response = requests.get(url, params={"action": "WriteFlangeStop"})
        response.raise_for_status()
        return True

    @property
    def flange_state(self):
        """
        Indicates if the door is closed.
        Returns:
            True if the door is fully closed.
        """
        return self.read_variable_from_main_vi("Flange state")

    def read_heating_profile(self) -> Dict[str, Any]:
        """
        Read first 10 segments of the heating profile.

        Returns:
            A dict like {"C01": time, "T01": temperature, ...}
        """
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
        """
        Write heating profile to the machine. Currently we stopped

        Args:
            setpoints: A dict like {"C01": time, "T01": temperature, ...}
        """
        url = self.base_url + self.URLS["write_data"]
        response = requests.get(url, params=setpoints)
        response.raise_for_status()
        time.sleep(5)
        max_temperature = int(max([v for k, v in setpoints.items() if k.startswith("C")]) * 0.9)
        self.write_variable_to_main_vi("Maximum loop temperature", max_temperature)

    @property
    def PV(self):
        """
        Current temperature in the furnace (degree C)
        """
        return self.read_variable_from_main_vi("PV")

    @property
    def SV(self):
        """
        Current set temperature in the furnace (degree C)
        """
        return self.read_variable_from_main_vi("SV")

    @property
    def pressure(self):
        """
        Current pressure in the furnace (Pa)
        """
        return self.read_variable_from_main_vi("Vacuum degree")

    @property
    def flow_PV(self):
        """
        Current flow rate in the furnace
        """
        return self.read_variable_from_main_vi("Real time flow")

    @property
    def flow_SV(self):
        """
        Current set flow rate in the furnace
        """
        return self.read_variable_from_main_vi("Set flow")

    @property
    def state(self) -> TubeFurnaceState:
        """
        Get the state of the furnace
        """
        autostate = self.read_variable_from_main_vi("Autostate")
        if "stopped" in autostate:
            return TubeFurnaceState.STOPPED
        elif "waiting" in autostate:
            return TubeFurnaceState.WAITING_FOR_SAMPLE
        elif "paused" in autostate:
            return TubeFurnaceState.PAUSED
        else:
            return TubeFurnaceState(re.search(r"\d+", autostate).group())


if __name__ == '__main__':
    tube_furnace_2 = TubeFurnace(furnace_index=2)

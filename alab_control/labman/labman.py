from contextlib import contextmanager
from enum import Enum, auto
from multiprocessing.sharedctypes import Value
import requests
from threading import Thread
import time
from typing import Dict
from molmass import Formula
from pathlib import Path

from alab_control.labman.error import *


class Powder:
    def __init__(self, name: str, composition: str):
        self.name = name
        self.formula = Formula(composition)

    def __eq__(self, other):
        if not isinstance(other, Powder):
            return False
        return self.formula._elements == other.formula._elements


class InputFile:
    def __init__(
        self,
        powder_dispenses=Dict[Powder, float],
        heating_duration: int = 300,
        ethanol_volume: int = 10000,
        transfer_volume: int = 10000,
        mixer_speed: int = 2000,
        mixer_duration: int = 900,
        min_transfer_mass: int = 5,
        replicates: int = 1,
    ):
        if transfer_volume > ethanol_volume:
            raise ValueError("`transfer_volume` must be <= `ethanol_volume`!")

        self.powder_dispenses = powder_dispenses
        self.heating_duration = heating_duration
        self.ethanol_volume = ethanol_volume
        self.transfer_volume = transfer_volume
        self.mixer_speed = mixer_speed
        self.mixer_duration = mixer_duration
        self.min_transfer_mass = min_transfer_mass
        self.replicates = replicates

    def to_json(self, position: int):
        """
        Example:
            {
            "CrucibleReplicates": 2,
            "HeatingDuration": 300,
            "EthanolDispenseVolume": 10000,
            "MinimumTransferMass": 5,
            "MixerDuration": 99455364,
            "MixerSpeed": 2000,
            "Position": 1,
            "PowderDispenses": [
                {
                "PowderName": "Manganese Oxide",
                "TargetMass": 10
                },
                {
                "PowderName": "Lithium carbonate",
                "TargetMass": 10
                }
            ],
            "TargetTransferVolume": 10000
            },
        """
        if position not in [1, 2, 3, 4]:
            raise ValueError("Position must be 1, 2, 3, or 4!")
        return (
            {
                "CrucibleReplicates": self.replicates,
                "HeatingDuration": self.heating_duration,
                "EthanolDispenseVolume": self.ethanol_volume,
                "MinimumTransferMass": self.min_transfer_mass,
                "MixerDuration": self.mixer_duration,
                "MixerSpeed": self.mixer_speed,
                "Position": self.position,
                "PowderDispenses": [
                    {"PowderName": powder.name, "TargetMass": mass}
                    for powder, mass in self.powder_dispenses.items()
                ],
                "TargetTransferVolume": self.transfer_volume,
            },
        )


class WorkflowStatus(Enum):
    COMPLETE = "Complete"
    RUNNING = "Running"  # TODO check if this is a real status
    FULL = "Full"
    LOADING = "Loading"  # TODO internal status to indicate that this workflow is accepting InputFiles. maybe we dont want to cross Labman and ALab statuses here...
    EMPTY = "Empty"
    UNKNOWN = "Unknown"


class Workflow:  # maybe this should be Quadrant instead
    MAX_SAMPLES: int = 24

    def __init__(self, name: str, prep_window: float = 300):
        self.name = name
        self._manage_window(duration=prep_window)
        self.inputs = []
        self.required_powders = Dict[Powder, float]
        self.required_ethanol_volume = 0
        self.required_jars = 0
        self.required_crucibles = 0

    def _manage_window(self, duration: float):
        self.open = True

        def timer(self, duration: float):
            time.sleep(duration)
            self.open = False

        t = Thread(target=timer, args=(duration,))
        t.run()

    def add_input(self, input: InputFile):
        if not self.open:
            raise WorkflowFullError(
                "The preparation window has closed for this workflow -- cannot add any more InputFile's!"
            )
        if self.required_jars + input.replicates > self.MAX_SAMPLES:
            raise WorkflowFullError(
                f"This workflow is too full ({self.required_jars}/{self.MAX_SAMPLES}) to accomodate this input ({input.replicates} replicates)!"
            )

        self.inputs.append(input)

        for powder, mass in input.powder_dispenses.items():
            if powder not in self.required_powders:
                self.required_powders[powder] = 0
            self.required_powders[powder] += mass
        self.required_ethanol_volume += input.ethanol_volume
        self.required_jars += input.replicates
        self.required_crucibles += input.replicates


class Quadrant:
    """one of the four quadrants on the Labman"""

    def __init__(self, index: int):
        if index not in [1, 2, 3, 4]:
            raise ValueError("Quadrant index must be 1,2,3,or 4!")
        self.current_workflow: Workflow = None
        self.index = index
        self.status = WorkflowStatus.UNKNOWN
        self.available_jars = []  # will populate with indices at which jars are present
        self.available_crucibles = []  # same concept as jars

    @property
    def num_available_jars(self):
        return len(self.available_jars)

    @property
    def num_available_crucibles(self):
        return len(self.available_crucibles)


class Labman:
    API_BASEURL = Path("apibase")  # TODO url path to Labman API
    STATUS_UPDATE_WINDOW: float = (
        5  # minimum time (seconds) between getting status updates from Labman
    )

    def __init__(self):
        self.quadrants = {
            i + 1: Quadrant(index=i + 1) for i in range(4)
        }  # four quadrants, 1-4
        # self.workflows = {i + 1: None for i in range(4)}  # four quadrants, 1-4
        self.powder_stocks = {i + 1: None for i in range(24)}  # 24 stock powders, 1-24
        self.available_jars = {
            i: quad.num_available_jars for i, quad in self.quadrants.items()
        }
        self.available_crucibles = {
            i: quad.num_available_crucibles for i, quad in self.quadrants.items()
        }
        self.available_ethanol = 0
        self.available_powders = {}  #

        self.last_updated_at = 0  # first `self.update_status()` should fire

    @property
    def status(self):
        self.update_status()
        return self._status

    @property
    def heated_rack_temperature(self):
        self.update_status()
        return self._heated_rack_temperature

    @property
    def in_automated_mode(self):
        self.update_status()
        return self._in_automated_mode

    @property
    def rack_under_robot_control(self):
        self.update_status()
        return self._rack_under_robot_control

    @property
    def available_pipette_tips(self):
        self.update_status()
        return self._pipette_tip_count

    @property
    def robot_is_running(self):
        self.update_status()
        return self._robot_running

    def update_status(self):
        """
        Example:
        {
            "ErrorMessage": "adipisicing",
            "Status": "Error",
            "Data": {
                "HeatedRackTemperature": 90261670.70323572,
                "IsInAutomatedMode": false,
                "IndexingRackStatus": "RobotControl",
                "PipetteTipCount": 39371395,
                "ProcessErrorMessage": "incididunt in mollit nisi",
                "QuadrantStatuses": [
                    {
                        "LoadedWorkflowName": "non ad ipsum p",
                        "Progress": "Complete",
                        "QuadrantNumber": 53088119
                    },
                    {
                        "LoadedWorkflowName": "elit voluptate cillum",
                        "Progress": "Empty",
                        "QuadrantNumber": -5344906
                    }
                ],
                "RobotRunning": true
            }
        }
        """
        if (time.time() - self.last_updated_at) < self.STATUS_UPDATE_WINDOW:
            return  # we updated very recently

        response = requests.get(url=self.API_BASE / "GetStatus")
        result = self.__process_server_response(response)
        self._status = result["Status"]
        # TODO do something with error message

        d = result["Data"]
        self._heated_rack_temperature = d["HeatedRackTemperature"]
        self._in_automated_mode = d["IsInAutomatedMode"]
        self._rack_under_robot_control = d["IndexingRackStatus"] == "RobotControl"
        self._pipette_tip_count = d["PipetteTipCount"]
        self._robot_running = d["RobotRunning"]

        for d in result["Data"]["QuadrantStatuses"]:
            idx = d["QuadrantNumber"]
            self.quadrants[idx].status = WorkflowStatus(d["Progress"])
            # TODO handle status workflow name != expected
            # TODO handle quadrants that do not show up in status report

    ### consumables
    def load_ethanol(self, volume: float):
        self.available_ethanol += volume

    def load_jar(self, slot: int, deck: int):
        return

    def load_powder(self, powder: Powder, mass: float, slot: int):
        if slot not in self.powder_stocks:
            raise ValueError("Slot must be an integer between 1-24!")
        if self.powder_stocks[slot] is not None:
            raise PowderLoadingError(
                f"Cannot load powder into slot {slot} -- it is already occupied by {self.powder_stocks[slot].name}! Unload first."
            )
        self.powder_stocks[slot] = {"powder": powder, "mass": mass}
        if powder in self.available_powders:
            self.available_powders[powder] += mass
        else:
            self.available_powders = mass

    def unload_powder(self, slot: int):
        if slot not in self.powder_stocks:
            raise ValueError("Slot must be an integer between 1-24!")
        if self.powder_stocks[slot] is None:
            raise PowderLoadingError(
                f"Cannot unload powder from slot {slot} -- it is already unoccupied!"
            )

        powder = self.powder_stocks[slot]["powder"]
        mass = self.powder_stocks[slot]["mass"]

        if self.available_powders[powder] == mass:
            del self.available_powders[powder]  # no remaining powder of this type
        else:
            self.available_powders[powder] -= mass

    def __process_server_response(self, response: requests.Response) -> dict:
        """Checks server response for errors, returns any json data returned from server

        Args:
            response (requests.Response): Labman server response

        Raises:
            LabmanCommunicationError: Server did not respond with 200

        Returns:
            dict: json contents (if any) of server response. if none, will be an empty dict
        """
        if response.status_code != 200:
            raise LabmanCommunicationError(response.text)
        try:
            return response.json()
        except:
            return {}  # if no json return an empty dict

    ### quadrants
    def __take_quadrant_access(self, index: int):
        response = requests.post(
            url=self.API_BASE
            / f"RequestIndexingRackControl?outwardFacingQuadrant={index}",
        )
        self.__process_server_response(response)  # will throw error if not successful
        while self.rack_under_robot_control:
            time.sleep(self.STATUS_UPDATE_WINDOW)

    def __release_quadrant_access(self):
        response = requests.post(url=self.API_BASE / "ReleaseIndexingRackControl")
        self.__process_server_response(response)  # will throw error if not successful
        while not self.rack_under_robot_control:
            time.sleep(self.STATUS_UPDATE_WINDOW)

    @contextmanager
    def access_quadrant(self, index: int) -> None:
        """Gives the user control of the Labman with a specific quadrant oriented towards the Labman opening

        Args:
            index (int): quadrant index (1,2,3, or 4) to orient towards the opening

        Raises:
            LabmanError: Invalid index provided

        Yields:
            Nothing
        """
        if index not in [1, 2, 3, 4]:
            raise LabmanError("Quadrant must be 1,2,3,or 4!")
        try:
            self.__take_quadrant_access(index=index)
            yield
        finally:
            self.__release_quadrant_access()

    ### crucible requests
    def add_inputfile(self, input: InputFile):
        loading_quadrants = [
            q for q in self.quadrants.values() if q.status == WorkflowStatus.LOADING
        ]
        # TODO rank the loading quadrants to find a workflow with the most overlapping powders
        for q in loading_quadrants:
            # try to load into a loading quadrant
            try:
                q.current_workflow.add_input(input=input)
                return
            except WorkflowFullError:
                continue

        for q in self.quadrants.values():
            if q.status == WorkflowStatus.EMPTY:
                new_workflow = Workflow()
                new_workflow.add_input(input=input)
                q.current_workflow = new_workflow
                return

        raise WorkflowFullError("No room to add this input -- check back later!")

from contextlib import contextmanager
import datetime
from enum import Enum, auto
import uuid
import requests
from threading import Thread
import time
from typing import Dict, List
from pathlib import Path
from alab_control.labman.optimize_workflow import BatchOptimizer

from .components import Powder, InputFile, Workflow, WorkflowStatus
from .error import (
    LabmanCommunicationError,
    LabmanError,
    PowderLoadingError,
    WorkflowError,
    WorkflowFullError,
)
from .database import (
    PowderView,
    JarView,
    CrucibleView,
    ContainerPositionStatus,
    InputFileView,
    LoggingView,
)
from .utils import initialize_labman_database
from .api import LabmanAPI


class BatchingWorkerStatus(Enum):
    """Status of the BatchingWorker"""

    WORKING = auto()
    STOP_REQUESTED = auto()
    STOPPED = auto()


class QuadrantStatus(Enum):
    EMPTY = "Empty"
    LOADING = "Loading"
    OCCUPIED = "Running"


class Quadrant:
    """one of the four quadrants on the Labman"""

    ALLOWED_POSITIONS = [i + 1 for i in range(16)]

    def __init__(self, index: int):
        if index not in [1, 2, 3, 4]:
            raise ValueError("Quadrant index must be 1,2,3,or 4!")
        self.current_workflow: Workflow = None
        self.index = index
        self.status = WorkflowStatus.UNKNOWN
        self.jar_view = JarView()
        self.crucible_view = CrucibleView()

    def add_jar(self, position: int):
        """Loads an empty jar into the specified jar position

        Args:
            position (int): position index where jar is loaded

        Raises:
            ValueError: Invalid position index
            ValueError: Jar position already occupied
        """
        if position not in self.ALLOWED_POSITIONS:
            raise ValueError(f"Position must be one of {self.ALLOWED_POSITIONS}!")
        self.jar_view.add_container(quadrant=self.index, position=position)

    def add_crucible(self, position: int):
        """Loads an empty crucible into the specified crucible position

        Args:
            position (int): position index where crucible is loaded

        Raises:
            ValueError: Invalid position index
            ValueError: Crucible position already occupied
        """
        if position not in self.ALLOWED_POSITIONS:
            raise ValueError(f"Position must be one of {self.ALLOWED_POSITIONS}!")
        self.crucible_view.add_container(quadrant=self.index, position=position)

    def reserve_jar(self, position: int):
        """Reserves the jar at the specified position. The position is still occupied by the jar, but this jar is not available for new InputFiles

        Args:
            position (int): position index where jar is loaded

        Raises:
            ValueError: Invalid position index
        """
        if position not in self.available_jars:
            raise ValueError(f"Jar position {position} is not available!")
        self.jar_view.reserve_container(quadrant=self.index, slot=position)

    def reserve_crucible(self, position: int):
        """Reserves the crucible at the specified position. The position is still occupied by the crucible, but this jar is not available for new InputFiles

        Args:
            position (int): position index where crucible is loaded

        Raises:
            ValueError: Invalid position index
        """
        if position not in self.available_crucibles:
            raise ValueError(f"Crucible position {position} is not available!")
        self.crucible_view.reserve_container(quadrant=self.index, slot=position)

    def remove_jar(self, position: int):
        """Indicates that the jar (empty or filled) has been physically removed from the specified position

        Args:
            position (int): position index jar has been removed from

        Raises:
            ValueError: Jar position was already empty
        """
        if position not in self.occupied_jar_positions:
            raise ValueError(f"Jar position {position} is not occupied!")
        self.jar_view.reserve_container(quadrant=self.index, slot=position)

    def remove_crucible(self, position: int):
        """Indicates that the crucible (empty or filled) has been physically removed from the specified position

        Args:
            position (int): position index crucible has been removed from

        Raises:
            ValueError: Crucible position was already empty
        """
        if position not in self.occupied_crucible_positions:
            raise ValueError(f"Crucible position {position} is not occupied!")
        self.crucible_view.reserve_container(quadrant=self.index, slot=position)

    @property
    def available_jars(self):
        """list of jar positions that are available for new InputFiles"""
        return self.jar_view.get_ready_positions(self.index)

    @property
    def available_crucibles(self):
        """list of crucible positions that are available for new InputFiles"""
        return self.crucible_view.get_ready_positions(self.index)

    @property
    def reserved_jars(self):
        """list of jar positions that are reserved for new InputFiles"""
        return self.jar_view.get_reserved_positions(self.index)

    @property
    def reserved_crucibles(self):
        """list of crucible positions that are reserved for new InputFiles"""
        return self.crucible_view.get_reserved_positions(self.index)

    @property
    def empty_jar_slots(self):
        """list of jar positions that are empty"""
        return self.jar_view.get_empty_positions(self.index)

    @property
    def empty_crucible_slots(self):
        """list of crucible positions that are empty"""
        return self.crucible_view.get_empty_positions(self.index)

    @property
    def num_available_jars(self):
        return len(self.available_jars)

    @property
    def num_available_crucibles(self):
        return len(self.available_crucibles)


class Labman:
    STATUS_UPDATE_WINDOW: float = (
        5  # minimum time (seconds) between getting status updates from Labman
    )
    WORKFLOW_BATCHING_WINDOW: float = (
        300  # max seconds to wait for incoming inputfiles before starting a workflow
    )
    MAX_BATCH_SIZE = 16  # max number of crucibles allowed in a single workflow

    def __init__(self):
        initialize_labman_database(overwrite_existing=False)
        self.quadrants = {i: Quadrant(i) for i in [1, 2, 3, 4]}  # four quadrants, 1-4
        self.powder_view = PowderView()
        self.last_updated_at = 0  # first `self.update_status()` should fire
        self.pending_inputfile_view = InputFileView()
        self.logging = LoggingView()
        # self._batching_worker_thread = self._start_batching_worker()
        self._batching_worker_status = BatchingWorkerStatus.STOPPED
        self.API = LabmanAPI()

    ### status update methods

    def __process_server_response(self, response: requests.Response) -> dict:
        """Checks server response for errors, returns any json data returned from server

        Args:
            response (requests.Response): Labman server response

        Raises:
            LabmanCommunicationError: Server did not respond with 200

        Returns:
            dict: json contents (if any) of server response. if none, will be an empty dict
        """
        # TODO handle error status + messages
        if response.status_code != 200:
            raise LabmanCommunicationError(response.text)
        try:
            return response.json()
        except:
            return {}  # if no json return an empty dict

    def __update_status(self):
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

        response = self.API.get_status()
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
            idx = d["QuadrantNumber"] - 1
            self.quadrants[idx].status = WorkflowStatus(d["Progress"])
            # TODO handle status workflow name != expected
            # TODO handle quadrants that do not show up in status report

    @property
    def status(self):
        self.__update_status()
        return self._status

    @property
    def heated_rack_temperature(self):
        self.__update_status()
        return self._heated_rack_temperature

    @property
    def in_automated_mode(self):
        self.__update_status()
        return self._in_automated_mode

    @property
    def rack_under_robot_control(self):
        self.__update_status()
        return self._rack_under_robot_control

    @property
    def available_pipette_tips(self):
        self.__update_status()
        return self._pipette_tip_count

    @property
    def robot_is_running(self):
        self.__update_status()
        return self._robot_running

    ### consumables
    @property
    def available_jars(self) -> Dict[int, List[int]]:
        return {i: quad.num_available_jars for i, quad in self.quadrants.items()}

    @property
    def available_crucibles(self) -> Dict[int, List[int]]:
        return {i: quad.num_available_crucibles for i, quad in self.quadrants.items()}

    @property
    def available_powders(self) -> Dict[str, float]:
        return self.powder_view.available_powders()

    def load_jar(self, quadrant: int, position: int):
        self.quadrants[quadrant].add_jar(position)

    def load_crucible(self, quadrant: int, position: int):
        self.quadrants[quadrant].add_crucible(position)

    def load_powder(
        self, dosinghead_index: int, powder: str, mass: float, unload_first: bool = True
    ):
        if unload_first:
            dh = self.powder_view.get_dosinghead(dosinghead_index)
            if dh["powder"] is not None:
                self.powder_view.unload_dosinghead(dosinghead_index)

        self.powder_view.load_dosinghead(
            index=dosinghead_index, powder=powder, mass_g=mass
        )

    def unload_powder(self, dosinghead_index: int):
        self.powder_view.unload_dosinghead(dosinghead_index)

    ### quadrant control
    def __take_quadrant_access(self, index: int):
        response = self.API.request_indexing_rack_control(index)
        self.logging.debug(
            category="labman-quadrant-take-request",
            message=f"Requested control of quadrant {index} under ALab control.",
            quadrant_index=index,
        )
        self.__process_server_response(response)  # will throw error if not successful
        self.logging.info(
            category="labman-quadrant-take",
            message=f"Quadrant {index} taken under ALab control.",
            quadrant_index=index,
        )
        while self.rack_under_robot_control:
            time.sleep(self.STATUS_UPDATE_WINDOW)

    def __release_quadrant_access(self):
        response = self.API.release_indexing_rack_control()
        self.logging.debug(
            category="labman-quadrant-release-request",
            message=f"Requested release of the indexing rack control back to Labman.",
        )
        self.__process_server_response(response)  # will throw error if not successful

        while not self.rack_under_robot_control:
            time.sleep(self.STATUS_UPDATE_WINDOW)
        self.logging.info(
            category="labman-quadrant-release",
            message=f"Labman resumed control of the indexing rack.",
        )

    @contextmanager
    def access_quadrant(self, index: int) -> None:
        # TODO contextmanager is an issue for instrument control over RPC, probably do away with this!
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

    ### workflow methods

    def __workflow_batching_worker(self):
        self.logging.debug(
            category="labman-batchingworker-start",
            message="Starting workflow batching worker thread",
        )
        self._timer_active = False
        self._time_to_go = None
        self._batching_worker_status = BatchingWorkerStatus.WORKING
        while self._batching_worker_status == BatchingWorkerStatus.WORKING:
            if self.pending_inputfile_view.num_pending > 0:
                if self._timer_active:
                    # if we already opened the batching window, check if its time to send a batch of inputfiles as a workflow
                    if time.time() > self._time_to_go:
                        self._timer_active = False
                        self._time_to_go = None
                        self._batch_and_submit()
                else:
                    # if not, lets open a batching window now
                    self._timer_active = True
                    self._time_to_go = time.time() + self.WORKFLOW_BATCHING_WINDOW
            time.sleep(self.WORKFLOW_BATCHING_WINDOW / 10)

        self._batching_worker_status = BatchingWorkerStatus.STOPPED
        self.logging.debug(
            category="labman-batchingworker-stop",
            message="Stopped workflow batching worker thread",
        )

    def _start_batching_worker(self):
        thread = Thread(target=self.__workflow_batching_worker)
        thread.daemon = True
        thread.run()
        return thread

    def _stop_batching_worker(self):
        self._batching_worker_status = BatchingWorkerStatus.STOP_REQUESTED
        while self._batching_worker_status != BatchingWorkerStatus.STOPPED:
            time.sleep(self.WORKFLOW_BATCHING_WINDOW / 100)

    def add_inputfile(self, input: InputFile):
        self.pending_inputfile_view.add(input)

    def build_optimal_workflow(self, inputfiles: List[InputFile]) -> List[InputFile]:
        bo = BatchOptimizer(
            available_powders=self.available_powders,
            available_jars=list(self.available_jars.values()),
            available_crucibles=list(self.available_crucibles.values()),
            inputfiles=inputfiles,
        )
        best_quadrant, best_inputfiles = bo.solve()
        name = f"{datetime.datetime.now()} - {len(best_inputfiles)}"
        wf = Workflow(name=name)
        for i in best_inputfiles:
            wf.add_input(i)
        return best_quadrant, wf

    def submit_workflow(self, quadrant_index: int, workflow: Workflow):
        if not self.workflow_is_valid(workflow):
            raise LabmanError("Workflow is not valid!")
        workflow_json = workflow.to_json(
            quadrant_index=quadrant_index,
            available_positions=self.quadrants[quadrant_index].available_jars,
        )  # TODO still no info on crucible locations
        with self.access_quadrant(
            quadrant_index
        ):  # TODO do we need to be under manual control to start a workflow?
            response = self.API.submit_workflow(workflow_json)
            data = self.__process_server_response(response)
            self.logging.info(
                category="labman-workflow-submit",
                message=f"Workflow submitted to Labman",
                workflow=workflow_json,
            )
            # TODO check response and update some stuff

    def workflow_is_valid(self, workflow: Workflow) -> bool:
        workflow_json = workflow.to_json(
            quadrant_index=1,
            available_positions=[i + 1 for i in range(16)],
        )  # dummy quadrant/positions
        response = self.API.validate_workflow(workflow_json)
        data = self.__process_server_response(response)

        if data["Data"]["Result"] == "NoError":
            return True
        else:
            # TODO parse error message and do something useful here
            return False

    def _batch_and_submit(self):
        inputfiles = self.pending_inputfile_view.get_all()
        quadrant_index, workflow = self.build_optimal_workflow(inputfiles)
        self.submit_workflow(quadrant_index, workflow)

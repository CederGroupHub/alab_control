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
from .api import LabmanAPI, WorkflowValidationResult


class BatchingWorkerStatus(Enum):
    """Status of the BatchingWorker"""

    WORKING = auto()
    STOP_REQUESTED = auto()
    STOPPED = auto()


class QuadrantStatus(Enum):
    UNKNOWN = "Unknown"
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
        self.status: QuadrantStatus = QuadrantStatus.UNKNOWN
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
        """list of jar positions that are reserved by existing InputFiles"""
        return self.jar_view.get_reserved_positions(self.index)

    @property
    def reserved_crucibles(self):
        """list of crucible positions that are reserved by existing InputFiles"""
        return self.crucible_view.get_reserved_positions(self.index)

    @property
    def empty_jar_slots(self):
        """list of jar positions that are empty (ie ready to accept a fresh jar)"""
        return self.jar_view.get_empty_positions(self.index)

    @property
    def empty_crucible_slots(self):
        """list of crucible positions that are empty (ie ready to accept a fresh crucible)"""
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

    def __init__(self, url, port):
        initialize_labman_database(overwrite_existing=False)
        self.quadrants = {i: Quadrant(i) for i in [1, 2, 3, 4]}  # four quadrants, 1-4
        self.powder_view = PowderView()
        self.last_updated_at = 0  # first `self.update_status()` should fire
        self.pending_inputfile_view = InputFileView()
        self.logging = LoggingView()
        # self._batching_worker_thread = self._start_batching_worker()
        self._batching_worker_status = BatchingWorkerStatus.STOPPED
        self.API = LabmanAPI(url, port)

    ### status update methods

    def __update_status(self, force: bool = False):
        """
        Example:
        {'ErrorMessage': None,
        'Status': 'OK',
        'Data': {
            'CurrentOutwardQuadrantNumber': 1,
            'HeatedRackTemperature': 23.5,
            'InAutomatedMode': True,
            'IndexingRackStatus': 'UserControl',
            'PipetteTipCount': 123,
            'ProcessErrorMessage': None,
            'QuadrantStatuses': [
                {'LoadedWorkflowName': None,
                'Progress': 'Empty',
                'QuadrantNumber': 1},
            {'LoadedWorkflowName': None, 'Progress': 'Empty', 'QuadrantNumber': 2},
            {'LoadedWorkflowName': None, 'Progress': 'Empty', 'QuadrantNumber': 3},
            {'LoadedWorkflowName': None, 'Progress': 'Empty', 'QuadrantNumber': 4}],
            'RobotRunning': True}}
        """
        if not force:
            if (time.time() - self.last_updated_at) < self.STATUS_UPDATE_WINDOW:
                return  # we updated very recently

        status_dict = self.API.get_status()

        self._heated_rack_temperature = status_dict["HeatedRackTemperature"]
        self._in_automated_mode = status_dict["InAutomatedMode"]
        self._rack_under_robot_control = (
            status_dict["IndexingRackStatus"] == "RobotControl"
        )
        self._pipette_tip_count = status_dict["PipetteTipCount"]
        self._robot_running = status_dict["RobotRunning"]

        for d in status_dict["QuadrantStatuses"]:
            idx = d["QuadrantNumber"]
            self.quadrants[idx].status = QuadrantStatus(d["Progress"])
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
        self.__update_status(force=True)
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
        if index not in [1, 2, 3, 4]:
            raise ValueError(
                f"Invalid quadrant index: {index}. Must be one of [1,2,3,4]"
            )
        self.logging.debug(
            category="labman-quadrant-take-request",
            message=f"Requested control of quadrant {index} under ALab control.",
            quadrant_index=index,
        )
        self.API.request_indexing_rack_control(index)

        # wait for the labman rack to no longer be under robot control
        while self.rack_under_robot_control:
            time.sleep(1)
        self.logging.info(
            category="labman-quadrant-take",
            message=f"Quadrant {index} taken under ALab control.",
            quadrant_index=index,
        )

    def __release_quadrant_access(self):
        self.logging.debug(
            category="labman-quadrant-release-request",
            message=f"Requested release of the indexing rack control back to Labman.",
        )
        self.API.release_indexing_rack_control()

        # wait for labman to take back control of the rack
        while not self.rack_under_robot_control:
            time.sleep(1)
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
        if quadrant_index not in [1, 2, 3, 4]:
            raise LabmanError("Invalid quadrant index!")
        if self.quadrants[quadrant_index].status != QuadrantStatus.EMPTY:
            raise LabmanError(
                f"Cannot start a workflow on quadrant {quadrant_index} -- this quadrant is currently busy!"
            )
        if not self.workflow_is_valid(workflow):
            raise LabmanError(
                "Workflow is not valid!"
            )  # TODO should we propagate the error from the labman API?

        workflow_json = workflow.to_json(
            quadrant_index=quadrant_index,
            available_positions=self.quadrants[quadrant_index].available_jars,
        )  # TODO still no info on crucible locations
        self.API.submit_workflow(workflow_json)
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
        validation_result = self.API.validate_workflow(workflow_json["InputFile"])

        if validation_result == WorkflowValidationResult.NoError:
            return True
        else:
            self.logging.error(
                category="labman-workflow-invalid",
                message=f"Workflow is invalid: {validation_result.value}",
                workflow=workflow_json,
                validation_error=validation_result.value,
            )
            return False

    def _batch_and_submit(self):
        inputfiles = self.pending_inputfile_view.get_all()
        quadrant_index, workflow = self.build_optimal_workflow(inputfiles)
        self.submit_workflow(quadrant_index, workflow)

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

from .components import InputFile, Workflow
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


class QuadrantStatus(Enum):
    UNKNOWN = "Unknown"
    EMPTY = "Empty"
    PROCESSING = "Processing"
    COMPLETE = "Complete"


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
        self.jar_view.remove_container(quadrant=self.index, slot=position)

    def remove_crucible(self, position: int):
        """Indicates that the crucible (empty or filled) has been physically removed from the specified position

        Args:
            position (int): position index crucible has been removed from

        Raises:
            ValueError: Crucible position was already empty
        """
        if position not in self.occupied_crucible_positions:
            raise ValueError(f"Crucible position {position} is not occupied!")
        self.crucible_view.remove_container(quadrant=self.index, slot=position)

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

    def __repr__(self):
        if self.status not in [QuadrantStatus.EMPTY, QuadrantStatus.UNKNOWN]:
            return f"<Quadrant {self.index}: {self.current_workflow} is {self.status.value}>"
        else:
            return f"<Quadrant {self.index}: {self.status.value}>"


class LabmanView:
    STATUS_UPDATE_WINDOW: float = (
        5  # minimum time (seconds) between getting status updates from Labman
    )

    def __init__(self, url="128.3.17.139", port=8080):
        initialize_labman_database(overwrite_existing=False)
        self.quadrants = {i: Quadrant(i) for i in [1, 2, 3, 4]}  # four quadrants, 1-4
        self.powder_view = PowderView()
        self.last_updated_at = 0  # first `self.update_status()` should fire
        self.pending_inputfile_view = InputFileView()
        self.logging = LoggingView()
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
        try:
            status_dict = self.API.get_status()
        except Exception as e:
            print(
                f"Got error: {e}.\n\nLabman API timed out. Check if the Labman GUI is frozen."
            )
            for q in self.quadrants.values():
                # set quadrants to unknown to ensure robot arm doesn't try to pick from the quadrant while we are unsure of the labman state.
                q.status = QuadrantStatus.UNKNOWN

        self._heated_rack_temperature = status_dict["HeatedRackTemperature"]
        self._in_automated_mode = status_dict["InAutomatedMode"]
        self._rack_under_robot_control = (
            status_dict["IndexingRackStatus"] != "UserControl"
        )
        self._pipette_tip_count = status_dict["PipetteTipCount"]
        self._robot_running = status_dict["RobotRunning"]

        for d in status_dict["QuadrantStatuses"]:
            idx = d["QuadrantNumber"]
            self.quadrants[idx].status = QuadrantStatus(d["Progress"])
            self.quadrants[idx].current_workflow = d["LoadedWorkflowName"]
            # TODO handle status workflow name != expected

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

    def get_quadrant_status(self, quadrant_index: int) -> QuadrantStatus:
        if quadrant_index not in [1, 2, 3, 4]:
            raise ValueError(
                f"Invalid quadrant index: {quadrant_index}. Must be one of [1,2,3,4]"
            )
        self.__update_status()
        return self.quadrants[quadrant_index].status

    def workflow_is_valid(self, workflow_json: Dict[any, any]) -> bool:
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

    def _synchronize_dosingheads(self) -> bool:
        """Checks if our database and the Labman's internal database agree on which powders are loaded in which dosing heads.

        Returns:
            bool: True if the dosing heads are in sync, False otherwise
        """
        heads_in_db = self.powder_view.get_filled_dosingheads()
        heads_in_labman = {}
        for entry in self.API.get_dosingheads():
            heads_in_labman[entry["Position"]] = entry["PowderName"]

        in_sync = True
        for index, powder in heads_in_db.items():
            if index not in heads_in_labman:
                in_sync = False
                print(
                    f"Dosing head {index} is empty on the Labman, but contains {powder} in our database!"
                )
            elif heads_in_labman[index] != powder:
                in_sync = False
                print(
                    f"Dosing head {index} contains {heads_in_labman[index]} on the Labman, but contains {powder} in our database!"
                )

        for index, powder in heads_in_labman.items():
            if index not in heads_in_db:
                in_sync = False
                print(
                    f"Dosing head {index} contains {powder} on the Labman, but is empty in our database!"
                )
        return in_sync


class Labman(LabmanView):
    def __init__(self, url="128.3.17.139", port=8080):
        super().__init__(url=url, port=port)

    def load_jar(self, quadrant: int, position: int):
        self.quadrants[quadrant].add_jar(position)

    def load_crucible(self, quadrant: int, position: int):
        self.quadrants[quadrant].add_crucible(position)

    def unload_jar(self, quadrant: int, position: int):
        self.quadrants[quadrant].remove_jar(position)

    def unload_crucible(self, quadrant: int, position: int):
        self.quadrants[quadrant].remove_crucible(position)

    def load_powder(self, dosinghead_index: int, powder: str, mass: float):
        # if self.robot_is_running:
        #     raise LabmanError(
        #         "Cannot load or unload powders while the robot is running! You need to press 'stop' on the Labman's UI first."
        #     )
        dh = self.powder_view.get_dosinghead(dosinghead_index)
        if dh["powder"] is not None:
            raise PowderLoadingError(
                f"Dosinghead {dosinghead_index} already loaded with powder. Unload the powder first!"
            )

        # TODO unload from API if powder_view.load fails
        # self.API.load_powder(
        #     dosinghead_index, powder
        # )  # change powder in Labman database
        self.powder_view.load_dosinghead(
            index=dosinghead_index, powder=powder, mass_g=mass
        )  # change powder in PowderView

    def unload_powder(self, dosinghead_index: int):
        if self.robot_is_running:
            raise LabmanError(
                "Cannot load or unload powders while the robot is running! You need to press 'stop' on the Labman's UI first."
            )
        # TODO reload previous over API if powder_view.load fails

        # self.API.unload_powder(dosinghead_index)  # change powder in Labman database
        self.powder_view.unload_dosinghead(
            dosinghead_index
        )  # change powder in PowderView

    ### quadrant control
    def take_quadrant(self, index: int):
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

    def release_quadrant(self):
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
    def take_quadrant_context(self, index: int) -> None:
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
            self.take_quadrant(index=index)
            yield
        finally:
            self.release_quadrant()

    ### workflow methods
    def submit_workflow(self, quadrant_index: int, workflow: Workflow):
        if quadrant_index not in [1, 2, 3, 4]:
            raise LabmanError("Invalid quadrant index!")
        if self.quadrants[quadrant_index].status != QuadrantStatus.EMPTY:
            raise LabmanError(
                f"Cannot start a workflow on quadrant {quadrant_index} -- this quadrant is currently busy!"
            )
        workflow_json = workflow.to_json(
            quadrant_index=quadrant_index,
            available_positions=self.quadrants[quadrant_index].available_jars,
        )  # TODO still no info on crucible locations
        if not self.workflow_is_valid(workflow_json):
            raise LabmanError(
                "Workflow is not valid! Check the logs for more information."
            )
        self.submit_workflow_json(workflow_json=workflow_json)

        # TODO check response and update some stuff

    def submit_workflow_json(self, workflow_json: dict):
        self.API.submit_workflow(workflow_json)
        self.logging.info(
            category="labman-workflow-submit",
            message=f"Workflow submitted to Labman",
            workflow=workflow_json,
        )

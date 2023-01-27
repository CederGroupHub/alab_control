import requests
from typing import Dict, List, Literal, Union
from ..error import LabmanError, LabmanCommunicationError
from .enums import WorkflowValidationResult

VALID_QUADRANTS = [1, 2, 3, 4]
VALID_DOSING_HEADS = [i + 1 for i in range(24)]


class LabmanAPI:
    REQUESTS_KWARGS = {
        "timeout": 5,
    }  # keyword arguments to pass to requests.get and requests.post

    def __init__(self, url: str, port: int):
        self.API_BASE = f"{url}:{port}"

    ### Under the hood
    def _get(self, url: str, **kwargs):
        mixed_kwargs = self.REQUESTS_KWARGS
        mixed_kwargs.update(kwargs)

        response = requests.get(url=url, **mixed_kwargs)
        return self._process_labman_response(response)

    def _post(self, url: str, **kwargs):
        mixed_kwargs = self.REQUESTS_KWARGS
        mixed_kwargs.update(kwargs)

        response = requests.post(url=url, **mixed_kwargs)
        return self._process_labman_response(response)

    def _process_labman_response(self, response: requests.Response) -> dict:
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

        response = response.json()
        if response["Status"] == "OK":
            return response.get("Data", {})
        else:
            raise LabmanError(response["Message"])

    ### API Calls
    def get_status(self):
        """Get the current status of the Labman

        Returns:
            dict:
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
        url = f"{self.API_BASE}/GetStatus"
        return self._get(url)

    def get_results(self, workflow_name: str):
        url = f"{self.API_BASE}/GetResults"
        return self._get(url=url, params={"workflowName": workflow_name})

    def request_indexing_rack_control(self, index: Literal[1, 2, 3, 4]):
        if index not in [1, 2, 3, 4]:
            raise ValueError(
                f"Indexing rack control can only be requested for quadrants 1-4! You asked for quadrant {index}"
            )
        url = (
            f"{self.API_BASE}/RequestIndexingRackControl?outwardFacingQuadrant={index}"
        )
        return self._post(url=url)

    def release_indexing_rack_control(self):
        url = f"{self.API_BASE}/ReleaseIndexingRackControl"
        return self._post(url)

    def submit_workflow(self, workflow_json: dict):
        url = f"{self.API_BASE}/PotsLoaded"
        return self._post(url, json=workflow_json)

    def pots_unloaded(self, index: Literal[1, 2, 3, 4]):
        url = f"{self.API_BASE}/PotsUnloaded"
        return self._post(url, json={"quadrant": index})

    def validate_workflow(self, workflow_json: dict) -> WorkflowValidationResult:
        url = f"{self.API_BASE}/ValidateWorkflow"
        result = self._post(url, json=workflow_json)
        return WorkflowValidationResult(result["Result"])

    def load_powder(self, index: int, powder_name: str):
        return
        url = f"{self.API_BASE}/DosingHeadLoaded"
        if index not in VALID_DOSING_HEADS:
            raise ValueError(
                f"Invalid dosing head index {index}. Valid values are: {VALID_DOSING_HEADS}"
            )

        return self._post(url, json={"Position": index, "PowderName": powder_name})

    def unload_powder(self, index: int):
        return
        url = f"{self.API_BASE}/DosingHeadUnloaded?position={index}"
        if index not in VALID_DOSING_HEADS:
            raise ValueError(
                f"Invalid dosing head index {index}. Valid values are: {VALID_DOSING_HEADS}"
            )

        return self._post(url)

    def get_dosingheads(self) -> List[Dict[str, Union[bool, int, str]]]:
        """Example response:

        [{  'InDispenser': False,
            'Position': 1,
            'PowderName': 'Titanium Oxide',
            'Status': 'OK'},
            {'InDispenser': False,
            'Position': 12,
            'PowderName': 'Lithium Carbonate',
            'Status': 'Empty'},
            {'InDispenser': False,
            'Position': 19,
            'PowderName': 'Manganese Oxide',
            'Status': 'OK'},
            {'InDispenser': False,
            'Position': 20,
            'PowderName': 'Manganese Oxide',
            'Status': 'OK'},
            {'InDispenser': False,
            'Position': 6,
            'PowderName': 'Silicon Dioxide',
            'Status': 'Empty'},
            {'InDispenser': False,
            'Position': 7,
            'PowderName': 'Silicon Dioxide',
            'Status': 'OK'},
            {'InDispenser': False,
            'Position': 13,
            'PowderName': 'Lithium Carbonate',
            'Status': 'OK'}]


        Returns:
            List[Dict[str, Union[bool, int, str]]]: See example above in docstring
        """
        url = f"{self.API_BASE}/DosingHeads"
        return self._get(url)

import requests
from typing import Literal
from ..error import LabmanError, LabmanCommunicationError
from .enums import WorkflowValidationResult


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

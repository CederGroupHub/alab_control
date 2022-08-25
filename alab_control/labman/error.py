class LabmanError(Exception):
    """A generic error for the Labman"""


class PowderLoadingError(LabmanError):
    """A generic error while loading powders into the Labman"""


class WorkflowError(LabmanError):
    """A generic error for Labman workflows"""


class WorkflowFullError(WorkflowError):
    """Error indicating a workflow is either:
    - completely full
    - does not have enough remaining capacity to include a requested InputFile
    - has just been closed to send to the Labman
    """


class LabmanCommunicationError(LabmanError):
    """Error communicating with Labman"""

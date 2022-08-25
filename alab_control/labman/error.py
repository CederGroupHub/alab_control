class LabmanError(Exception):
    """A generic error for the Labman"""


class PowderLoadingError(LabmanError):
    """A generic error while loading powders into the Labman"""


class WorkflowError(LabmanError):
    """A generic error for Labman workflows"""


class LabmanCommunicationError(LabmanError):
    """Error communicating with Labman"""

from enum import Enum, auto


class WorkflowValidationResult(Enum):
    """
    Enum for the different types of workflow validation errors.
    """

    NoError = auto()
    InvalidCrucibleReplicates = auto()
    TooManyCrucibles = auto()
    InvalidHeatingDuration = auto()
    InvalidEthanolVolume = auto()
    InvalidMixerDuration = auto()
    InvalidMixerSpeed = auto()
    InvalidPosition = auto()
    InvalidPowderMass = auto()
    InvalidTransferVolume = auto()
    NoMixingPots = auto()
    RepeatedPosition = auto()

    InvalidPowderName = (
        auto()
    )  # TODO: Not shown in the mock server, to be updated when the real machine is come
    NoEnoughPipetteTip = (
        auto()
    )  # TODO: Not shown in the mock server, to be updated when the real machine is come

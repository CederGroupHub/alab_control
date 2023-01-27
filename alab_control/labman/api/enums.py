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
    InvalidPowderName = auto()
    NotEnoughPipetteTip = auto()

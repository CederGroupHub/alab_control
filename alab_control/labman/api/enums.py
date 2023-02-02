from enum import Enum


class WorkflowValidationResult(Enum):
    """
    Enum for the different types of workflow validation errors.
    """

    NoError = "NoError"
    NoMixingPots = "NoMixingPots"
    RepeatedPosition = "RepeatedPosition"
    PotWithNoWork = "PotWithNoWork"
    InvalidCrucibleReplicates = "InvalidCrucibleReplicates"
    InvalidHeatingDuration = "InvalidHeatingDuration"
    InvalidEthanolVolume = "InvalidEthanolVolume"
    InvalidMixerDuration = "InvalidMixerDuration"
    InvalidMixerSpeed = "InvalidMixerSpeed"
    InvalidPosition = "InvalidPosition"
    InvalidTransferVolume = "InvalidTransferVolume"
    BlankPowderName = "BlankPowderName"
    InvalidPowderMass = "InvalidPowderMass"
    TooManyCrucibles = "TooManyCrucibles"
    InsufficientPipetteTips = "InsufficientPipetteTips"
    PowderNotLoaded = "PowderNotLoaded"


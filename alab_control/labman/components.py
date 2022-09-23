from threading import Thread
import time
from typing import Dict, Type, List
from molmass import Formula

class Powder:
    def __init__(self, name: str, composition: str):
        self.name = name
        self.formula = Formula(composition)

    def __eq__(self, other):
        if not isinstance(other, Powder):
            return False
        return self.formula._elements == other.formula._elements


class InputFile:
    def __init__(
        self,
        powder_dispenses=Dict[Powder, float],
        heating_duration: int = 300,
        ethanol_volume: int = 10000,
        transfer_volume: int = 10000,
        mixer_speed: int = 2000,
        mixer_duration: int = 900,
        min_transfer_mass: int = 5,
        replicates: int = 1,
    ):
        if transfer_volume > ethanol_volume:
            raise ValueError("`transfer_volume` must be <= `ethanol_volume`!")
        self.powder_dispenses = powder_dispenses
        self.heating_duration = heating_duration
        self.ethanol_volume = ethanol_volume
        self.transfer_volume = transfer_volume
        self.mixer_speed = mixer_speed
        self.mixer_duration = mixer_duration
        self.min_transfer_mass = min_transfer_mass
        self.replicates = replicates

    def to_json(self, position: int):
        """
        Example:
            {
            "CrucibleReplicates": 2,
            "HeatingDuration": 300,
            "EthanolDispenseVolume": 10000,
            "MinimumTransferMass": 5,
            "MixerDuration": 99455364,
            "MixerSpeed": 2000,
            "Position": 1,
            "PowderDispenses": [
                {
                "PowderName": "Manganese Oxide",
                "TargetMass": 10
                },
                {
                "PowderName": "Lithium carbonate",
                "TargetMass": 10
                }
            ],
            "TargetTransferVolume": 10000
            },
        """

        return (
            {
                "CrucibleReplicates": self.replicates,
                "HeatingDuration": self.heating_duration,
                "EthanolDispenseVolume": self.ethanol_volume,
                "MinimumTransferMass": self.min_transfer_mass,
                "MixerDuration": self.mixer_duration,
                "MixerSpeed": self.mixer_speed,
                "Position": self.position,
                "PowderDispenses": [
                    {"PowderName": powder.name, "TargetMass": mass}
                    for powder, mass in self.powder_dispenses.items()
                ],
                "TargetTransferVolume": self.transfer_volume,
            },
        )


class Workflow:  # maybe this should be Quadrant instead
    MAX_SAMPLES: int = 16
    # TODO handle position in inputfile!

    def __init__(self, name: str):
        self.name = name
        self.inputs = []
        self.required_powders = Dict[Powder, float]
        self.required_ethanol_volume = 0
        self.required_jars = 0
        self.required_crucibles = 0
        self.status = WorkflowStatus.LOADING

    def add_input(self, input: InputFile):
        if (self.required_jars + input.replicates) > self.MAX_SAMPLES:
            raise WorkflowFullError(
                f"This workflow is too full ({self.required_jars}/{self.MAX_SAMPLES}) to accomodate this input ({input.replicates} replicates)!"
            )

        self.inputs.append(input)

        for powder, mass in input.powder_dispenses.items():
            if powder not in self.required_powders:
                self.required_powders[powder] = 0
            self.required_powders[powder] += mass * input.replicates
        self.required_ethanol_volume += input.ethanol_volume * input.replicates
        self.required_jars += 1
        self.required_crucibles += input.replicates

    def to_json(self, quadrant_index: int, available_positions: List[int]) -> dict:
        data = {
            "WorkflowName": self.name,
            "Quadrant": quadrant_index,
            "InputFile": [],
        }

        for input, position in zip(self.inputs, available_positions):
            input: InputFile
            data["InputFile"].append(input.to_json(position=position))
        return data



from typing import Dict, Type, List
from molmass import Formula
from bson import ObjectId
from datetime import datetime
from .error import WorkflowFullError
from enum import Enum, auto


class Powder:
    def __init__(self, name: str, composition: str):
        self.name = name
        self.formula = Formula(composition)

    def __eq__(self, other):
        if not isinstance(other, Powder):
            return False
        return self.formula._elements == other.formula._elements


class InputFile:
    MAX_REPLICATES:int = 4
    def __init__(
        self,
        powder_dispenses=Dict[Powder, float],
        heating_duration_s: int = 60*30,
        ethanol_volume_ul: int = 10000,
        transfer_volume_ul: int = 10000,
        mixer_speed_rpm: int = 2000,
        mixer_duration_s: int = 60*9,
        min_transfer_mass_g: int = 5,
        replicates: int = 1,
        time_added: datetime = None,
        _id: ObjectId = None,
    ):
        if len(powder_dispenses) == 0:
            raise ValueError("`powder_dispenses` must be non-empty!")
        self.powder_dispenses = powder_dispenses

        self.heating_duration = heating_duration_s
        if heating_duration_s < 0 or heating_duration_s > 120*60:
            raise ValueError("`heating_duration_s` must be between 0 and 7200 (0 and 120 minutes)! ")

        if transfer_volume_ul > ethanol_volume_ul:
            raise ValueError("`transfer_volume` must be <= `ethanol_volume`!")
        self.ethanol_volume = ethanol_volume_ul
        self.transfer_volume = transfer_volume_ul
        self.mixer_speed = mixer_speed_rpm

        if mixer_duration_s < 0 or mixer_duration_s > 10*60:
            raise ValueError("`mixer_duration_s` must be between 0 and 600 (0 and 10 minutes)! ")
        self.mixer_duration = mixer_duration_s
        self.min_transfer_mass = min_transfer_mass_g
        self.replicates = replicates
        if time_added is None:
            self.time_added = datetime.now()
        else:
            self.time_added = time_added
        if _id is None:
            self._id = ObjectId()
        else:
            self._id = _id

    def to_json(self):
        return {
            "CrucibleReplicates": self.replicates,
            "HeatingDuration": self.heating_duration,
            "EthanolDispenseVolume": self.ethanol_volume,
            "MinimumTransferMass": self.min_transfer_mass,
            "MixerDuration": self.mixer_duration,
            "MixerSpeed": self.mixer_speed,
            "PowderDispenses": [
                {"PowderName": powder, "TargetMass": mass}
                for powder, mass in self.powder_dispenses.items()
            ],
            "TargetTransferVolume": self.transfer_volume,
            "_id": str(self._id),
            "time_added": self.time_added.isoformat(),
        }

    def to_labman_json(self, position: int):
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
        j = self.to_json()
        j.pop("time_added")
        j.pop("_id")
        j["Position"] = position
        return j

    @classmethod
    def from_json(cls, json: Dict):
        return cls(
            powder_dispenses={
                v["PowderName"]: v["TargetMass"] for v in json["PowderDispenses"]
            },
            heating_duration_s=json["HeatingDuration"],
            ethanol_volume_ul=json["EthanolDispenseVolume"],
            transfer_volume_ul=json["TargetTransferVolume"],
            mixer_speed_rpm=json["MixerSpeed"],
            mixer_duration_s=json["MixerDuration"],
            min_transfer_mass_g=json["MinimumTransferMass"],
            replicates=json["CrucibleReplicates"],
            time_added = datetime.fromisoformat(json["time_added"]),
            _id=json["_id"],
        )

    def __repr__(self):
        return f"<InputFile: {len(self.powder_dispenses)} powders, {self.replicates} replicates>"

    @property
    def age(self) -> int:
        """The age (seconds) of this InputFile.

        Returns:
            int: age (seconds)
        """
        return (datetime.now() - self.time_added).seconds

    def __eq__(self, other):
        if not isinstance(other, InputFile):
            return False
        this = self.to_json()
        that = other.to_json()

        dont_consider_for_equality = ["CrucibleReplicates"]
        for key in dont_consider_for_equality:
            this.pop(key, None)
            that.pop(key, None)

        return this == that

    @property
    def can_accept_another_replicate(self) -> bool:
        """Whether this InputFile can accept another replicate.

        Returns:
            bool: True if this InputFile can accept another replicate, False otherwise.
        """
        return self.replicates < self.MAX_REPLICATES

class Workflow:  # maybe this should be Quadrant instead
    MAX_SAMPLES: int = 16
    INVALID_CHARACTERS: List[str] = [":", "\t", "\n", "\r", "\0", "\x0b"]
    def __init__(self, name: str):
        if any([c in self.INVALID_CHARACTERS for c in name]):
            raise ValueError(f"Invalid character in name: {name}. The name must contain characters valid in a Windows filepath.")
        self.name = name
        self.inputs = []

    def add_input(self, input: InputFile):
        if (self.required_crucibles + input.replicates) > self.MAX_SAMPLES:
            raise WorkflowFullError(
                f"This workflow is too full ({self.required_crucibles}/{self.MAX_SAMPLES}) to accomodate this input ({input.replicates} replicates)!"
            )

        # TODO dont merge inputs until we can disentangle them from the workflow results
        # for existing_input in self.inputs:
        #     if input != existing_input:
        #         continue
        #     while input.replicates > 0 and existing_input.can_accept_another_replicate:
        #         existing_input.replicates += 1
        #         input.replicates -= 1
        #     if input.replicates == 0:
        #         return

        self.inputs.append(input) # if we get here, we couldn't merge the input with an existing one


    def to_json(self, quadrant_index: int, available_positions: List[int]) -> dict:
        data = {
            "WorkflowName": self.name,
            "Quadrant": quadrant_index,
            "InputFile": [],
        }

        for input, position in zip(self.inputs, available_positions):
            input: InputFile
            data["InputFile"].append(input.to_labman_json(position=position))
        return data

    def __len__(self):
        return len(self.inputs)

    def __repr__(self):
        return f"""<Workflow: {self.required_jars} jars, {self.required_crucibles} crucibles, {len(self.required_powders)} unique powders>"""

    @property
    def required_ethanol_volume_ul(self) -> int:
        """The total volume of ethanol (in microliters) required to execute this workflow
        """
        return sum([input.ethanol_volume * input.replicates for input in self.inputs])

    @property
    def required_jars(self) -> int:
        """The number of jar required to execute this workflow

        Returns:
            int: number of jars
        """
        return len(self.inputs)

    @property
    def required_crucibles(self) -> int:
        """The number of crucibles required to execute this workflow

        Returns:
            int: number of crucibles
        """
        return sum([input.replicates for input in self.inputs])

    @property
    def required_powders(self) -> Dict[Powder, float]:
        """The masses of powders required to execute this workflow

        Returns:
            Dict[Powder, float]: dictionary of powders and their required masses (in grams)
        """
        powders = {}
        for input in self.inputs:
            for powder, mass in input.powder_dispenses.items():
                if powder not in powders:
                    powders[powder] = 0
                powders[powder] += mass * input.replicates
        return powders

    
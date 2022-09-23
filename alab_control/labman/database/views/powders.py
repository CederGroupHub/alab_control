from ..data_objects import get_collection
from bson import ObjectId


class PowderView:
    ALLOWED_DOSING_HEAD_INDICES = [i + 1 for i in range(24)]

    def __init__(self):
        self.powders = get_collection("powders")
        self.dosingheads = get_collection("dosing_heads")

        # self._lock = get_lock("powders")

    def _initialize(self):
        """Initialize the dosing head database"""
        self.powders.drop()
        self.dosingheads.drop()

        for i in self.ALLOWED_DOSING_HEAD_INDICES:
            self.dosingheads.insert_one(
                {
                    "index": i,
                    "powder": None,
                    "powder_id": None,
                    "mass_g": 0,
                }
            )

    def get_dosinghead(self, index: int):
        if index not in self.ALLOWED_DOSING_HEAD_INDICES:
            raise ValueError(f"Invalid dosing head index {index}. (should be 1-24)")
        return self.dosingheads.find_one({"index": index})

    def get_powder(self, powder: str):
        entry = self.powders.find_one({"name": powder})
        if entry is None:
            raise ValueError(f"Powder {powder} not present on the LabMan")
        return entry

    def available_powders(self):
        return {powder["name"]: powder["mass_g"] for powder in self.powders.find()}

    def _initialize_powder(
        self, powder: str, mass_g: float, dosinghead_index: int
    ) -> ObjectId:
        result = self.powders.insert_one(
            {
                "name": powder,
                "mass_g": mass_g,
                "available_mass_g": mass_g,
                "reserved_mass_g": [],
                "dosing_heads": [dosinghead_index],
            }
        )
        return result.inserted_id

    def load_dosinghead(self, index: int, powder: str, mass_g: float):
        dosinghead_entry = self.get_dosinghead(index)
        if dosinghead_entry["powder"] is not None:
            raise ValueError(f"Dosing head {index} is not empty.")

        powder_entry = self.powders.find_one({"name": powder})
        if powder_entry is None:
            powder_id = self._initialize_powder(powder, mass_g, index)
        else:
            powder_id = powder_entry["_id"]
            powder_entry["mass_g"] += mass_g
            powder_entry["available_mass_g"] += mass_g
            powder_entry["dosing_heads"].append(index)
            self.powders.update_one({"_id": powder_id}, {"$set": powder_entry})

        self.dosingheads.update_one(
            {"index": index},
            {
                "$set": {
                    "powder": powder,
                    "powder_id": powder_id,
                    "mass_g": mass_g,
                }
            },
        )

    def unload_dosinghead(self, index: int):
        # TODO check if removing this dosing head will invalidate running workflows
        dosinghead_entry = self.get_dosinghead(index)
        if dosinghead_entry["powder"] is None:
            raise ValueError(f"Dosing head {index} is already empty.")
        powder_entry = self.powders.find_one({"_id": dosinghead_entry["powder_id"]})
        powder_entry["mass_g"] -= dosinghead_entry["mass_g"]
        powder_entry["dosing_heads"].remove(index)

        self.dosingheads.update_one(
            {"index": index},
            {"$set": {"powder": None, "powder_id": None, "mass_g": 0}},
        )
        if powder_entry["mass_g"] == 0:
            self.powders.delete_one({"_id": powder_entry["_id"]})
        else:
            self.powders.update_one(
                {"_id": powder_entry["_id"]},
                {"$set": powder_entry},
            )

    def reserve_powder(self, powder: str, mass_g: float, reservation_id: ObjectId):
        powder_entry = self.get_powder(powder)
        if powder_entry["mass_g"] < mass_g:
            raise ValueError(
                f"Not enough powder {powder} on the LabMan (requested {mass_g}, only {powder_entry['available_mass_g']} available."
            )
        if reservation_id in powder_entry["reserved_mass_g"]:
            raise ValueError(
                f"Reservation ID {reservation_id} already exists for powder {powder}."
            )

        powder_entry["reserved_mass_g"].append(
            {"reservation_id": reservation_id, "mass_g": mass_g}
        )
        powder_entry["available_mass_g"] -= mass_g

        self.powders.update_one(
            {"_id": powder_entry["_id"]},
            {"$set": powder_entry},
        )

    def consume_powder(self, index: int, mass_g: float, reservation_id: ObjectId):
        powder_entry = self.powders.find_one(
            {"reserved_mass_g.reservation_id": reservation_id}
        )
        if powder_entry is None:
            raise ValueError(f"Reservation ID {reservation_id} not found.")
        dosinghead_entry = self.get_dosinghead(index)
        dosinghead_entry["mass_g"] -= mass_g
        if dosinghead_entry["mass_g"] < 0:
            raise ValueError(
                f"Not enough mass available from dosing head {index}."
            )

        if (
            index not in powder_entry["dosing_heads"]
            or dosinghead_entry["powder_id"] != powder_entry["_id"]
        ):
            raise ValueError(
                f"Reservation ID {reservation_id} is for {powder_entry['powder']}. Dosing head {index} contains {dosinghead_entry['powder']}!"
            )
        remaining_reservations = []
        for entry in powder_entry["reserved_mass_g"]:
            if entry["reservation_id"] == reservation_id:
                reserved_mass = entry["mass_g"]
            else:
                remaining_reservations.append(entry)

        powder_entry["available_mass_g"] += reserved_mass - mass_g
        powder_entry["mass_g"] -= mass_g
        powder_entry["reserved_mass_g"] = remaining_reservations

        if powder_entry["mass_g"] <= 0:  # TODO some tolerance here?
            self.powders.delete_one({"_id": powder_entry["_id"]})
        else:
            self.powders.update_one(
                {"_id": powder_entry["_id"]},
                {"$set": powder_entry},
            )

        if dosinghead_entry["mass_g"] <= 0:
            dosinghead_entry.update(
                {
                    "powder": None,
                    "powder_id": None,
                    "mass_g": 0,
                }
            )
        self.dosingheads.update_one(
            {"index": index},
            {"$set": dosinghead_entry},
        )

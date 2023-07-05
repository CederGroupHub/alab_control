from enum import Enum, auto
from typing import List
from ..data_objects import get_collection
from .logging import LoggingView


class QuadrantStatus(Enum):
    UNKNOWN = "Unknown"
    EMPTY = "Empty"
    PROCESSING = "Processing"
    COMPLETE = "Complete"
    RESERVED = "Reserved"


class QuadrantView:
    QUADRANT_INDICES = [1, 2, 3, 4]

    def __init__(self):
        self.collection = get_collection("quadrant_statuses")
        self.logging = LoggingView()

    def _initialize(self):
        """Initialize the jar database"""
        self.collection.drop()

        for quadrant in self.QUADRANT_INDICES:
            self.collection.insert_one(
                {
                    "quadrant": quadrant,
                    "status": QuadrantStatus.UNKNOWN.name,
                },
            )

    def get_status(self, quadrant: int) -> QuadrantStatus:
        entry = self.collection.find_one({"quadrant": quadrant})
        return QuadrantStatus[entry["status"]]

    def set_status(self, quadrant: int, status: QuadrantStatus):
        self.collection.update_one(
            {"quadrant": quadrant},
            {"$set": {"status": status.name}},
        )
        self.logging.debug(
            category=f"quadrant-status-change",
            message=f"Set status of quadrant {quadrant} to {status.name}.",
            quadrant=quadrant,
            status=status.name,
        )

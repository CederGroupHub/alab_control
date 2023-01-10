from enum import Enum, auto
from typing import List
from ..data_objects import get_collection
from .logging import LoggingView


class ContainerPositionStatus(Enum):
    EMPTYPOSITION = auto()  # no jar/crucible in position
    READY = auto()  # empty jar/crucible
    RESERVED = auto()  # jar/crucible reserved in a workflow
    TRASH = auto()  # jar/crucible has unwanted contents from an aborted workflow
    COMPLETED = auto()  # jar/crucible has contents from completed workflow


class BaseContainerView:
    QUADRANT_INDICES = [1, 2, 3, 4]
    POSITION_INDICES = [i + 1 for i in range(16)]

    def __init__(self, containertype: str):
        self.containertype = containertype
        self.collection = get_collection(containertype)
        self.logging = LoggingView()

    def _initialize(self):
        """Initialize the jar database"""
        self.collection.drop()

        for quadrant in self.QUADRANT_INDICES:
            for position in self.POSITION_INDICES:
                self.collection.insert_one(
                    {
                        "quadrant": quadrant,
                        "position": position,
                        "state": ContainerPositionStatus.EMPTYPOSITION.name,
                    },
                )

    def get_state(self, quadrant: int, position: int) -> ContainerPositionStatus:
        entry = self.collection.find_one({"quadrant": quadrant, "position": position})
        return ContainerPositionStatus[entry["state"]]

    def add_container(self, quadrant: int, position: int):
        if self.get_state(quadrant, position) != ContainerPositionStatus.EMPTYPOSITION:
            raise ValueError("Container position is not empty.")
        self.collection.update_one(
            {"quadrant": quadrant, "position": position},
            {"$set": {"state": ContainerPositionStatus.READY.name}},
        )
        self.logging.debug(
            category=f"{self.containertype}-add",
            message=f"Added {self.containertype} to quadrant {quadrant}, position {position}.",
            quadrant=quadrant,
            position=position,
        )

    def remove_container(self, quadrant: int, position: int):
        if self.get_state(quadrant, position) == ContainerPositionStatus.EMPTYPOSITION:
            raise ValueError("Container position is already empty.")
        self.collection.update_one(
            {"quadrant": quadrant, "position": position},
            {"$set": {"state": ContainerPositionStatus.EMPTYPOSITION.name}},
        )
        self.logging.debug(
            category=f"{self.containertype}-remove",
            message=f"Removed {self.containertype} from quadrant {quadrant}, position {position}.",
            quadrant=quadrant,
            position=position,
        )

    def reserve_container(self, quadrant: int, position: int):
        if self.get_state(quadrant, position) != ContainerPositionStatus.READY:
            raise ValueError("Container position is not ready, cannot reserve!")
        self.collection.update_one(
            {"quadrant": quadrant, "position": position},
            {"$set": {"state": ContainerPositionStatus.RESERVED.name}},
        )
        self.logging.debug(
            category=f"{self.containertype}-reserved",
            message=f"{self.containertype} at quadrant {quadrant}, position {position} was reserved.",
            quadrant=quadrant,
            position=position,
        )

    def mark_container_trash(self, quadrant: int, position: int):
        if self.get_state(quadrant, position) == ContainerPositionStatus.EMPTYPOSITION:
            raise ValueError("Cannot trash an empty container position!")
        self.collection.update_one(
            {"quadrant": quadrant, "position": position},
            {"$set": {"state": ContainerPositionStatus.TRASH.name}},
        )
        self.logging.debug(
            category=f"{self.containertype}-marked-trash",
            message=f"{self.containertype} at quadrant {quadrant}, position {position} is marked as trash.",
            quadrant=quadrant,
            position=position,
        )

    def mark_container_completed(self, quadrant: int, position: int):
        if self.get_state(quadrant, position) == ContainerPositionStatus.EMPTYPOSITION:
            raise ValueError("Cannot mark an empty container position as completed!")
        self.collection.update_one(
            {"quadrant": quadrant, "position": position},
            {"$set": {"state": ContainerPositionStatus.COMPLETED.name}},
        )
        self.logging.debug(
            category=f"{self.containertype}-marked-complete",
            message=f"{self.containertype} at quadrant {quadrant}, position {position} is marked as complete.",
            quadrant=quadrant,
            position=position,
        )

    def get_positions_on_quadrant_by_status(
        self, quadrant: int, status: ContainerPositionStatus
    ) -> List[int]:
        """Get a list of position indices that have empty containers ready for use in a workflow."""
        entries = self.collection.find({"quadrant": quadrant, "state": status.name})
        return [entry["position"] for entry in entries]

    def get_ready_positions(self, quadrant: int) -> List[int]:
        """Get a list of position indices that have empty containers ready for use in a workflow."""
        return self.get_positions_on_quadrant_by_status(
            quadrant, ContainerPositionStatus.READY
        )

    def get_reserved_positions(self, quadrant: int) -> List[int]:
        """Get a list of position indices that have empty containers ready for use in a workflow."""
        return self.get_positions_on_quadrant_by_status(
            quadrant, ContainerPositionStatus.RESERVED
        )

    def get_empty_positions(self, quadrant: int) -> List[int]:
        """Get a list of position indices that have empty containers ready for use in a workflow."""
        return self.get_positions_on_quadrant_by_status(
            quadrant, ContainerPositionStatus.EMPTYPOSITION
        )


class JarView(BaseContainerView):
    def __init__(self):
        super().__init__("jars")


class CrucibleView(BaseContainerView):
    def __init__(self):
        super().__init__("crucibles")

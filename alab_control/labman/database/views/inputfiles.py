from enum import Enum, auto
from typing import List
from bson import ObjectId
from ..data_objects import get_collection
from alab_control.labman.components import InputFile


class InputFileStatus(Enum):
    EMPTYPOSITION = auto()  # no jar/crucible in position
    READY = auto()  # empty jar/crucible
    RESERVED = auto()  # jar/crucible reserved in a workflow
    TRASH = auto()  # jar/crucible has unwanted contents from an aborted workflow
    COMPLETED = auto()  # jar/crucible has contents from completed workflow


class InputFileView:
    def __init__(self):
        self.collection = get_collection("pending_inputfiles")

    def _initialize(self):
        """Initialize the jar database"""
        self.collection.drop()

    def add(self, inputfile: "InputFile"):
        # TODO check for duplicates
        _id = self.collection.insert_one(inputfile.to_json())
        self.logging.info(
            category = f"inputfile-added",
            message = f"An inputfile was added to the database",
            inputfile = inputfile.to_json()
            inputfile_id = _id
        )

    def get(self, id: ObjectId) -> "InputFile":
        entry = self.collection.find_one({"_id": id})
        return InputFile.from_json(entry)

    def remove(self, id: ObjectId):
        self.collection.delete_one({"_id": id})
        self.logging.info(
            category = f"inputfile-removed",
            message = f"An inputfile was removed from the database",
            inputfile_id = id
        )

    def get_all(self) -> List["InputFile"]:
        return [InputFile.from_json(entry) for entry in self.collection.find()]

    @property
    def num_pending(self) -> int:
        return self.collection.count_documents({})

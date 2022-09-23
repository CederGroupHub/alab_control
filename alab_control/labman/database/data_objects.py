"""
A convenient wrapper for MongoClient. We can get a database object by calling ``get_collection`` function.
"""

from typing import Optional
import pymongo
from pymongo import collection, database

from .db_lock import MongoLock


class _GetMongoCollection:
    client: Optional[pymongo.MongoClient] = None
    db: Optional[database.Database] = None
    db_lock: Optional[MongoLock] = None

    @classmethod
    def init(
        cls,
        host: str = "localhost",
        port: int = 27017,
        username="",
        password="",
        db_name="Labman",
    ):
        cls.client = pymongo.MongoClient(
            host=host,
            port=port,
            username=username,
            password=password,
        )
        cls.db = cls.client[db_name]
        cls.db_name = db_name

    @classmethod
    def get_collection(cls, name: str) -> collection.Collection:
        """
        Get collection by name
        """
        if cls.client is None:
            cls.init()

        return cls.db[name]

    @classmethod
    def get_lock(cls, name: str) -> MongoLock:
        if cls.db_lock is None:
            cls.db_lock = MongoLock(collection=cls.get_collection("_lock"), name=name)
        return cls.db_lock

    @classmethod
    def db_exists(cls) -> bool:
        if cls.client is None:
            cls.init()
        return cls.db_name in cls.client.list_database_names()


get_collection = _GetMongoCollection.get_collection
get_lock = _GetMongoCollection.get_lock
db_exists = _GetMongoCollection.db_exists

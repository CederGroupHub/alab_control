"""
A convenient wrapper for MongoClient. We can get a database object by calling ``get_collection`` function.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import pymongo
from pymongo import collection, database

from .db_lock import MongoLock


def _labman_mongo_settings() -> dict[str, Any]:
    """Resolve Labman Mongo host/port.

    Prefer the AlabOS config (same cell DB the rest of the lab uses), then env overrides,
    then the historical localhost:27017 default.
    """
    host = os.environ.get("LABMAN_MONGODB_HOST") or os.environ.get("ALABOS_MONGODB_HOST")
    port_raw = os.environ.get("LABMAN_MONGODB_PORT") or os.environ.get(
        "ALABOS_MONGODB_PORT"
    )
    username = os.environ.get("LABMAN_MONGODB_USERNAME", "")
    password = os.environ.get("LABMAN_MONGODB_PASSWORD", "")
    db_name = os.environ.get("LABMAN_MONGODB_DB", "Labman")

    if host is None or port_raw is None:
        try:
            from alab_management.config import AlabOSConfig

            cfg = AlabOSConfig().get("mongodb", {}) or {}
            host = host or cfg.get("host") or "localhost"
            port_raw = port_raw if port_raw is not None else cfg.get("port", 27017)
            username = username or cfg.get("username", "") or ""
            password = password or cfg.get("password", "") or ""
        except Exception:
            host = host or "localhost"
            port_raw = port_raw if port_raw is not None else 27017

    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 27017

    return {
        "host": host,
        "port": port,
        "username": username or "",
        "password": password or "",
        "db_name": db_name,
    }


class _GetMongoCollection:
    client: Optional[pymongo.MongoClient] = None
    db: Optional[database.Database] = None
    db_lock: Optional[MongoLock] = None
    db_name: str = "Labman"

    @classmethod
    def init(
        cls,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        db_name: str | None = None,
    ):
        settings = _labman_mongo_settings()
        host = host if host is not None else settings["host"]
        port = port if port is not None else settings["port"]
        username = username if username is not None else settings["username"]
        password = password if password is not None else settings["password"]
        db_name = db_name if db_name is not None else settings["db_name"]
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

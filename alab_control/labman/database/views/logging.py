from enum import Enum
from ..data_objects import get_collection
from bson import ObjectId
from datetime import datetime


class LogLevel(Enum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class LoggingView:
    def __init__(self):
        self.collection = get_collection("powders")

    def _initialize(self):
        """Initialize the dosing head database"""
        self.collection.drop()

    def _log_entry(self, category: str, level: LogLevel, message: str, **details):
        self.collection.insert_one(
            {
                "category": category,
                "level": level.value,
                "message": message,
                "created_at": datetime.now(),
                **details,
            }
        )

    def debug(self, category: str, message: str, **details):
        self._log_entry(
            category=category, level=LogLevel.DEBUG, message=message, **details
        )

    def info(self, category: str, message: str, **details):
        self._log_entry(
            category=category, level=LogLevel.INFO, message=message, **details
        )

    def warning(self, category: str, message: str, **details):
        self._log_entry(
            category=category, level=LogLevel.WARNING, message=message, **details
        )

    def error(self, category: str, message: str, **details):
        self._log_entry(
            category=category, level=LogLevel.ERROR, message=message, **details
        )

    def critical(self, category: str, message: str, **details):
        self._log_entry(
            category=category, level=LogLevel.CRITICAL, message=message, **details
        )

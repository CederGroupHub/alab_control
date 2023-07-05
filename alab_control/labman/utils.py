from .database import (
    PowderView,
    CrucibleView,
    JarView,
    InputFileView,
    LoggingView,
    QuadrantView,
)
from .database.data_objects import db_exists


def initialize_labman_database(overwrite_existing=False):
    if overwrite_existing or not db_exists():
        for view in [
            PowderView,
            CrucibleView,
            JarView,
            InputFileView,
            LoggingView,
            QuadrantView,
        ]:
            view()._initialize()

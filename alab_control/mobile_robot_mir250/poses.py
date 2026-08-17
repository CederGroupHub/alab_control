"""Per-station pose records, so Python can check ``BasePosition`` against reality.

``BasePosition`` is a persisted Ability variable, and ``Main`` picks its retreat sequence
from it. If it disagrees with where the robot physically is, ``Main`` drives the wrong
retreat path -- out of a station the robot is not in. Reading the variable over ROS proves
what the program believes, not where the robot is, so the two have to be reconciled
against a pose measured at each station.

Two files back this. ``poses.json`` inside the package is the committed baseline, recorded
on the cell and reviewed. A mutable file, ``MIR250_POSES_FILE`` or
``~/.alab_control/mir250/poses.json``, collects what the robot has done since; a runtime
record wins over the baseline for the same station. Splitting them means a recorded
observation never dirties the repository and the shipped record is always the fallback.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .clients import Pose

BASELINE_FILE = Path(__file__).resolve().parent / "poses.json"

#: Environment variable naming the mutable pose record.
POSES_FILE_ENV = "MIR250_POSES_FILE"

# The base parks by driving to a MiR position, so repeatability is a few centimetres.
# Wider than the charger tolerance because docking is mechanically constrained and a
# station approach is not.
DEFAULT_TOLERANCE_M = 0.25
DEFAULT_HEADING_TOLERANCE_DEG = 8.0

# The charger is mechanically constrained by the dock, so it gets a tighter window.
CHARGER_TOLERANCE_M = 0.30
CHARGER_HEADING_TOLERANCE_DEG = 5.0

# The arm base and the MiR body report poses from the same map but from different origins:
# the Ability `Base` reference sits 0.2588 m from the MiR's own reported centre. Headings
# agree exactly, so a heading disagreement is stale telemetry rather than an offset.
ARM_MOUNT_OFFSET_M = 0.2588
ARM_MOUNT_OFFSET_TOLERANCE_M = 0.15
POSE_SOURCE_HEADING_TOLERANCE_DEG = 1.0


def runtime_file() -> Path:
    """Where observed poses are written."""
    configured = os.environ.get(POSES_FILE_ENV)
    if configured:
        return Path(configured)
    return Path.home() / ".alab_control" / "mir250" / "poses.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


class StationPoses:
    """The recorded pose of each station, and whether a measured pose agrees with it."""

    def __init__(
        self,
        baseline_path: Path | str | None = None,
        runtime_path: Path | str | None = None,
    ) -> None:
        self.baseline_path = Path(baseline_path) if baseline_path else BASELINE_FILE
        self.runtime_path = Path(runtime_path) if runtime_path else runtime_file()
        baseline = _read(self.baseline_path)
        runtime = _read(self.runtime_path)

        self.stations: dict[str, dict[str, Any]] = {}
        for source in (baseline, runtime):
            for station, record in (source.get("stations") or {}).items():
                if isinstance(record, dict):
                    self.stations[station] = record
        self.charger: dict[str, Any] | None = None
        for source in (baseline, runtime):
            record = source.get("charger")
            if isinstance(record, dict):
                self.charger = record

    def known(self, station: str) -> dict[str, Any] | None:
        return self.stations.get(station)

    def offsets(self, station: str, pose: Pose) -> tuple[float, float] | None:
        """Distance in metres and heading difference in degrees from the record."""
        known = self.known(station)
        if not known:
            return None
        return _offsets_from(known, pose)

    def check(
        self,
        station: str,
        pose: Pose,
        *,
        tolerance_m: float = DEFAULT_TOLERANCE_M,
        heading_tolerance_deg: float = DEFAULT_HEADING_TOLERANCE_DEG,
    ) -> str:
        """Why the pose disagrees with the record, or "" when it matches or is new.

        A station with no record yet cannot be checked, and saying so with an empty
        string rather than an error is deliberate: the first visit to a new station is
        how the record gets written.
        """
        measured = self.offsets(station, pose)
        if measured is None:
            return ""
        distance, heading = measured
        if distance <= tolerance_m and heading <= heading_tolerance_deg:
            return ""
        return (
            f"the robot is {distance:.3f} m and {heading:.2f} deg from the pose recorded for "
            f"{station!r} on {self.known(station).get('recorded_at', 'an unknown date')}, "
            f"outside {tolerance_m} m / {heading_tolerance_deg} deg"
        )

    def check_charger(
        self,
        pose: Pose,
        *,
        tolerance_m: float = CHARGER_TOLERANCE_M,
        heading_tolerance_deg: float = CHARGER_HEADING_TOLERANCE_DEG,
    ) -> str:
        """Why the pose is not the charger pose, or "" when it matches or is unknown."""
        if not self.charger:
            return ""
        distance, heading = _offsets_from(self.charger, pose)
        if distance <= tolerance_m and heading <= heading_tolerance_deg:
            return ""
        return (
            f"the robot is {distance:.3f} m and {heading:.2f} deg from the recorded charger "
            f"pose, outside {tolerance_m} m / {heading_tolerance_deg} deg"
        )

    def record(self, station: str, pose: Pose, evidence: str) -> None:
        """Write an observed station pose to the mutable record."""
        self.stations[station] = _record_of(pose, evidence)
        self._flush()

    def record_charger(self, pose: Pose, evidence: str) -> None:
        self.charger = _record_of(pose, evidence)
        self._flush()

    def _flush(self) -> None:
        self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_path.write_text(
            json.dumps(
                {"stations": self.stations, "charger": self.charger},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def _record_of(pose: Pose, evidence: str) -> dict[str, Any]:
    return {
        "x": pose.x,
        "y": pose.y,
        "yaw_deg": pose.yaw_deg,
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "evidence": evidence,
    }


def _offsets_from(record: dict[str, Any], pose: Pose) -> tuple[float, float]:
    distance = math.hypot(pose.x - float(record["x"]), pose.y - float(record["y"]))
    heading = abs((pose.yaw_deg - float(record["yaw_deg"]) + 180.0) % 360.0 - 180.0)
    return distance, heading


def pose_sources_disagree(
    ability_pose: Pose,
    mir_x: float,
    mir_y: float,
    mir_orientation_deg: float,
    *,
    heading_tolerance_deg: float = POSE_SOURCE_HEADING_TOLERANCE_DEG,
    offset_tolerance_m: float = ARM_MOUNT_OFFSET_TOLERANCE_M,
) -> str:
    """Why two independent pose sources cannot both be right, or "" when they agree.

    Ability's ``/v2/transform/Base`` and the MiR's own ``/status`` read the same map from
    different origins: the arm base is mounted ``ARM_MOUNT_OFFSET_M`` from the MiR's
    reported centre, and the headings agree exactly. So a heading disagreement means one
    of the two is stale telemetry, and a separation far from the known offset means they
    are not describing the same robot position at all. Either way, moving on a pose that
    might be stale is what drives the wrong retreat path.
    """
    if math.isnan(mir_x) or math.isnan(mir_y) or math.isnan(mir_orientation_deg):
        return "the MiR did not report a position, so its pose cannot be cross-checked"
    heading_gap = abs(
        (ability_pose.yaw_deg - mir_orientation_deg + 180.0) % 360.0 - 180.0
    )
    if heading_gap > heading_tolerance_deg:
        return (
            f"the two pose sources disagree on heading by {heading_gap:.2f} deg "
            f"(Ability {ability_pose.yaw_deg:.2f}, MiR {mir_orientation_deg:.2f}), "
            "which suggests stale telemetry"
        )
    separation = math.hypot(ability_pose.x - mir_x, ability_pose.y - mir_y)
    if abs(separation - ARM_MOUNT_OFFSET_M) > offset_tolerance_m:
        return (
            f"the arm base and the MiR body are {separation:.3f} m apart, but the arm is "
            f"mounted {ARM_MOUNT_OFFSET_M} m from the MiR centre, so the two pose sources "
            "are not describing the same position"
        )
    return ""


def pose_dict(pose: Pose | None) -> dict[str, float] | None:
    """A pose as plain JSON-able numbers, or None passed through."""
    if pose is None:
        return None
    return {"x": pose.x, "y": pose.y, "yaw_deg": pose.yaw_deg}

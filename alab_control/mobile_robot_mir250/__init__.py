"""Python control of the MiR250 + UR5e mobile manipulator behind an Ability controller.

The Ability block program ``Main`` is a motion library here, not the brain. Sequencing,
station routing, safety, battery policy, cancellation and observability all live in Python:

- :mod:`clients` -- the three interfaces to the cell (Ability REST V2, the Ability
  rosbridge, and the MiR's own REST API), and the state sets that say what each reported
  state means.
- :mod:`registry` / ``stations.toml`` -- stations, regions and routes as data. Adding a
  station or a path is a data edit, validated against the live controller at setup.
- :mod:`mission` -- a mission as an ordered list of legs, each one a single ``Main``
  invocation so every leg boundary is a point where the gripper is provably empty.
- :mod:`engine` -- runs a mission leg by leg, with every blocking wait interruptible by
  cancellation or the battery policy.
- :mod:`preflight` -- the gate that refuses to move when the cell is not in a safe state.
- :mod:`driver` -- :class:`MiR250MobileManipulator`, the surface an AlabOS device uses.
- :mod:`mock` -- :class:`MockMiR250`, the same driver with an in-memory cell underneath, for
  the tests and for AlabOS simulation mode.

Import cost is kept low deliberately: nothing here reads the 14 MB Ability program export
or opens a connection at import time.
"""

from .clients import (
    ALL_STATES,
    ATTENDED_STATES,
    BASE_POSITIONS,
    BUSY_STATES,
    ERROR_STATES,
    IDLE_STATES,
    MAIN_ARGUMENT_KEYS,
    RUNNING_STATES,
    STATE_REQUESTS,
    AbilityClient,
    AbilityRosClient,
    MirClient,
    Pose,
    RobotApiError,
    is_error_state,
    main_arguments,
    mir_client_from_env,
    mir_pause_reason,
    settle_on_charge,
)
from .errors import (
    BatterySuspend,
    LegFailed,
    MaintenanceRequired,
    MissionCancelled,
    MissionInterrupted,
    MobileRobotError,
    PreflightFailed,
    RegistryError,
)
from .driver import (
    CHARGER_NO_WAIT,
    CHARGER_WAIT,
    PARKING_STATION,
    MiR250MobileManipulator,
    classify_failure,
)
from .engine import (
    MissionEngine,
    MissionEvent,
    MissionResult,
    dock_mission,
    go_home_mission,
    legs_summary,
)
from .mission import Leg, LegKind, Mission, SampleMove, dock, transfer, travel
from .mock import FakeAbility, FakeMir, FakeRos, MockMiR250
from .poses import StationPoses, pose_dict, pose_sources_disagree
from .preflight import Check, PreflightReport, preflight
from .safety import (
    DEFAULT_BATTERY_POLICY,
    BatteryPolicy,
    MuteGuard,
    StopReport,
    assert_fields_unmuted,
    emergency_stop,
    fields_muted,
    mir_is_wedged,
    wedge_prompt,
)
from .registry import (
    DEFAULT_REGISTRY,
    ON_BOARD,
    Placement,
    Region,
    Registry,
    Route,
    Station,
    load_registry,
    registry,
)
from .session import APPROACH, RETREAT, BridgeError, ProgrammingSession, PyBridge
from .webhook import StateEvent, WebhookListener

__all__ = [
    "ALL_STATES",
    "APPROACH",
    "ATTENDED_STATES",
    "AbilityClient",
    "AbilityRosClient",
    "BASE_POSITIONS",
    "BUSY_STATES",
    "BatteryPolicy",
    "BatterySuspend",
    "BridgeError",
    "CHARGER_NO_WAIT",
    "CHARGER_WAIT",
    "Check",
    "DEFAULT_BATTERY_POLICY",
    "DEFAULT_REGISTRY",
    "ERROR_STATES",
    "FakeAbility",
    "FakeMir",
    "FakeRos",
    "IDLE_STATES",
    "Leg",
    "LegFailed",
    "LegKind",
    "MAIN_ARGUMENT_KEYS",
    "MaintenanceRequired",
    "MiR250MobileManipulator",
    "MirClient",
    "Mission",
    "MissionCancelled",
    "MissionEngine",
    "MissionEvent",
    "MissionInterrupted",
    "MissionResult",
    "MobileRobotError",
    "MockMiR250",
    "MuteGuard",
    "ON_BOARD",
    "PARKING_STATION",
    "Placement",
    "Pose",
    "PreflightFailed",
    "PreflightReport",
    "ProgrammingSession",
    "PyBridge",
    "RETREAT",
    "RUNNING_STATES",
    "Region",
    "Registry",
    "RegistryError",
    "RobotApiError",
    "Route",
    "STATE_REQUESTS",
    "SampleMove",
    "StateEvent",
    "Station",
    "StationPoses",
    "StopReport",
    "WebhookListener",
    "assert_fields_unmuted",
    "classify_failure",
    "dock",
    "dock_mission",
    "emergency_stop",
    "fields_muted",
    "go_home_mission",
    "is_error_state",
    "legs_summary",
    "load_registry",
    "main_arguments",
    "mir_client_from_env",
    "mir_is_wedged",
    "mir_pause_reason",
    "pose_dict",
    "pose_sources_disagree",
    "preflight",
    "registry",
    "settle_on_charge",
    "transfer",
    "travel",
    "wedge_prompt",
]

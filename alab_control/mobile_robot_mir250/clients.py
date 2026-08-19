"""Clients for the Ability (ER-FLEX) REST V2 API and the MiR250 REST v2.0.0 API.

The Ability controller owns the UR arm, the vision system and all sequencing; it drives
the MiR250 base internally. Prefer commanding motion through Ability so its arm-safety
and marker-calibration logic runs.

This controller serves REST V2 only. There is no mission queue: load one program, start
it, poll until it returns to Idle.

Every state set and every comment here records something that was established against the
real cell. They are load-bearing, not documentation: the difference between ``Idle`` and
``Ready``, the fact that a ``Pause`` on the MiR is usually harmless, and the fact that a
short instruction can pass through ``Executing`` between two polls, are each the reason
some earlier version of this code misread the robot.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import requests

ABILITY_HOST = "192.168.1.207"
ABILITY_PORT = 8082
MIR_HOST = "192.168.1.218"

# Program argument datatype ids. `GET /v2/help/datatypes` names only the first four, but
# the full set is the constants of the `er_msgs/Setting` message the argument list is
# built from. The structured types were always accepted and simply undocumented, which is
# why a pose or a joint vector can be passed as an argument.
TYPE_STRING = 0
TYPE_DOUBLE = 1
TYPE_INTEGER = 2
TYPE_BOOLEAN = 3
TYPE_VECTOR3D = 4
TYPE_VECTOR2D = 5
TYPE_JOINTS = 6
TYPE_RPY = 7
TYPE_POSE = 8

STATE_IDLE = "Idle"
STATE_EXECUTING = "Executing"
STATE_PAUSED = "Paused"

# PUT /status accepts only these three, per the controller's own 400 response:
# "'Idle' is not one of ['Executing', 'Paused', 'Ready']". Ready is the stop request;
# the controller then reports itself as Idle. Asking for Idle is always rejected.
STATE_REQUESTS = ("Executing", "Paused", "Ready")
STATE_STOP_REQUEST = "Ready"

# The full state enum from GET /v2/openapi.json, plus two the controller reports but
# the schema omits. "Finishing Execution" appears at the end of every instruction run
# through the programming interface, and "Running" flickers past while a stranded
# programming token is released.
STATE_READY = "Ready"
STATE_FINISHING = "Finishing Execution"
ALL_STATES = (
    "Idle",
    "Emergency Stop Active",
    "Safeguard Stop Active",
    "Entity Error Active",
    "No Program",
    "Loading Program",
    "Ready",
    "Recovery",
    "Executing",
    "Pausing Execution",
    "Paused",
    "Stopping Execution",
    "Execution Error Active",
    "Joystick Active",
    "Finishing Execution",
    "Running",
)

# Nothing is running and a new program may be started.
IDLE_STATES = (STATE_IDLE, STATE_READY, "No Program")

# Faulted. A stop request, PUT /status {"state": "Ready"}, clears the latch and
# returns the controller to Idle. Note that asking for Idle instead is rejected with
# 400 whatever the state, which is easily mistaken for a latch that will not clear.
ERROR_STATES = (
    "Emergency Stop Active",
    "Safeguard Stop Active",
    "Entity Error Active",
    "Execution Error Active",
)

# Transient states seen while a command is being applied. Recovery is the exception:
# it persists until a stranded programming token is released.
BUSY_STATES = (
    "Loading Program",
    "Pausing Execution",
    "Stopping Execution",
    "Finishing Execution",
    "Running",
    "Recovery",
)

# States that prove something is actually running. A short instruction can pass through
# Executing between two polls, but never skips Finishing Execution, so treating both as
# evidence is what stops a fast instruction looking like one that never started.
RUNNING_STATES = (STATE_EXECUTING, "Running", STATE_FINISHING)

# A person has taken control. Not errors, but an unattended run cannot continue and
# must not wait them out: whoever is holding the joystick decides what happens next.
ATTENDED_STATES = (STATE_PAUSED, "Joystick Active")

# A stranded programming token. Neither idle nor an error: REST rejects every state
# request from here and /er/system/stop cannot process a Stop, so the only way out is
# AbilityRosClient.force_token_release().
STATE_RECOVERY = "Recovery"


def is_error_state(state: str) -> bool:
    return state in ERROR_STATES or "error" in (state or "").lower()


# The MiR's own idle text once Ability hands the base back. Anything else alongside a
# Pause means real work was cut short.
MIR_IDLE_PAUSE_TEXT = "waiting for new mission"


def mir_pause_reason(status: Mapping[str, Any]) -> str:
    """Why a paused MiR needs attention, or "" when the pause is harmless.

    Ability parks the base in Pause every time one of its drive blocks finishes, with
    mission_text "Waiting for new missions ...", and resumes it itself on the next
    drive, so that pause blocks nothing. A pause that still names a mission is the
    harmful one, and on the charger it means the dock aborted and charging never
    started.
    """
    if str(status.get("state_text", "")) != "Pause":
        return ""
    text = str(status.get("mission_text") or "")
    if MIR_IDLE_PAUSE_TEXT in text.lower():
        return ""
    return (
        f"the MiR is paused part-way through a mission (mission_text={text!r}), so it will not "
        "move or charge until that is cleared: press Continue on the MiR interface, or redock it"
    )


# Main reads every one of these keys out of its `arguments` dictionary on startup and
# throws "the key ... does not exists in dictionary" if one is absent, so always send
# all five. The program's own guards compare against the literal string "None".
MAIN_ARGUMENT_KEYS = (
    "target_base_position",
    "source_region",
    "source_slot",
    "destination_region",
    "destination_slot",
)
MAIN_ARGUMENT_NONE = "None"


def main_arguments(**overrides: Any) -> dict[str, str]:
    """Build a complete argument set for Main, defaulting unused keys to "None"."""
    unknown = set(overrides) - set(MAIN_ARGUMENT_KEYS)
    if unknown:
        raise ValueError(f"unknown Main arguments: {sorted(unknown)}")
    args = {key: MAIN_ARGUMENT_NONE for key in MAIN_ARGUMENT_KEYS}
    args.update({key: str(value) for key, value in overrides.items()})
    return args


# Accepted values of Main's target_base_position argument. Anything else makes the
# program throw NotImplementedError.
BASE_POSITIONS = (
    "Home",
    "Charging",
    "ChargingNoWait",
    "LABMAN",
    "BFT",
    "DASH",
    "SRS",
    "IXRD",
    "SEMEDS",
)


class RobotApiError(RuntimeError):
    """An HTTP or transport failure against one of the robot APIs.

    Carries the status code and raw response body, since Ability reports block
    errors as text rather than through the status code.
    """

    def __init__(
        self,
        message: str,
        *,
        method: str = "",
        url: str = "",
        status: int | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.method = method
        self.url = url
        self.status = status
        self.body = body

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.method or self.url:
            parts.append(f"({self.method} {self.url})")
        if self.status is not None:
            parts.append(f"status={self.status}")
        if self.body:
            body = self.body if len(self.body) <= 500 else self.body[:500] + "..."
            parts.append(f"body={body}")
        return " ".join(parts)


@dataclass(frozen=True)
class Pose:
    """A transform from GET /v2/transform/{ref}: meters and radians.

    The manual labels the payload XYZRPY, but the 4th element is the heading on the
    map, not roll: for Base in World it reads 0.6175 rad = 35.3799 deg, matching the
    MiR's reported orientation of 35.3799 deg exactly. On a flat floor the remaining
    two rotations stay at zero, so they are kept only for completeness.
    """

    x: float
    y: float
    z: float
    yaw: float
    rot2: float
    rot3: float

    @property
    def yaw_deg(self) -> float:
        return math.degrees(self.yaw)

    def distance_to(self, other: "Pose") -> float:
        """Planar distance, ignoring z."""
        return math.hypot(self.x - other.x, self.y - other.y)

    def heading_error_deg(self, other: "Pose") -> float:
        """Smallest absolute heading difference in degrees."""
        return abs((self.yaw_deg - other.yaw_deg + 180.0) % 360.0 - 180.0)


class _JsonClient:
    def __init__(self, base_url: str, timeout: float = 10.0, retries: int = 2) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._session = requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        # The MiR web server drops keep-alive connections under sustained polling, so
        # retry transport failures before giving up. HTTP errors are not retried.
        last_exc: requests.RequestException | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self._session.request(
                    method,
                    url,
                    json=json,
                    params=params,
                    headers=dict(headers or {}),
                    timeout=self.timeout,
                )
                break
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        else:
            raise RobotApiError(
                f"request failed after {self.retries + 1} attempts: {last_exc}",
                method=method,
                url=url,
            ) from last_exc

        if not response.ok:
            raise RobotApiError(
                "unexpected HTTP status",
                method=method,
                url=url,
                status=response.status_code,
                body=response.text,
            )

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise RobotApiError(
                f"response was not JSON: {exc}",
                method=method,
                url=url,
                status=response.status_code,
                body=response.text,
            ) from exc

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        """Escape hatch for endpoints without a dedicated method."""
        return self._request(
            "GET", path, params=params, headers=getattr(self, "_headers", None)
        )

    def close(self) -> None:
        self._session.close()


class AbilityClient(_JsonClient):
    """Ability REST V2. No authentication; interactive docs live at /v2/ui."""

    def __init__(
        self,
        host: str = ABILITY_HOST,
        port: int = ABILITY_PORT,
        timeout: float = 10.0,
    ) -> None:
        super().__init__(f"http://{host}:{port}/v2", timeout=timeout)
        self.host = host
        self.port = port

    def programs(self) -> list[str]:
        return self._request("GET", "/programs")

    def program_current(self) -> dict[str, Any] | None:
        """The loaded program, or None. The API returns "" when nothing is loaded."""
        result = self._request("GET", "/programs/current")
        return result if isinstance(result, dict) else None

    def load_program(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        arg_type: int = TYPE_STRING,
        arg_types: Mapping[str, int] | None = None,
        webhook_uri: str | None = None,
        webhook_context: str = "",
    ) -> dict[str, Any]:
        """Load a program with arguments.

        Loading resets every reference to its default transform, discarding any
        marker calibration from a previous run.

        Arguments are strings unless named in arg_types, which takes any of the TYPE_*
        ids: a pose or joint vector goes across as its text form with the matching id.

        Pass webhook_uri to have the controller PUT execution state changes to your
        own HTTP server instead of polling. The callback body is
        {"state": ..., "message": ..., "context": ...}; reply 200 to keep receiving
        them, or 404 to be unregistered.
        """
        payload: dict[str, Any] = {
            "name": name,
            "arguments": [
                {
                    "name": key,
                    "type": (arg_types or {}).get(key, arg_type),
                    "value": str(value),
                }
                for key, value in (arguments or {}).items()
            ],
        }
        if webhook_uri:
            payload["webhook"] = {"uri": webhook_uri, "context": webhook_context}
        return self._request("PUT", "/programs/current", json=payload)

    def status(self) -> dict[str, Any]:
        """State, loaded program, battery and message.

        Block errors appear in the "message" field, so always read it.
        """
        return self._request("GET", "/status")

    def state(self) -> str:
        """Just the controller state, which is what most guards actually want."""
        return str(self.status().get("state", ""))

    def set_state(self, state: str) -> dict[str, Any]:
        if state not in STATE_REQUESTS:
            raise ValueError(f"state must be one of {STATE_REQUESTS}, got {state!r}")
        return self._request("PUT", "/status", json={"state": state})

    def start(self) -> dict[str, Any]:
        return self.set_state(STATE_EXECUTING)

    def stop(self) -> dict[str, Any]:
        """Request a stop, which also clears a latched execution error.

        Rejected with 400 when there is nothing to stop, so an already-idle
        controller refuses this.
        """
        return self.set_state(STATE_STOP_REQUEST)

    def wait_until_loadable(self, timeout: float = 30.0, poll: float = 0.5) -> str:
        """Block until a new program can be loaded, and return the state seen.

        Tearing down a finished program passes through Ready on the way to Idle, and
        a load during that window is rejected with "State machine couldn't process
        event: ActivateProgramming". Ready is otherwise a perfectly good state, so
        this waits for it to settle rather than treating it as an error.
        """
        deadline = time.monotonic() + timeout
        state = ""
        while time.monotonic() < deadline:
            state = str(self.status().get("state", ""))
            if state in (STATE_IDLE, "No Program"):
                return state
            if state not in (STATE_READY, "Loading Program", "Stopping Execution"):
                break
            time.sleep(poll)
        raise RobotApiError(
            f"controller is {state!r}, which will not accept a program load",
            method="PUT",
            url=f"{self.base_url}/programs/current",
        )

    def references(self) -> dict[str, Any]:
        return self._request("GET", "/references")

    def transform(self, ref_id: str = "Base", from_ref: str = "World") -> Pose:
        """Pose of a reference. Base in World is the arm base on the MiR map."""
        values = self._request(
            "GET", f"/transform/{ref_id}", params={"_from": from_ref}
        )
        if not isinstance(values, list) or len(values) != 6:
            raise RobotApiError(
                f"expected 6 transform values, got {values!r}",
                method="GET",
                url=f"{self.base_url}/transform/{ref_id}",
            )
        return Pose(*(float(v) for v in values))

    def datatypes(self) -> dict[str, int]:
        return self._request("GET", "/help/datatypes")


#: MiR persistent setting that latches the protective-field mute. ROS unmute can
#: report success while this stays ``true``, which is why recovery writes it directly.
MIR_MUTE_SETTING_ID = 2137

#: Position type 0, "Robot position", from GET /position_types. What a plain marker on the
#: map is, as opposed to a cart or charger entry.
MIR_ROBOT_POSITION_TYPE = 0


class MirClient(_JsonClient):
    """MiR250 REST v2.0.0.

    GET /status needs no credentials. Everything else returns 401; supply a
    username and password to reach positions, missions, settings and the
    mission queue.
    """

    def __init__(
        self,
        host: str = MIR_HOST,
        timeout: float = 10.0,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        super().__init__(f"http://{host}/api/v2.0.0", timeout=timeout)
        self.host = host
        self._headers: dict[str, str] = {}
        if username is not None and password is not None:
            self._headers["Authorization"] = _mir_basic_auth(username, password)

    @property
    def authenticated(self) -> bool:
        """Whether credentials were supplied, so the non-status endpoints will work."""
        return "Authorization" in self._headers

    def status(self) -> dict[str, Any]:
        """Includes position {x, y, orientation}, battery_percentage, state_text,
        mode_text and mission_text. orientation is in degrees."""
        return self._request("GET", "/status", headers=self._headers)

    def position(self) -> tuple[float, float, float]:
        """Base pose on the map as (x, y, orientation_deg)."""
        pos = self.status().get("position") or {}
        return (
            float(pos.get("x", float("nan"))),
            float(pos.get("y", float("nan"))),
            float(pos.get("orientation", float("nan"))),
        )

    def battery_percentage(self) -> float:
        """Charge percentage. The one number available without credentials."""
        return float(self.status().get("battery_percentage", float("nan")))

    def positions(self) -> list[dict[str, Any]]:
        """Requires credentials."""
        return self._request("GET", "/positions", headers=self._headers)

    def missions(self) -> list[dict[str, Any]]:
        """Requires credentials."""
        return self._request("GET", "/missions", headers=self._headers)

    def guid(self, kind: str, guid: str) -> dict[str, Any]:
        """Resolve a positions or missions GUID to its record. Requires credentials."""
        return self._request("GET", f"/{kind}/{guid}", headers=self._headers)

    def _require_auth(self, what: str) -> None:
        if not self.authenticated:
            raise RobotApiError(
                f"{what} needs MiR credentials (MIR_USERNAME / MIR_PASSWORD)",
                url=f"{self.base_url}/settings",
            )

    def setting(self, setting_id: int) -> dict[str, Any]:
        """One MiR setting record. Requires credentials."""
        self._require_auth("reading a MiR setting")
        result = self._request(
            "GET", f"/settings/{setting_id}", headers=self._headers
        )
        return result if isinstance(result, dict) else {}

    def put_setting(self, setting_id: int, value: str) -> Any:
        """Write a MiR setting. Requires credentials.

        The body is ``{"value": ...}`` as a string, matching the GET shape.
        """
        self._require_auth("writing a MiR setting")
        return self._request(
            "PUT",
            f"/settings/{setting_id}",
            json={"value": value},
            headers=self._headers,
        )

    def set_protective_fields_muted(self, muted: bool) -> None:
        """Enable or disable the MiR *feature* for reducing protective fields (setting 2137).

        This is not the live ``safety_system_muted`` latch; ROS
        ``/mobile/mute_protective_fields`` drives that. Recovery still writes 2137
        because some cells persist mute there, then verifies ``GET /status``.
        """
        self.put_setting(MIR_MUTE_SETTING_ID, "true" if muted else "false")

    def resume_ready(self) -> dict[str, Any]:
        """Clear a harmful MiR pause (e.g. ``Aborted - User Request``).

        Puts the base in ``Ready`` and drops a stuck mission queue entry so
        redock and charging can proceed. Requires credentials.
        """
        self._require_auth("resuming the MiR from a harmful pause")
        return self._request(
            "PUT",
            "/status",
            json={"state_id": 3},
            headers=self._headers,
        )

    def create_position(
        self,
        name: str,
        x: float,
        y: float,
        orientation: float = 0.0,
        *,
        map_id: str | None = None,
        type_id: int = MIR_ROBOT_POSITION_TYPE,
    ) -> dict[str, Any]:
        """Put a named marker on the MiR map. Requires credentials.

        Used to pin where an obstruction was found, so it appears on the same map the
        operator is already looking at rather than only in a log file. The map defaults to
        whichever one is loaded, since a marker on an unloaded map helps nobody.
        """
        self._require_auth("creating a MiR map position")
        target_map = map_id or str(self.status().get("map_id") or "")
        if not target_map:
            raise RobotApiError(
                "the MiR did not report which map is loaded, so a position cannot be placed",
                url=f"{self.base_url}/positions",
            )
        return self._request(
            "POST",
            "/positions",
            json={
                "name": name,
                "pos_x": float(x),
                "pos_y": float(y),
                "orientation": float(orientation),
                "type_id": int(type_id),
                "map_id": target_map,
            },
            headers=self._headers,
        )


class AbilityRosClient:
    """Ability's ROS interface over the rosbridge websocket on port 9090.

    Far larger than REST V2: 425 services and 140 topics against REST's handful.
    The `/er/*` namespace is the documented 23-service subset; the `/ability_backend/*`
    namespace is what the web UI itself uses. Four capabilities matter most:

    - `persistent/global/get_variable` reads Ability program variables, including
      `BasePosition`. This is the station the program believes it is parked at, and it
      is not exposed over REST at all.
    - `program/execute_instruction` runs a single backend instruction given as XML,
      which is how Python calls one of `Main`'s function blocks without loading it.
    - `get_positions` and `get_charging_stations` resolve MiR GUIDs to names without
      MiR credentials.
    - `program/save_program_as` and `program/load_program_backup` are a program
      backup and restore path that the manual does not mention.

    Service replies wrap their payload as {"data": {"data": [...]}} with positions
    encoded as {"a": name, "b": guid}. Most also carry `success` and `error_message`,
    and a false `success` is *not* reported as a transport failure, so check it.
    """

    def __init__(
        self, host: str = ABILITY_HOST, port: int = 9090, timeout: float = 15.0
    ) -> None:
        self.host = host
        self.url = f"ws://{host}:{port}"
        self.timeout = timeout

    def service_type(self, service: str) -> str:
        """ROS message type of a service, via rosapi. Read-only."""
        return str(
            self.call_service("/rosapi/service_type", {"service": service}).get(
                "type", ""
            )
        )

    def topic_type(self, topic: str) -> str:
        """ROS message type of a topic, via rosapi. Read-only."""
        return str(
            self.call_service("/rosapi/topic_type", {"topic": topic}).get("type", "")
        )

    def healthcheck(self, name: str) -> dict[str, Any]:
        """Call ``/{name}/healthcheck``. Used to see whether a latched entity error is stale."""
        path = name if name.startswith("/") else f"/{name}/healthcheck"
        return self.call_service(path)

    def docker_modules(self, timeout: float = 5.0) -> list[str]:
        """Names of Ability docker modules, from the latched ``/docker_backend/modules`` topic."""
        for message in self.topic_messages(
            "/docker_backend/modules", count=1, timeout=timeout
        ):
            return _docker_module_names(message)
        return []

    def restart_docker_module(self, name: str) -> dict[str, Any]:
        """Restart one Ability docker module. Never call ``restart_all`` from here."""
        return self.call_service(
            "/docker_backend/restart_module", {"request": name}
        )

    def publish(
        self,
        topic: str,
        message: Mapping[str, Any],
        *,
        type_name: str,
    ) -> None:
        """Advertise, publish one message, and unadvertise. For jogging with a deadman."""
        try:
            import websocket
        except ImportError as exc:  # pragma: no cover
            raise RobotApiError(
                "the websocket-client package is required for the ROS interface: "
                "pip install websocket-client"
            ) from exc

        connection = websocket.create_connection(self.url, timeout=self.timeout)
        try:
            connection.send(
                json.dumps(
                    {"op": "advertise", "topic": topic, "type": type_name}
                )
            )
            connection.send(
                json.dumps({"op": "publish", "topic": topic, "msg": dict(message)})
            )
            connection.send(json.dumps({"op": "unadvertise", "topic": topic}))
        finally:
            connection.close()

    def call_service(
        self, service: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            import websocket  # provided by the websocket-client package
        except ImportError as exc:  # pragma: no cover
            raise RobotApiError(
                "the websocket-client package is required for the ROS interface: "
                "pip install websocket-client"
            ) from exc

        request_id = f"py-{int(time.time() * 1000)}"
        try:
            connection = websocket.create_connection(self.url, timeout=self.timeout)
        except Exception as exc:
            raise RobotApiError(
                f"could not connect to rosbridge at {self.url}: {exc}"
            ) from exc
        try:
            connection.send(
                json.dumps(
                    {
                        "op": "call_service",
                        "service": service,
                        "args": args or {},
                        "id": request_id,
                    }
                )
            )
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                message = json.loads(connection.recv())
                if (
                    message.get("op") == "service_response"
                    and message.get("id") == request_id
                ):
                    if not message.get("result", True):
                        raise RobotApiError(
                            f"ROS service {service} failed: {message.get('values')}",
                            url=f"{self.url}{service}",
                        )
                    return message.get("values", {}) or {}
            raise RobotApiError(
                f"timed out waiting for a reply from {service}", url=self.url
            )
        finally:
            connection.close()

    def system_stop(self) -> dict[str, Any]:
        """Stop execution and reset errors.

        Equivalent to the REST stop request and subject to the same limitation: it
        rejects a Stop when nothing is stoppable, including from Recovery and from an
        already-idle controller. Prefer the REST stop, and use `force_token_release`
        for Recovery.
        """
        return self.call_service("/er/system/stop")

    def force_token_release(self) -> dict[str, Any]:
        """Release a stranded programming token.

        A token taken by `activate_programming` and not cleanly released leaves the
        programming region in Recovery, reporting "Connection error: Request canceled
        by user. (110)". In that state REST rejects every state request and
        `/er/system/stop` cannot process a Stop, so this is the only way out short of
        the web UI.
        """
        return self.call_service("/ability_backend/program/force_token_release")

    def system_status(self) -> dict[str, Any]:
        return self.call_service("/er/system/get_status").get("data") or {}

    def program_state(self) -> dict[str, Any]:
        """Six concurrent state machines: safety, system, execution, joystick, timer, main.

        Richer than REST GET /status, which collapses these into one string.
        """
        return (
            self.call_service("/ability_backend/system/get_program_state").get("data")
            or {}
        )

    def variable_names(self, scope: str = "global") -> list[str]:
        """Names of the persisted Ability variables.

        The program scope is only populated while a program is open in the editor;
        `Main` keeps its state in the global scope.
        """
        reply = self.call_service(
            f"/ability_backend/persistent/{scope}/get_variable_names"
        )
        return list((reply.get("data") or {}).get("data") or [])

    def variable(self, name: str, scope: str = "global") -> Any:
        """Read one persisted Ability variable, JSON-decoded.

        Strings come back JSON-quoted, so `BasePosition` reads as "Charging" rather
        than Charging; poses come back as a six-element list.
        """
        reply = self.call_service(
            f"/ability_backend/persistent/{scope}/get_variable", {"data": name}
        )
        if not reply.get("success", True):
            raise RobotApiError(
                f"could not read variable {name!r}: {reply.get('error_message')}",
                url=f"{self.url}/persistent/{scope}/get_variable",
            )
        raw = reply.get("data")
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return raw

    def base_position(self) -> str:
        """The station `Main` believes the base is parked at.

        The authoritative answer to "where does the program think it is". `Main`
        drives its retreat path from this, so a stale value makes the robot move as
        though parked somewhere it is not. Always read it before commanding a move.
        """
        return str(self.variable("BasePosition"))

    def robot_pose(self) -> str:
        """The arm posture `Main` believes it left the manipulator in, e.g. "Home"."""
        return str(self.variable("RobotPose"))

    def manipulator_q(self) -> list[float]:
        """Live arm joint angles in radians, six values."""
        reply = self.call_service("/ability_backend/workcell/get_manipulator_q")
        return [float(v) for v in ((reply.get("q") or {}).get("Q") or [])]

    def base_pose(self, timeout: float = 5.0) -> Pose:
        """Base pose on the map from the mobile driver, as x, y and heading.

        A third independent pose source alongside Ability's `/v2/transform/Base` and
        the MiR's own status, useful for cross-checking before a move.
        """
        for message in self.topic_messages("/mobile/device_state", count=1, timeout=timeout):
            pose = message.get("pose") or {}
            return Pose(
                float(pose.get("x", 0.0)),
                float(pose.get("y", 0.0)),
                0.0,
                float(pose.get("theta", 0.0)),
                0.0,
                0.0,
            )
        raise RobotApiError("/mobile/device_state published nothing", url=self.url)

    def is_charging(self) -> bool:
        """Whether the MiR is actually drawing charge.

        A direct answer where the MiR REST API only offers `mission_text` prose.
        """
        return bool(self.call_service("/mobile/is_charging").get("response"))

    def battery(self) -> dict[str, Any]:
        """Charge percentage and remaining runtime in seconds."""
        return self.call_service("/mobile/get_battery_status")

    def available_programs(self) -> list[str]:
        return list(
            self.call_service(
                "/ability_backend/program/get_available_programs"
            ).get("programs")
            or []
        )

    def backup_programs(self) -> list[str]:
        """Programs with a controller-side backup that `load_program_backup` can restore."""
        return list(
            self.call_service(
                "/ability_backend/program/get_available_backup_programs"
            ).get("programs")
            or []
        )

    def manip_events(self) -> list[str]:
        """Named arm sequences the controller can execute, the arm's action vocabulary."""
        return list(
            (self.call_service("/er/manip/get_events").get("data") or {}).get("data")
            or []
        )

    def version(self) -> str:
        return str(
            self.call_service("/ability_backend/system/get_version").get("version", "")
        )

    def _name_guid_pairs(self, service: str) -> dict[str, str]:
        payload = self.call_service(service).get("data") or {}
        return {row.get("b", ""): row.get("a", "") for row in (payload.get("data") or [])}

    def positions(self) -> dict[str, str]:
        """MiR position GUID to name, no MiR credentials needed."""
        return self._name_guid_pairs("/er/mobile/get_positions")

    def charging_stations(self) -> dict[str, str]:
        """Charging station GUID to name."""
        return self._name_guid_pairs("/er/mobile/get_charging_stations")

    def topic_messages(
        self, topic: str, *, count: int = 1, timeout: float | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield up to `count` messages from a ROS topic, then unsubscribe.

        Ability's topics are latched only in the sense that they publish on change, so
        a quiet topic yields nothing within the timeout. That absence is itself a
        finding: it means the value is not observable from outside while idle.
        """
        try:
            import websocket
        except ImportError as exc:  # pragma: no cover
            raise RobotApiError(
                "the websocket-client package is required for the ROS interface: "
                "pip install websocket-client"
            ) from exc

        limit = self.timeout if timeout is None else timeout
        connection = websocket.create_connection(self.url, timeout=limit)
        subscription = f"py-sub-{int(time.time() * 1000)}"
        try:
            connection.send(
                json.dumps({"op": "subscribe", "topic": topic, "id": subscription})
            )
            deadline = time.monotonic() + limit
            seen = 0
            while seen < count and time.monotonic() < deadline:
                connection.settimeout(max(0.1, deadline - time.monotonic()))
                try:
                    message = json.loads(connection.recv())
                except Exception:
                    break
                if message.get("op") == "publish" and message.get("topic") == topic:
                    seen += 1
                    yield message.get("msg", {}) or {}
            connection.send(
                json.dumps({"op": "unsubscribe", "topic": topic, "id": subscription})
            )
        finally:
            connection.close()

    def move_to_charging_station(self, guid: str) -> dict[str, Any]:
        """Dock to a charging station, base only.

        Unlike Ability's Drive to Charging Station block, this runs the MiR's own
        docking mission and leaves it charging rather than paused with an aborted
        queue. Requires the arm to already be parked.
        """
        return self.call_service("/er/mobile/move_to_charging_station", {"data": guid})


def settle_on_charge(
    ros: "AbilityRosClient",
    mir: "MirClient",
    log: Callable[[str], None] | None = None,
    *,
    settle_s: float = 25.0,
    attempts: int = 2,
    dock_timeout: float = 150.0,
    charging_station_guid: str = "",
) -> bool:
    """Leave the cell charging, and wait long enough to catch the delayed abort.

    Ability tears down the MiR docking mission after its program ends, and that abort
    can land half a minute late: the base reads as charging, then flips to Pause with
    "Aborted - User Request" and stops charging. A single read right after the program
    finishes therefore passes and then becomes untrue, so this insists on charging
    holding for a settling window, and redocks through the MiR's own mission if it
    does not.

    Pass ``charging_station_guid`` to redock to a specific station; without it the
    first station the controller reports is used, which is correct on a single-charger
    cell and would be a guess on any other.
    """
    say = log or (lambda _message: None)
    for attempt in range(1, attempts + 1):
        stable_until = time.monotonic() + settle_s
        broke = False
        while time.monotonic() < stable_until:
            if not ros.is_charging() or mir_pause_reason(mir.status()):
                broke = True
                break
            time.sleep(2.0)
        if not broke:
            return True
        if attempt == attempts:
            break
        say(f"charging stopped within {settle_s:.0f}s of the leg finishing; redocking over ROS")
        guid = charging_station_guid or next(iter(ros.charging_stations()), "")
        if not guid:
            return False
        ros.move_to_charging_station(guid)
        deadline = time.monotonic() + dock_timeout
        while time.monotonic() < deadline:
            if ros.is_charging():
                break
            time.sleep(3.0)
    return ros.is_charging() and not mir_pause_reason(mir.status())


def _docker_module_names(message: Any) -> list[str]:
    """Pull module names out of whatever shape ``/docker_backend/modules`` publishes."""
    items: Any = message
    if isinstance(message, dict):
        items = (
            message.get("modules")
            or message.get("data")
            or message.get("names")
            or message.get("response")
            or []
        )
        if isinstance(items, dict):
            items = items.get("data") or list(items.values())
    names: list[str] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, str) and item:
                names.append(item)
            elif isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("id")
                    or item.get("module")
                    or item.get("a")
                    or ""
                )
                if name:
                    names.append(str(name))
    return names


def _mir_basic_auth(username: str, password: str) -> str:
    """MiR expects Basic base64(username:sha256hex(password))."""
    digest = hashlib.sha256(password.encode()).hexdigest()
    token = base64.b64encode(f"{username}:{digest}".encode()).decode()
    return f"Basic {token}"


def env_file_candidates() -> list[Path]:
    """Where a MiR credentials file is looked for, in order.

    ``MIR250_ENV_FILE`` wins, then a per-user file, then the working directory. Keeping
    the MiR password out of the repository is the point, so no path inside the package
    is ever consulted.
    """
    explicit = os.environ.get("MIR250_ENV_FILE")
    candidates = [Path(explicit)] if explicit else []
    candidates.append(Path.home() / ".alab_control" / "mir250.env")
    candidates.append(Path.cwd() / ".env")
    return candidates


def load_env(path: str | Path | None = None) -> None:
    """Load KEY=VALUE lines from a gitignored env file into the environment.

    Existing environment variables win, so a shell override or a value already set by
    the AlabOS process still applies.
    """
    candidates = [Path(path)] if path else env_file_candidates()
    for env_file in candidates:
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return


def mir_client_from_env(**kwargs: Any) -> MirClient:
    """MirClient authenticated from MIR_USERNAME and MIR_PASSWORD.

    Without a password the client still works for GET /status, which is the only
    unauthenticated endpoint -- and which is where battery_percentage lives, so an
    unauthenticated client is enough for the battery policy.
    """
    load_env()
    password = os.environ.get("MIR_PASSWORD")
    username = os.environ.get("MIR_USERNAME", "admin")
    if not password:
        return MirClient(**kwargs)
    return MirClient(username=username, password=password, **kwargs)

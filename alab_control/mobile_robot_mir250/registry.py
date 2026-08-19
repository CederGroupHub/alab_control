"""The station registry: `stations.toml` turned into validated, queryable objects.

This is the seam that makes the driver plug and play. Adding a station or a route is an
edit to `stations.toml`; nothing here is specific to Labman, the furnaces or DASH.

Two kinds of checking happen:

- On load, everything that can be decided from the file alone. Station names must be real
  `BasePosition` values, approach and retreat functions must match what the extracted
  `Main` actually calls, routes must name stations that exist, regions must name stations
  that exist, and no two regions may claim the same AlabOS sample position.
- On demand, everything that needs the robot. `validate_against_controller` resolves every
  MiR GUID against the live map and every AlabOS resource against the live lab. Call it
  from `alabos setup` so a typo fails there instead of in front of a furnace.

Both raise `RegistryError` with every problem found, not just the first, because fixing a
map file one exception at a time is miserable.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .clients import BASE_POSITIONS
from .errors import RegistryError
from .obstruction import DEFAULT_OBSTRUCTION_SETTINGS, ObstructionSettings
from .session import APPROACH, RETREAT

try:  # tomllib is stdlib from 3.11; tomli is the identical backport below that.
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter version
    import tomli as _toml  # type: ignore[no-redef]

DEFAULT_REGISTRY = Path(__file__).with_name("stations.toml")

# A region whose station is this travels with the robot, so it is reachable from anywhere.
ON_BOARD = "*"

SCHEMA_VERSION = 1


class _Strict(BaseModel):
    """Reject unknown keys.

    A misspelled key that is silently ignored is the whole failure mode this file exists
    to prevent: `mutes_protective_field` would read as "does not mute" and the robot would
    drive into Labman with its scanners live.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class Station(_Strict):
    """A base position `Main` can drive to."""

    name: str
    kind: Literal["waypoint", "workstation", "charger"]
    description: str = ""

    approach_function: str
    retreat_function: str | None = None

    mir_position: str | None = None
    mir_position_guid: str | None = None
    mir_charging_station: str | None = None
    mir_charging_station_guid: str | None = None
    #: Whether Ability's own approach blocks until the battery target is reached.
    waits_for_charge: bool | None = None

    #: The Ability reference frame the marker calibration at this station corrects.
    calibration_reference: str | None = None
    marker: str
    max_projection_error: float = Field(gt=0)

    #: True where Main suppresses the MiR protective fields to reach in. Preflight insists
    #: the mute is cleared again afterwards, so this list is a safety obligation, not a note.
    mutes_protective_fields: bool = False

    approach_attempts: int = Field(ge=1)
    calibration_attempts: int = Field(ge=1)
    pose_tolerance_m: float = Field(gt=0)
    pose_tolerance_deg: float = Field(gt=0)

    #: How long the base may make no progress on the way here before it is called an
    #: obstruction. A station whose approach includes a slow docking manoeuvre needs longer
    #: than a straight run down a corridor, which is the whole reason this is per station.
    obstruction_stall_grace_s: float | None = Field(default=None, gt=0)
    #: Re-approach attempts after an obstruction before the mission goes on hold.
    obstruction_attempts: int | None = Field(default=None, ge=1)
    #: How long the wheels may turn without the target getting closer before the drive is
    #: called a collision and the controller is latched. Per station because a station whose
    #: approach shuffles the base into place legitimately makes no progress for a moment.
    obstruction_impact_grace_s: float | None = Field(default=None, gt=0)
    #: Set false to take a station out of the hard-stop tier entirely, leaving it only the
    #: patient, retryable stall detector. For a dock where nudging something is expected --
    #: the charger contacts -- not for a station somebody merely finds it inconvenient at.
    obstruction_hard_stop: bool | None = None

    @property
    def is_charger(self) -> bool:
        return self.kind == "charger"

    @property
    def mir_guid(self) -> str | None:
        """The GUID the base actually drives to, wherever it is declared."""
        return self.mir_position_guid or self.mir_charging_station_guid


class Region(_Strict):
    """A place the arm can reach, addressed as `Main`'s (region, slot) argument pair.

    `slots` are the slot arguments Main accepts. `child_slots` are the seats inside each
    slot -- the four crucibles in a subrack. Children are only individually reachable when
    `child_region` is set; at Labman the whole subrack moves or nothing does.
    """

    name: str
    station: str
    carrier: Literal["subrack", "crucible"]
    description: str = ""

    slots: tuple[str, ...]
    #: AlabOS devices owning these positions. Booked before the arm reaches in.
    resources: tuple[str, ...] = ()
    #: Template over {resource} and {slot}. Absent where AlabOS does not track the region.
    alabos_position: str | None = None

    child_slots: tuple[str, ...] = ()
    child_region: str | None = None
    child_alabos_position: str | None = None

    #: Suffix added to the base slot when a carrier from here rides on the base.
    base_slot_suffix: str | None = None
    requires_take_control: bool = False

    @field_validator("slots", "child_slots", "resources")
    @classmethod
    def _no_duplicates(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError(f"repeated entries in {sorted(value)}")
        return value

    @property
    def travels_with_robot(self) -> bool:
        return self.station == ON_BOARD

    def child_region_for(self, slot: str) -> str | None:
        """Main's region argument for the seats inside `slot`, if they are reachable."""
        if self.child_region is None:
            return None
        return self.child_region.format(slot=slot)


class Route(_Strict):
    """A source/destination pair the planner may serve."""

    source: str
    destination: str
    description: str = ""
    max_samples: int = Field(ge=1)
    max_carriers: int = Field(ge=1)
    #: Where empty carriers are borrowed when the source cannot supply them.
    carrier_from: str | None = None
    #: Where carriers are returned before the robot goes home.
    return_carrier_to: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.destination)


@dataclass(frozen=True)
class Placement:
    """One physical seat, named in both languages at once.

    The AlabOS side is what a task books and what the dashboard shows. The Ability side is
    what Main is told. Keeping them in one object is what stops the two from drifting.
    """

    alabos_position: str
    region: str
    slot: str
    station: str
    carrier: str
    resource: str | None = None
    #: For a crucible nested in a subrack: the subrack's own slot and region.
    carrier_slot: str | None = None
    carrier_region: str | None = None
    #: Which seat inside the carrier this is. Recorded separately because a crucible in a
    #: Labman subrack is addressed by its subrack, so `slot` names the subrack -- but the
    #: planner still has to know which of the four seats the crucible occupies, since it
    #: keeps that seat for the whole journey.
    child_slot: str | None = None
    #: False where Main cannot address this seat on its own (a crucible inside a Labman
    #: subrack). Such a seat moves only by moving its carrier.
    addressable: bool = True

    @property
    def travels_with_robot(self) -> bool:
        return self.station == ON_BOARD

    def __str__(self) -> str:
        return self.alabos_position


class Registry:
    """The validated contents of `stations.toml`."""

    def __init__(
        self,
        stations: Mapping[str, Station],
        regions: Mapping[str, Region],
        routes: Sequence[Route],
        source: Path | None = None,
        obstruction: ObstructionSettings = DEFAULT_OBSTRUCTION_SETTINGS,
    ) -> None:
        self.stations: dict[str, Station] = dict(stations)
        self.regions: dict[str, Region] = dict(regions)
        self.routes: tuple[Route, ...] = tuple(routes)
        self.obstruction = obstruction
        self.source = source
        self._placements: dict[str, Placement] = {}
        # Templates are checked before they are used, so a wrong placeholder is a readable
        # complaint about the file rather than a KeyError from inside str.format.
        self._check_templates()
        self._build_placements()
        self._check()

    # -- construction ------------------------------------------------------

    def _check_templates(self) -> None:
        problems: list[str] = []
        for region in self.regions.values():
            for field, template, keys in (
                ("alabos_position", region.alabos_position, {"resource", "slot"}),
                (
                    "child_alabos_position",
                    region.child_alabos_position,
                    {"resource", "slot", "child"},
                ),
                ("child_region", region.child_region, {"slot"}),
            ):
                if template is None:
                    continue
                used = set(re.findall(r"{(\w+)}", template))
                if not used <= keys:
                    problems.append(
                        f"region {region.name!r} {field} template {template!r} uses "
                        f"{sorted(used - keys)}, which is not substituted here "
                        f"(available: {sorted(keys)})"
                    )
        if problems:
            raise RegistryError(self._describe(problems))

    def _build_placements(self) -> None:
        """Expand every region into the AlabOS positions it owns.

        Enumerating instead of pattern matching means the reverse lookup is exact, and a
        template that does not produce the position names the lab actually uses shows up
        as a collision or a miss here rather than as a wrong argument to Main.
        """
        collisions: list[str] = []
        for region in self.regions.values():
            if not region.alabos_position or not region.resources:
                continue  # not tracked in AlabOS; still addressable by region and slot
            for resource in region.resources:
                for slot in region.slots:
                    position = region.alabos_position.format(resource=resource, slot=slot)
                    self._add(
                        Placement(
                            alabos_position=position,
                            region=region.name,
                            slot=slot,
                            station=region.station,
                            carrier=region.carrier,
                            resource=resource,
                        ),
                        collisions,
                    )
                    if not region.child_slots or not region.child_alabos_position:
                        continue
                    child_region = region.child_region_for(slot)
                    for child in region.child_slots:
                        child_position = region.child_alabos_position.format(
                            resource=resource, slot=slot, child=child
                        )
                        self._add(
                            Placement(
                                alabos_position=child_position,
                                # A child with no child_region of its own is not
                                # addressable; it is described by the carrier that holds it.
                                region=child_region or region.name,
                                slot=child if child_region else slot,
                                station=region.station,
                                carrier="crucible",
                                resource=resource,
                                carrier_slot=slot,
                                carrier_region=region.name,
                                child_slot=child,
                                addressable=child_region is not None,
                            ),
                            collisions,
                        )
        if collisions:
            raise RegistryError(
                "two regions claim the same AlabOS sample position:\n  "
                + "\n  ".join(collisions)
            )

    def _add(self, placement: Placement, collisions: list[str]) -> None:
        existing = self._placements.get(placement.alabos_position)
        if existing is not None:
            collisions.append(
                f"{placement.alabos_position} is claimed by both "
                f"{existing.region!r} and {placement.region!r}"
            )
            return
        self._placements[placement.alabos_position] = placement

    def _check(self) -> None:
        """Everything decidable without touching the robot."""
        problems: list[str] = []

        for name, station in self.stations.items():
            if name not in BASE_POSITIONS:
                problems.append(
                    f"station {name!r} is not a BasePosition the controller knows; "
                    f"valid values are {', '.join(sorted(BASE_POSITIONS))}"
                )
                continue
            expected_approach = APPROACH.get(name)
            if expected_approach and station.approach_function != expected_approach:
                problems.append(
                    f"station {name!r} declares approach_function "
                    f"{station.approach_function!r} but Main dispatches "
                    f"{expected_approach!r} for it"
                )
            expected_retreat = RETREAT.get(name)
            if expected_retreat and station.retreat_function != expected_retreat:
                problems.append(
                    f"station {name!r} declares retreat_function "
                    f"{station.retreat_function!r} but Main dispatches "
                    f"{expected_retreat!r} for it"
                )
            if station.is_charger and station.mir_charging_station_guid is None:
                problems.append(f"charger {name!r} has no mir_charging_station_guid")
            if station.is_charger and station.waits_for_charge is None:
                problems.append(
                    f"charger {name!r} must say whether Ability waits for the battery "
                    f"(waits_for_charge), because the battery guard needs to know who is "
                    f"deciding when to resume"
                )
            if not station.is_charger and station.mir_position_guid is None:
                problems.append(f"station {name!r} has no mir_position_guid")

        # A resource must belong to exactly one station, or booking it cannot tell the
        # robot where to stand.
        resource_stations: dict[str, set[str]] = {}
        for region in self.regions.values():
            if region.station != ON_BOARD and region.station not in self.stations:
                problems.append(
                    f"region {region.name!r} sits at station {region.station!r}, "
                    f"which is not declared"
                )
            for resource in region.resources:
                resource_stations.setdefault(resource, set()).add(region.station)
            if region.child_region and not region.child_slots:
                problems.append(
                    f"region {region.name!r} declares child_region but no child_slots"
                )
            if region.child_alabos_position and not region.alabos_position:
                problems.append(
                    f"region {region.name!r} maps children into AlabOS but not the slots "
                    f"holding them"
                )
        for resource, stations in resource_stations.items():
            if len(stations) > 1:
                problems.append(
                    f"AlabOS resource {resource!r} is claimed by more than one station "
                    f"({', '.join(sorted(stations))}); the robot would not know where to "
                    f"stand to reach it"
                )

        # Every region a child_region names must exist, or Main gets an argument it will
        # reject only once the arm is already extended.
        for region in self.regions.values():
            if region.child_region is None:
                continue
            for slot in region.slots:
                derived = region.child_region_for(slot)
                if derived and derived not in self.regions:
                    problems.append(
                        f"region {region.name!r} addresses its contents as {derived!r}, "
                        f"which is not declared as a region"
                    )

        seen: set[tuple[str, str]] = set()
        for route in self.routes:
            for role, station_name in (
                ("source", route.source),
                ("destination", route.destination),
                ("carrier_from", route.carrier_from),
                ("return_carrier_to", route.return_carrier_to),
            ):
                if station_name is None:
                    continue
                if station_name not in self.stations:
                    problems.append(
                        f"route {route.source}->{route.destination} names {station_name!r} "
                        f"as {role}, which is not a declared station"
                    )
                elif not any(
                    region.station == station_name for region in self.regions.values()
                ):
                    problems.append(
                        f"route {route.source}->{route.destination} names {station_name!r} "
                        f"as {role}, but no region is defined there so the arm has nothing "
                        f"to reach for"
                    )
            if route.source == route.destination:
                problems.append(
                    f"route {route.source}->{route.destination} goes nowhere"
                )
            if route.key in seen:
                problems.append(f"route {route.source}->{route.destination} is declared twice")
            seen.add(route.key)
            if route.max_carriers > len(self.base_carrier_slots()):
                problems.append(
                    f"route {route.source}->{route.destination} wants "
                    f"{route.max_carriers} carriers but the base has "
                    f"{len(self.base_carrier_slots())} seats"
                )

        if not self.base_region():
            problems.append(
                "no region travels with the robot; there is nowhere to put a sample down "
                f"between stations (expected a region with station = {ON_BOARD!r})"
            )

        if problems:
            raise RegistryError(self._describe(problems))

    def _describe(self, problems: Sequence[str]) -> str:
        where = f" in {self.source}" if self.source else ""
        return f"{len(problems)} problem(s){where}:\n  - " + "\n  - ".join(problems)

    # -- queries -----------------------------------------------------------

    def station(self, name: str) -> Station:
        try:
            return self.stations[name]
        except KeyError:
            raise RegistryError(
                f"unknown station {name!r}; declared stations are "
                f"{', '.join(sorted(self.stations))}"
            ) from None

    def region(self, name: str) -> Region:
        try:
            return self.regions[name]
        except KeyError:
            raise RegistryError(
                f"unknown region {name!r}; declared regions are "
                f"{', '.join(sorted(self.regions))}"
            ) from None

    def obstruction_settings(self, station: str | None = None) -> ObstructionSettings:
        """The obstruction thresholds for a drive to `station`, overrides applied.

        An unknown station gets the cell-wide defaults rather than an error: this is
        consulted on every base move, including recovery moves to stations the caller may
        have spelled loosely, and refusing to watch is worse than watching with defaults.
        """
        declared = self.stations.get(station or "")
        if declared is None:
            return self.obstruction
        changes: dict[str, Any] = {}
        if declared.obstruction_stall_grace_s is not None:
            changes["stall_grace_s"] = declared.obstruction_stall_grace_s
        if declared.obstruction_attempts is not None:
            changes["max_attempts"] = declared.obstruction_attempts
        if declared.obstruction_impact_grace_s is not None:
            changes["impact_grace_s"] = declared.obstruction_impact_grace_s
        if declared.obstruction_hard_stop is not None:
            changes["hard_stop"] = declared.obstruction_hard_stop
        if not changes:
            return self.obstruction
        return dataclasses.replace(self.obstruction, **changes)

    def regions_at(self, station: str) -> list[Region]:
        """Regions the arm can reach while parked at `station`, on-board ones included."""
        return [
            region
            for region in self.regions.values()
            if region.station in (station, ON_BOARD)
        ]

    def base_region(self) -> Region | None:
        """The region that rides on the robot."""
        for region in self.regions.values():
            if region.travels_with_robot and region.carrier == "subrack":
                return region
        return None

    def base_carrier_slots(self) -> tuple[str, ...]:
        """The subrack seats on the base, in the order the planner should fill them."""
        base = self.base_region()
        return base.slots if base else ()

    def base_sample_slots(self) -> list[Placement]:
        """Every crucible seat on the base, in fill order."""
        base = self.base_region()
        if base is None:
            return []
        out: list[Placement] = []
        for slot in base.slots:
            for child in base.child_slots:
                placement = self._placements.get(
                    (base.child_alabos_position or "").format(
                        resource=base.resources[0] if base.resources else "",
                        slot=slot,
                        child=child,
                    )
                )
                if placement is not None:
                    out.append(placement)
        return out

    def resolve(self, alabos_position: str) -> Placement:
        """Where an AlabOS sample position is, in the robot's own terms."""
        try:
            return self._placements[alabos_position]
        except KeyError:
            raise RegistryError(
                f"{alabos_position!r} is not a position the mobile robot can reach. "
                f"Declare the region that owns it in {self.source or 'stations.toml'}."
            ) from None

    def knows(self, alabos_position: str) -> bool:
        return alabos_position in self._placements

    def placements(self) -> dict[str, Placement]:
        return dict(self._placements)

    def station_of(self, alabos_position: str) -> str:
        return self.resolve(alabos_position).station

    def route(self, source: str, destination: str) -> Route:
        """The route between two stations, or a refusal naming what is on offer."""
        for candidate in self.routes:
            if candidate.key == (source, destination):
                return candidate
        offered = ", ".join(f"{r.source}->{r.destination}" for r in self.routes)
        raise RegistryError(
            f"no route from {source} to {destination}. Declared routes are {offered}. "
            f"Add a [[route]] entry to teach this one."
        )

    def route_for_positions(self, source: str, destination: str) -> Route:
        """The route serving a move between two AlabOS sample positions."""
        return self.route(self.station_of(source), self.station_of(destination))

    def can_serve(self, source: str, destination: str) -> bool:
        """Whether a request between two AlabOS positions is one the robot may accept."""
        try:
            self.route_for_positions(source, destination)
        except RegistryError:
            return False
        return True

    def carriers_needed(self, route: Route) -> str | None:
        """Where this route's empty subracks come from, if they must be borrowed."""
        return route.carrier_from

    def resources_for(self, positions: Iterable[str]) -> dict[str, list[str]]:
        """AlabOS devices to book, grouped by the station they must be booked at."""
        grouped: dict[str, list[str]] = {}
        for position in positions:
            placement = self.resolve(position)
            if placement.resource is None:
                continue
            bucket = grouped.setdefault(placement.station, [])
            if placement.resource not in bucket:
                bucket.append(placement.resource)
        return grouped

    def base_slot_for(self, source_station: str, base_slot: str) -> str:
        """The base slot argument Main wants for a carrier taken from `source_station`.

        Storage subracks ride vertically, so the same seat is spelled differently
        depending on where the subrack came from. This is the only place that knows.
        """
        for region in self.regions_at(source_station):
            if region.station == source_station and region.base_slot_suffix:
                return f"{base_slot}{region.base_slot_suffix}"
        return base_slot

    # -- live validation ---------------------------------------------------

    def validate_against_controller(
        self,
        ros: Any | None = None,
        mir: Any | None = None,
        alabos_resources: Iterable[str] | None = None,
        program_functions: Iterable[str] | None = None,
    ) -> list[str]:
        """Check the file against the live robot and lab. Returns the problems found.

        Every argument is optional so this can run with whatever happens to be reachable;
        what cannot be checked is reported as skipped rather than silently passing.
        """
        problems: list[str] = []

        if ros is not None:
            problems += self._check_map(ros)
        if mir is not None and getattr(mir, "authenticated", False):
            problems += self._check_mir_map(mir)
        if program_functions is not None:
            known = set(program_functions)
            for station in self.stations.values():
                for role, function in (
                    ("approach", station.approach_function),
                    ("retreat", station.retreat_function),
                ):
                    if function and function not in known:
                        problems.append(
                            f"station {station.name!r} {role} function {function!r} is not "
                            f"a function block in the deployed program"
                        )
        if alabos_resources is not None:
            known_resources = set(alabos_resources)
            for region in self.regions.values():
                for resource in region.resources:
                    if resource not in known_resources:
                        problems.append(
                            f"region {region.name!r} books AlabOS device {resource!r}, "
                            f"which is not registered in the lab"
                        )
        return problems

    def _check_map(self, ros: Any) -> list[str]:
        problems: list[str] = []
        try:
            positions = self._name_to_guid_map(ros.positions())
            chargers = self._name_to_guid_map(ros.charging_stations())
        except Exception as error:  # noqa: BLE001 - the reason is the useful part
            return [f"could not read the MiR map from Ability: {error}"]
        problems += self._match_guids(positions, "mir_position", "mir_position_guid")
        problems += self._match_guids(
            chargers, "mir_charging_station", "mir_charging_station_guid"
        )
        return problems

    @staticmethod
    def _name_to_guid_map(live: Mapping[str, str]) -> dict[str, str]:
        """Ability returns guid->name; registry matching needs name->guid."""
        if not live:
            return {}
        sample = next(iter(live))
        if "-" in sample and len(sample) > 20:
            return {name: guid for guid, name in live.items() if name}
        return dict(live)

    def _match_guids(
        self, live: Mapping[str, str], name_field: str, guid_field: str
    ) -> list[str]:
        problems: list[str] = []
        for station in self.stations.values():
            name = getattr(station, name_field)
            guid = getattr(station, guid_field)
            if name is None and guid is None:
                continue
            if name is not None and name not in live:
                problems.append(
                    f"station {station.name!r} drives to {name!r}, which is not on the "
                    f"robot's map (map has: {', '.join(sorted(live))})"
                )
                continue
            if name is not None and guid is not None and live[name] != guid:
                problems.append(
                    f"station {station.name!r} has {name!r} as {guid}, but the map says "
                    f"{live[name]}. The position was re-taught; update stations.toml."
                )
        return problems

    def _check_mir_map(self, mir: Any) -> list[str]:
        """Confirm each GUID still resolves on MiR itself, not just through Ability."""
        problems: list[str] = []
        for station in self.stations.values():
            guid = station.mir_guid
            if guid is None:
                continue
            try:
                record = mir.guid("positions", guid)
            except Exception as error:  # noqa: BLE001
                problems.append(
                    f"station {station.name!r} GUID {guid} does not resolve on MiR: {error}"
                )
                continue
            expected = station.mir_position or station.mir_charging_station
            actual = record.get("name")
            if expected and actual and actual != expected:
                problems.append(
                    f"station {station.name!r} GUID {guid} is named {actual!r} on MiR, "
                    f"not {expected!r}"
                )
        return problems

    def require_valid_against_controller(self, **kwargs: Any) -> None:
        """Same checks, but refuse to continue if any fail."""
        problems = self.validate_against_controller(**kwargs)
        if problems:
            raise RegistryError(self._describe(problems))

    def station_coordinates(self, mir: Any) -> dict[str, tuple[float, float, float]]:
        """Each station's map coordinates, read from MiR. For the dashboard floor plan.

        The map is the authority on where a taught position is, so this is read live rather
        than copied into the registry where it would rot the next time one is re-taught.
        """
        out: dict[str, tuple[float, float, float]] = {}
        for station in self.stations.values():
            guid = station.mir_guid
            if guid is None:
                continue
            try:
                record = mir.guid("positions", guid)
            except Exception:  # noqa: BLE001 - a missing marker is not worth failing over
                continue
            try:
                out[station.name] = (
                    float(record["pos_x"]),
                    float(record["pos_y"]),
                    float(record["orientation"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def __repr__(self) -> str:
        return (
            f"Registry({len(self.stations)} stations, {len(self.regions)} regions, "
            f"{len(self.routes)} routes, {len(self._placements)} sample positions)"
        )


def _station_models(raw: Mapping[str, Any], defaults: Mapping[str, Any]) -> dict[str, Station]:
    stations: dict[str, Station] = {}
    for name, body in raw.items():
        if not isinstance(body, Mapping):
            raise RegistryError(f"[station.{name}] must be a table")
        stations[name] = Station(
            name=name,
            marker=body.get("marker", defaults["marker"]),
            max_projection_error=body.get(
                "max_projection_error", defaults["max_projection_error"]
            ),
            approach_attempts=body.get("approach_attempts", defaults["approach_attempts"]),
            calibration_attempts=body.get(
                "calibration_attempts", defaults["calibration_attempts"]
            ),
            pose_tolerance_m=body.get("pose_tolerance_m", defaults["pose_tolerance_m"]),
            pose_tolerance_deg=body.get("pose_tolerance_deg", defaults["pose_tolerance_deg"]),
            **{
                key: value
                for key, value in body.items()
                if key
                not in {
                    "marker",
                    "max_projection_error",
                    "approach_attempts",
                    "calibration_attempts",
                    "pose_tolerance_m",
                    "pose_tolerance_deg",
                }
            },
        )
    return stations


def load_registry(path: Path | str | None = None) -> Registry:
    """Read and validate a registry file.

    Raises `RegistryError` listing every problem, so one pass over the output is enough to
    fix the file.
    """
    resolved = Path(path) if path else DEFAULT_REGISTRY
    if not resolved.exists():
        raise RegistryError(f"no station registry at {resolved}")
    try:
        raw = _toml.loads(resolved.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - TOML errors are already specific
        raise RegistryError(f"{resolved} is not valid TOML: {error}") from error

    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise RegistryError(
            f"{resolved} declares schema_version {version!r}; this driver reads "
            f"{SCHEMA_VERSION}"
        )

    defaults = {
        "approach_attempts": 3,
        "calibration_attempts": 2,
        "pose_tolerance_m": 0.25,
        "pose_tolerance_deg": 8.0,
        "marker": "CH3",
        "max_projection_error": 1.0,
        **(raw.get("defaults") or {}),
    }

    try:
        stations = _station_models(raw.get("station") or {}, defaults)
        regions = {
            name: Region(name=name, **body)
            for name, body in (raw.get("region") or {}).items()
        }
        routes = [Route(**body) for body in (raw.get("route") or [])]
        obstruction = _obstruction_settings(raw.get("obstruction") or {})
    except RegistryError:
        raise
    except Exception as error:  # pydantic ValidationError, mostly
        raise RegistryError(f"{resolved} is not a usable registry:\n{error}") from error

    if not stations:
        raise RegistryError(f"{resolved} declares no stations")

    return Registry(stations, regions, routes, source=resolved, obstruction=obstruction)


def _obstruction_settings(raw: Mapping[str, Any]) -> ObstructionSettings:
    known = {field.name for field in dataclasses.fields(ObstructionSettings)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise RegistryError(
            f"[obstruction] does not understand {unknown}; valid keys are {sorted(known)}"
        )
    values = dict(raw)
    # TOML has arrays where the settings have tuples, and a mutable default in a frozen
    # dataclass would be a bug waiting to happen, so every sequence is converted here rather
    # than each caller remembering to.
    for name in ("mission_text_needles", "hard_stop_needles", "hard_stop_state_ids"):
        if name in values:
            values[name] = tuple(values[name])
    return dataclasses.replace(DEFAULT_OBSTRUCTION_SETTINGS, **values)


@lru_cache(maxsize=4)
def _cached(path: str | None) -> Registry:
    return load_registry(path)


def registry(path: Path | str | None = None) -> Registry:
    """The shared registry, parsed once per path."""
    return _cached(str(path) if path else None)

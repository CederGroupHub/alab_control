"""Everything about the mobile robot that can be decided without a robot.

Three groups, and the reason each exists:

- **State classification and the `Main` argument contract.** Ported from the handoff's
  `test_logic.py`. These are a record of what the controller actually does, worked out
  against the real cell, as much as a check on the code.
- **The station registry.** A bad `stations.toml` must fail here rather than in front of a
  furnace, so each way of getting it wrong has a test that proves the error is raised and
  readable.
- **Missions, cancellation and the battery policy**, driven through the real driver with a
  fake cell underneath. The promises being checked are the ones made to the user: a cancelled
  task docks and never repeats a leg, a suspended mission resumes where it stopped, and the
  robot never waits on another instrument with a flat battery.

    python -m pytest tests/test_mir250_logic.py -q
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from alab_control.mobile_robot_mir250 import (
    ALL_STATES,
    APPROACH,
    ATTENDED_STATES,
    BASE_POSITIONS,
    BUSY_STATES,
    ERROR_STATES,
    IDLE_STATES,
    MAIN_ARGUMENT_KEYS,
    RETREAT,
    STATE_REQUESTS,
    BatteryPolicy,
    BatterySuspend,
    LegKind,
    MaintenanceRequired,
    Mission,
    MissionCancelled,
    Pose,
    RegistryError,
    SampleMove,
    StationPoses,
    classify_failure,
    is_error_state,
    load_registry,
    main_arguments,
    mir_pause_reason,
    pose_dict,
    registry,
    transfer,
    travel,
)
from alab_control.mobile_robot_mir250.ability_xml import (
    ProgramArchive,
    call_instruction,
    compact,
    default_archive_path,
    function_block,
    wait_instruction,
)
from alab_control.mobile_robot_mir250.mock import MockMiR250
from alab_control.mobile_robot_mir250.registry import DEFAULT_REGISTRY

# ==========================================================================
# Ability state classification
# ==========================================================================


def test_every_state_is_classified() -> None:
    """No controller state may fall through every bucket.

    An unclassified state is the dangerous case: the wait loop would neither treat it as a
    failure nor as completion, and would sit there until the timeout.
    """
    handled = set(IDLE_STATES) | set(ERROR_STATES) | set(BUSY_STATES) | set(ATTENDED_STATES)
    handled.add("Executing")
    assert [state for state in ALL_STATES if state not in handled] == []


def test_attended_states_are_not_confused_with_errors_or_idle() -> None:
    """Joystick Active and Paused both mean a person is driving.

    Neither is an error, and neither may be treated as completion, or an unattended run
    would carry on while someone else is moving the robot.
    """
    for state in ATTENDED_STATES:
        assert not is_error_state(state), state
        assert state not in IDLE_STATES, state


def test_error_states_are_detected() -> None:
    for state in ERROR_STATES:
        assert is_error_state(state), state
    for state in (*IDLE_STATES, "Executing"):
        assert not is_error_state(state), state


def test_unknown_error_wording_is_still_an_error() -> None:
    """Firmware wording may change; anything mentioning an error is treated as one."""
    assert is_error_state("Some New Error State")
    assert is_error_state("execution error")
    assert not is_error_state("")


def test_recovery_is_busy_not_idle_and_not_an_error() -> None:
    """Recovery is a stranded programming token, and needs force_token_release.

    It must not be classified as idle, or preflight would start a program the controller
    will refuse, and not as an error, since /er/system/stop cannot process a Stop there.
    """
    assert "Recovery" in BUSY_STATES
    assert "Recovery" not in IDLE_STATES
    assert not is_error_state("Recovery")


def test_state_requests_exclude_idle() -> None:
    """PUT /status accepts only Executing, Paused and Ready. Idle is always a 400."""
    assert STATE_REQUESTS == ("Executing", "Paused", "Ready")


# ==========================================================================
# Main's argument contract
# ==========================================================================


def test_main_arguments_always_sends_all_five() -> None:
    """Main reads all five keys on startup and throws if one is missing."""
    args = main_arguments(target_base_position="Home")
    assert set(args) == set(MAIN_ARGUMENT_KEYS)
    assert args["target_base_position"] == "Home"
    assert all(
        args[key] == "None" for key in MAIN_ARGUMENT_KEYS if key != "target_base_position"
    )


def test_main_arguments_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="target_position"):
        main_arguments(target_position="Home")


def test_main_arguments_stringifies_values() -> None:
    """Every argument is sent as a string, since the type id used is 0."""
    assert main_arguments(source_slot=3)["source_slot"] == "3"


def test_pick_and_place_needs_all_four_slot_arguments() -> None:
    """Main only calls PickHandler when all four are set, so three of four does nothing."""
    args = main_arguments(source_region="A", source_slot="1", destination_region="B")
    assert args["destination_slot"] == "None"


def test_a_travel_leg_sends_only_the_base_argument() -> None:
    args = travel("BFT", "going to the furnaces").main_arguments()
    assert args["target_base_position"] == "BFT"
    assert args["source_region"] == "None"


def test_a_transfer_leg_never_sends_a_base_argument() -> None:
    """A leg that set both would make Main move the base and then the arm in one call,
    which is exactly the coupling the leg model exists to break."""
    args = transfer(
        "BFT", "placing a crucible", "ROBOT_BASE/SubRackA", "1", "BFT", "3"
    ).main_arguments()
    assert args["target_base_position"] == "None"
    assert args["destination_slot"] == "3"


def test_a_transfer_leg_without_a_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="source region"):
        transfer("BFT", "nothing", "None", "None", "BFT", "1")


# ==========================================================================
# How a paused MiR should be read
# ==========================================================================


def test_idle_pause_after_a_drive_block_is_harmless() -> None:
    """Ability parks the base in Pause every time it hands it back.

    Refusing to run in that state blocked the station test from starting, even though
    Ability resumes the base itself on the next drive.
    """
    assert (
        mir_pause_reason(
            {"state_text": "Pause", "mission_text": "Waiting for new missions ..."}
        )
        == ""
    )


def test_pause_mid_mission_needs_clearing() -> None:
    reason = mir_pause_reason(
        {"state_text": "Pause", "mission_text": "Aborted - User Request"}
    )
    assert "Aborted - User Request" in reason
    assert "redock" in reason


def test_a_working_mir_is_never_reported_as_paused() -> None:
    for state in ("Executing", "Ready", "Error", ""):
        assert (
            mir_pause_reason(
                {"state_text": state, "mission_text": "Aborted - User Request"}
            )
            == ""
        )


# ==========================================================================
# Station pose reconciliation
# ==========================================================================


def _store(tmp: Path) -> StationPoses:
    """A pose store with no baseline, so each test starts from nothing recorded."""
    return StationPoses(baseline_path=tmp / "baseline.json", runtime_path=tmp / "runtime.json")


def test_first_visit_to_a_station_has_nothing_to_compare(tmp_path: Path) -> None:
    """Saying nothing rather than failing is deliberate: the first visit is how the record
    gets written in the first place."""
    assert _store(tmp_path).check("LABMAN", Pose(0, 0, 0, 0, 0, 0)) == ""


def test_a_repeat_visit_within_tolerance_passes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("LABMAN", Pose(-4.895, -6.269, 0, 0.5748, 0, 0), "first visit")
    assert store.check("LABMAN", Pose(-4.90, -6.20, 0, 0.5748, 0, 0)) == ""


def test_a_station_the_robot_is_nowhere_near_is_reported(tmp_path: Path) -> None:
    """The case worth catching: BasePosition says LABMAN, the robot is at the charger."""
    store = _store(tmp_path)
    store.record("LABMAN", Pose(-4.895, -6.269, 0, 0.5748, 0, 0), "first visit")
    reason = store.check("LABMAN", Pose(-4.325, -2.192, 0, 0.6168, 0, 0))
    assert "LABMAN" in reason
    assert "4.1" in reason or "4.0" in reason


def test_a_station_reached_backwards_is_reported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("LABMAN", Pose(-4.895, -6.269, 0, 0.5748, 0, 0), "first visit")
    assert "180" in store.check("LABMAN", Pose(-4.895, -6.269, 0, 0.5748 + math.pi, 0, 0))


def test_records_survive_a_reload(tmp_path: Path) -> None:
    _store(tmp_path).record("LABMAN", Pose(1.0, 2.0, 0, 0.0, 0, 0), "written")
    reloaded = _store(tmp_path).known("LABMAN")
    assert reloaded is not None
    assert reloaded["x"] == 1.0
    assert reloaded["evidence"] == "written"


def test_the_shipped_baseline_knows_the_two_stations_we_recorded() -> None:
    """The committed baseline is evidence, not a placeholder; losing it would silently
    disable the reconciliation on a fresh checkout."""
    store = StationPoses(runtime_path=Path("nonexistent-runtime.json"))
    assert "LABMAN" in store.stations
    assert store.charger is not None


# ==========================================================================
# Pose arithmetic
# ==========================================================================


def test_pose_yaw_is_the_fourth_transform_element() -> None:
    """GET /transform returns [x, y, z, yaw, _, _] despite the XYZRPY label.

    Confirmed on the robot: 0.6175 rad reads as 35.3799 degrees, matching the MiR's
    reported orientation exactly.
    """
    assert abs(Pose(1.0, 2.0, 0.0, 0.6175, 0.0, 0.0).yaw_deg - 35.3799) < 1e-3


def test_heading_error_wraps_around_180() -> None:
    a = Pose(0, 0, 0, math.radians(179), 0, 0)
    b = Pose(0, 0, 0, math.radians(-179), 0, 0)
    assert abs(a.heading_error_deg(b) - 2.0) < 1e-6


def test_distance_ignores_z() -> None:
    assert abs(Pose(0, 0, 0, 0, 0, 0).distance_to(Pose(3, 4, 99, 0, 0, 0)) - 5.0) < 1e-9


def test_pose_dict_passes_none_through() -> None:
    assert pose_dict(None) is None
    assert pose_dict(Pose(1, 2, 3, 0, 0, 0))["x"] == 1


# ==========================================================================
# The station registry
# ==========================================================================


def test_the_shipped_registry_loads() -> None:
    table = registry()
    assert table.stations and table.regions and table.routes
    assert set(table.stations) <= set(BASE_POSITIONS)


def test_every_alabos_position_the_lab_uses_resolves() -> None:
    """The registry has to know the position names the rest of the lab actually uses.

    Spot-checked against the names in alab_one's device definitions: a rename on either
    side breaks delivery, and this is the cheapest place to notice.
    """
    table = registry()
    for position, region, slot in [
        ("LABMAN_quadrant_1/crucible/SubRackA", "LABMAN", "SubRackA"),
        ("LABMAN_quadrant_4/crucible/SubRackD/4", "LABMAN", "SubRackD"),
        # A TransferRack calls its position group "slot", so its positions are
        # BFT_input_rack/slot/16 and not BFT_input_rack/16. Spelling this the obvious way
        # produces names nothing in the lab has, and the arm only finds out when it reaches.
        ("BFT_input_rack/slot/16", "BFT", "16"),
        ("DASH_input_rack/slot/1", "DASH", "1"),
        ("MOBILE_arm_ALFRED/SubRackB", "ROBOT_BASE", "SubRackB"),
        ("MOBILE_arm_ALFRED/SubRackB/3", "ROBOT_BASE/SubRackB", "3"),
    ]:
        placement = table.resolve(position)
        assert (placement.region, placement.slot) == (region, slot), position


def test_a_crucible_inside_a_labman_subrack_is_not_individually_addressable() -> None:
    """Labman hands over whole subracks. A planner that tried to pick one crucible there
    would send Main an argument pair it cannot serve, so the registry says so up front."""
    assert not registry().resolve("LABMAN_quadrant_1/crucible/SubRackA/2").addressable
    assert registry().resolve("MOBILE_arm_ALFRED/SubRackA/2").addressable


def test_routes_are_a_whitelist_not_a_suggestion() -> None:
    table = registry()
    assert table.can_serve(
        "LABMAN_quadrant_1/crucible/SubRackA/1", "BFT_input_rack/slot/1"
    )
    assert table.can_serve("BFT_input_rack/slot/1", "DASH_input_rack/slot/1")
    # The reverse was never taught, so it must be refused rather than attempted.
    assert not table.can_serve("DASH_input_rack/slot/1", "BFT_input_rack/slot/1")


def test_an_unknown_position_is_refused_with_a_useful_message() -> None:
    with pytest.raises(RegistryError, match="not a position the mobile robot can reach"):
        registry().resolve("DASH_scale/1")


def test_an_untaught_route_names_the_routes_that_do_exist() -> None:
    with pytest.raises(RegistryError, match="Declared routes are"):
        registry().route("LABMAN", "SEMEDS")


def test_storage_subracks_ride_vertically_and_only_storage_ones_do() -> None:
    """The only per-station spelling rule in the cell, and the one place it lives."""
    table = registry()
    assert table.base_slot_for("SRS", "SubRackA") == "SubRackAVertical"
    assert table.base_slot_for("LABMAN", "SubRackA") == "SubRackA"


def test_booking_is_grouped_by_the_station_it_must_happen_at() -> None:
    grouped = registry().resources_for(
        ["LABMAN_quadrant_2/crucible/SubRackA/1", "BFT_input_rack/slot/4"]
    )
    assert grouped == {"LABMAN": ["LABMAN_quadrant_2"], "BFT": ["BFT_input_rack"]}


def test_the_registry_agrees_with_mains_own_dispatch() -> None:
    """A station whose approach function is misnamed would fail after the retreat has
    already happened, which is the expensive moment to find out."""
    for name, station in registry().stations.items():
        if name in APPROACH:
            assert station.approach_function == APPROACH[name], name
        if name in RETREAT:
            assert station.retreat_function == RETREAT[name], name


def test_the_bridge_can_reach_every_station_main_can() -> None:
    """The approach table replaces BaseHandler's dispatch, so it must be no less complete."""
    assert [station for station in BASE_POSITIONS if station not in APPROACH] == []


def test_home_needs_no_retreat() -> None:
    """BaseHandler guards its whole retreat branch with BasePosition != 'Home'."""
    assert "Home" not in RETREAT


# -- the ways a registry can be wrong, and the complaint each produces ------

BAD_REGISTRIES = {
    "an approach function Main does not dispatch": (
        'approach_function = "Go to Labman"',
        'approach_function = "Go to LABMAN"',
        "but Main dispatches",
    ),
    "a misspelled safety key": (
        "mutes_protective_fields = true\n\n[station.BFT]",
        "mutes_protective_field = true\n\n[station.BFT]",
        "extra_forbidden",
    ),
    "a route to a station that does not exist": (
        'source = "BFT"\ndestination = "DASH"',
        'source = "BFT"\ndestination = "MARS"',
        "not a declared station",
    ),
    "a route to a station with nothing to reach": (
        'source = "BFT"\ndestination = "DASH"',
        'source = "BFT"\ndestination = "SEMEDS"',
        "no region is defined there",
    ),
    "more carriers than the base has seats": (
        "max_carriers = 4\ncarrier_from",
        "max_carriers = 9\ncarrier_from",
        "the base has 4 seats",
    ),
    "one resource claimed by two stations": (
        'resources = ["BFT_input_rack"]',
        'resources = ["BFT_input_rack", "MOBILE_arm_ALFRED"]',
        "more than one station",
    ),
    "two regions claiming the same position": (
        'resources = ["DASH_input_rack"]',
        'resources = ["BFT_input_rack"]',
        "claimed by both",
    ),
    "a template placeholder nothing fills": (
        'alabos_position = "{resource}/crucible/{slot}"',
        'alabos_position = "{device}/crucible/{slot}"',
        "not substituted here",
    ),
    "an undeclared child region": (
        'child_region = "ROBOT_BASE/{slot}"',
        'child_region = "BASE/{slot}"',
        "not declared as a region",
    ),
    "a schema this driver cannot read": (
        "schema_version = 1",
        "schema_version = 2",
        "this driver reads 1",
    ),
}


@pytest.mark.parametrize(
    ("old", "new", "expected"), BAD_REGISTRIES.values(), ids=list(BAD_REGISTRIES)
)
def test_a_broken_registry_is_refused_with_an_explanation(
    tmp_path: Path, old: str, new: str, expected: str
) -> None:
    """Each of these is a real way to get the file wrong. The message has to say which."""
    good = DEFAULT_REGISTRY.read_text(encoding="utf-8")
    assert old in good, f"the fixture drifted: {old!r} is no longer in stations.toml"
    path = tmp_path / "stations.toml"
    path.write_text(good.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(RegistryError) as raised:
        load_registry(path)
    assert expected in str(raised.value)


def test_a_missing_registry_says_where_it_looked(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="no station registry at"):
        load_registry(tmp_path / "absent.toml")


# ==========================================================================
# Missions
# ==========================================================================


def _labman_to_bft() -> Mission:
    """The shape of the real thing: fetch two subracks, deliver one crucible, come home."""
    return Mission.build(
        [
            travel("LABMAN", "collecting dosed crucibles from Labman quadrant 1"),
            transfer(
                "LABMAN",
                "loading subrack A onto the base",
                "LABMAN",
                "SubRackA",
                "ROBOT_BASE",
                "SubRackA",
                moves=[
                    SampleMove(
                        "S1",
                        "LABMAN_quadrant_1/crucible/SubRackA/1",
                        "MOBILE_arm_ALFRED/SubRackA/1",
                        "r1",
                    ),
                    SampleMove(
                        "S2",
                        "LABMAN_quadrant_1/crucible/SubRackA/2",
                        "MOBILE_arm_ALFRED/SubRackA/2",
                        "r1",
                    ),
                ],
                resources=("LABMAN_quadrant_1",),
                take_control=True,
            ),
            travel("BFT", "delivering to the box furnaces"),
            transfer(
                "BFT",
                "placing S1 into furnace input rack slot 3",
                "ROBOT_BASE/SubRackA",
                "1",
                "BFT",
                "3",
                moves=[
                    SampleMove(
                        "S1", "MOBILE_arm_ALFRED/SubRackA/1", "BFT_input_rack/slot/3", "r1"
                    )
                ],
                resources=("BFT_input_rack",),
            ),
            travel("Home", "work done, returning to the parking spot"),
        ],
        route="LABMAN -> BFT",
        description="2 crucibles from Labman quadrant 1 to the box furnaces",
    )


def test_legs_are_numbered_and_requests_collected() -> None:
    mission = _labman_to_bft()
    assert [leg.index for leg in mission] == [0, 1, 2, 3, 4]
    assert mission.request_ids == ("r1",)
    assert mission.samples == ("S1", "S2")


def test_a_mission_reports_the_stations_it_visits_in_order() -> None:
    assert _labman_to_bft().stations == ("LABMAN", "BFT", "Home")


def test_sample_positions_are_replayed_from_the_legs_that_ran() -> None:
    """Where a sample is has to be answerable for a mission that stopped part way, because
    that is exactly when someone needs to know."""
    mission = _labman_to_bft()
    assert mission.positions_after(0) == {}
    assert mission.positions_after(2)["S1"] == "MOBILE_arm_ALFRED/SubRackA/1"
    assert mission.final_positions() == {
        "S1": "BFT_input_rack/slot/3",
        "S2": "MOBILE_arm_ALFRED/SubRackA/2",
    }


def test_carried_samples_are_the_ones_on_the_base() -> None:
    mission = _labman_to_bft()
    assert mission.carried_after(2, "MOBILE_arm_ALFRED") == {
        "S1": "MOBILE_arm_ALFRED/SubRackA/1",
        "S2": "MOBILE_arm_ALFRED/SubRackA/2",
    }
    # S1 has been handed to the furnace rack, so only S2 is still aboard.
    assert list(mission.carried_after(4, "MOBILE_arm_ALFRED")) == ["S2"]


def test_the_dashboard_shape_carries_the_reason_for_every_leg() -> None:
    """The whole point of the transparency work: a person reading the timeline sees why."""
    data = _labman_to_bft().to_dict(legs_completed=2, base_prefix="MOBILE_arm_ALFRED")
    assert data["legs_completed"] == 2
    assert data["current_leg"]["reason"] == "delivering to the box furnaces"
    assert all(leg["reason"] for leg in data["legs"])
    assert data["carried"]


# ==========================================================================
# Running missions, cancelling them, and the battery policy
# ==========================================================================


def test_a_clean_mission_runs_every_leg_once(tmp_path: Path) -> None:
    robot = MockMiR250(tmp_path=tmp_path)
    result = robot.run_mission(_labman_to_bft())
    assert result.status == "completed"
    assert len(robot.legs_started) == 5
    assert result.positions["S1"] == "BFT_input_rack/slot/3"


def test_a_mission_below_the_working_floor_never_starts(tmp_path: Path) -> None:
    """Not a warning. The robot does not take on work it may not be able to finish."""
    robot = MockMiR250(tmp_path=tmp_path, battery=61.0)
    with pytest.raises(Exception) as raised:
        robot.run_mission(_labman_to_bft())
    assert "battery" in str(raised.value)
    assert robot.legs_started == [], "nothing may move when preflight refuses"


def test_a_cancelled_mission_stops_at_a_leg_boundary(tmp_path: Path) -> None:
    """The user's complaint, tested: cancel must not leave a leg half done, and must not
    run the next one either."""
    robot = MockMiR250(tmp_path=tmp_path)
    cancelled = {"after": 2}

    with pytest.raises(MissionCancelled) as raised:
        robot.run_mission(
            _labman_to_bft(),
            should_cancel=lambda: (
                "an operator cancelled the task"
                if len(robot.legs_started) >= cancelled["after"]
                else ""
            ),
        )
    assert len(robot.legs_started) == cancelled["after"]
    assert raised.value.leg_index == cancelled["after"]
    assert robot.mission_status == "cancelled"


def test_a_cancelled_mission_reports_the_resources_it_was_holding(tmp_path: Path) -> None:
    """So the caller can release the Labman quadrant instead of holding it through a dock."""
    robot = MockMiR250(tmp_path=tmp_path)
    with pytest.raises(MissionCancelled) as raised:
        robot.run_mission(
            _labman_to_bft(),
            should_cancel=lambda: "cancelled" if len(robot.legs_started) >= 1 else "",
        )
    assert raised.value.held_resources == ("LABMAN_quadrant_1",)


def test_a_cancelled_mission_records_where_the_samples_actually_got_to(
    tmp_path: Path,
) -> None:
    robot = MockMiR250(tmp_path=tmp_path)
    with pytest.raises(MissionCancelled) as raised:
        robot.run_mission(
            _labman_to_bft(),
            should_cancel=lambda: "cancelled" if len(robot.legs_started) >= 2 else "",
        )
    result = raised.value.result
    assert result.legs_completed == 2
    assert result.positions == {
        "S1": "MOBILE_arm_ALFRED/SubRackA/1",
        "S2": "MOBILE_arm_ALFRED/SubRackA/2",
    }


def test_cancelling_docks_the_robot_and_does_not_raise(tmp_path: Path) -> None:
    """A cancellation path that raises would replace the reason the task was stopping."""
    robot = MockMiR250(tmp_path=tmp_path)
    robot.park_after_cancellation("an operator cancelled the task")
    assert robot.legs_started[-1]["target_base_position"] == "ChargingNoWait"
    assert robot.mission_status in ("cancelled", "completed")


def test_a_battery_suspend_resumes_without_repeating_a_leg(tmp_path: Path) -> None:
    """The promise made about the 80/90 policy: the mission is intact, not restarted."""
    robot = MockMiR250(tmp_path=tmp_path)
    mission = _labman_to_bft()
    with pytest.raises(BatterySuspend) as raised:
        robot.run_mission(
            mission,
            should_suspend=lambda: (
                "battery below 80%" if len(robot.legs_started) >= 3 else ""
            ),
        )
    resume_at = raised.value.leg_index
    assert resume_at == 3
    assert len(robot.legs_started) == 3

    result = robot.run_mission(mission, start_at=resume_at, skip_preflight=True)
    assert result.status == "completed"
    assert len(robot.legs_started) == 5, "a resumed leg must not be run twice"
    assert result.positions["S1"] == "BFT_input_rack/slot/3"


def test_the_robot_never_waits_on_another_instrument_with_a_flat_battery(
    tmp_path: Path,
) -> None:
    """The explicit promise: waiting on Labman is not an exemption from the battery floor.

    The wait is what the old system did forever. Here it raises at once, naming what it was
    waiting for, so the caller docks instead.
    """
    robot = MockMiR250(tmp_path=tmp_path, battery=55.0)
    with pytest.raises(BatterySuspend) as raised:
        robot.engine.wait_for(
            lambda: False,
            "Labman to release quadrant 1",
            mission=_labman_to_bft(),
            leg=_labman_to_bft().leg(1),
            should_suspend=lambda: robot.battery_policy.suspend_reason(robot.battery()),
        )
    assert "Labman to release quadrant 1" in str(raised.value)
    assert "80%" in str(raised.value)


def test_a_cancel_wins_over_a_battery_suspend(tmp_path: Path) -> None:
    """A cancelled mission is not going to resume, so there is nothing to charge up for."""
    robot = MockMiR250(tmp_path=tmp_path)
    with pytest.raises(MissionCancelled):
        robot.run_mission(
            _labman_to_bft(),
            should_cancel=lambda: "cancelled",
            should_suspend=lambda: "battery below 80%",
        )


def test_waiting_for_charge_is_interruptible(tmp_path: Path) -> None:
    robot = MockMiR250(tmp_path=tmp_path, battery=45.0)
    with pytest.raises(MissionCancelled):
        robot.wait_until_charged(should_cancel=lambda: "cancelled while charging")


def test_waiting_for_charge_returns_once_the_resume_level_is_reached(
    tmp_path: Path,
) -> None:
    robot = MockMiR250(tmp_path=tmp_path, battery=45.0)
    reads = {"n": 0}
    real_battery = robot.battery

    def battery() -> float:
        reads["n"] += 1
        if reads["n"] > 3:
            robot.set_battery(91.0)
        return real_battery()

    robot.battery = battery  # type: ignore[method-assign]
    assert robot.wait_until_charged() == 91.0


# -- events and transparency ----------------------------------------------


def test_every_leg_announces_itself_with_its_reason(tmp_path: Path) -> None:
    robot = MockMiR250(tmp_path=tmp_path)
    events = []
    robot.subscribe(events.append)
    robot.run_mission(_labman_to_bft())
    started = [event for event in events if event.kind == "leg_started"]
    assert len(started) == 5
    assert started[0].reason == "collecting dosed crucibles from Labman quadrant 1"
    assert events[-1].kind == "mission_finished"


def test_a_finished_transfer_reports_the_samples_it_moved(tmp_path: Path) -> None:
    """This is what the Moving task mirrors into AlabOS, so it has to be the truth about
    what happened, not what was planned."""
    robot = MockMiR250(tmp_path=tmp_path)
    moved = []
    robot.subscribe(
        lambda event: moved.extend(event.moves) if event.kind == "leg_finished" else None
    )
    robot.run_mission(_labman_to_bft())
    assert [move.sample for move in moved] == ["S1", "S2", "S1"]


def test_the_snapshot_describes_a_running_mission(tmp_path: Path) -> None:
    robot = MockMiR250(tmp_path=tmp_path)
    robot.run_mission(_labman_to_bft())
    snapshot = robot.snapshot()
    assert snapshot["mission"]["route"] == "LABMAN -> BFT"
    assert snapshot["battery"] == 95.0
    assert snapshot["battery_policy"] == {
        "working_floor": 80.0,
        "resume_at": 90.0,
        "hard_floor": 20.0,
    }
    assert snapshot["stations"]["LABMAN"]["recorded_pose"]["x"] == pytest.approx(
        -4.895, abs=1e-3
    )


# -- the retry policy ------------------------------------------------------


def test_a_transient_manipulator_fault_is_retried(tmp_path: Path) -> None:
    robot = MockMiR250(tmp_path=tmp_path, fail_on={1: "Manipulator is not ready"})
    robot.run_leg_with_retries(travel("Home", "going home"))
    assert len(robot.legs_started) == 2, "the leg should have been attempted twice"


def test_a_blocked_path_is_retried_but_not_forever(tmp_path: Path) -> None:
    """The old code looped `while not success` on a blocked path. This one gives up and
    asks for a person, which is the difference between a night wasted and a night's work."""
    blocked = "The Move action timed out after being blocked"
    robot = MockMiR250(tmp_path=tmp_path, fail_on=dict.fromkeys(range(1, 12), blocked))
    with pytest.raises(MaintenanceRequired, match="blocked"):
        robot.run_leg_with_retries(travel("BFT", "going to the furnaces"))
    station = registry().station("BFT")
    assert len(robot.legs_started) == station.approach_attempts + 1


def test_an_obstacle_is_not_retried_at_all(tmp_path: Path) -> None:
    """The arm hit something. Trying again would hit it again, harder."""
    robot = MockMiR250(tmp_path=tmp_path, fail_on={1: "the arm is homed"})
    with pytest.raises(MaintenanceRequired):
        robot.run_leg_with_retries(travel("Home", "going home"))
    assert len(robot.legs_started) == 1


def test_a_failed_calibration_re_approaches_the_station(tmp_path: Path) -> None:
    """The camera is on the flange, so the marker is only in view from the taught pose.
    Driving out and back in is what actually fixes this, and it is capped."""
    robot = MockMiR250(tmp_path=tmp_path, fail_on={1: "Failed to Calibrate Tag"})
    leg = transfer(
        "LABMAN", "loading subrack A", "LABMAN", "SubRackA", "ROBOT_BASE", "SubRackA"
    )
    robot.run_leg_with_retries(leg)
    targets = [args["target_base_position"] for args in robot.legs_started]
    assert "Home" in targets and "LABMAN" in targets


def test_failure_classification_covers_every_message_we_have_seen() -> None:
    assert classify_failure("The Move action timed out after being blocked") == "blocked"
    assert classify_failure("Failed to Calibrate Tag on LABMAN") == "calibration"
    assert classify_failure("Manipulator is not ready") == "transient"
    assert classify_failure("the arm is homed") == "obstacle"
    assert classify_failure("something nobody has seen before") == "unknown"


# -- the protective-field mute --------------------------------------------


def test_reaching_into_labman_mutes_the_fields_and_puts_them_back(
    tmp_path: Path,
) -> None:
    robot = MockMiR250(tmp_path=tmp_path)
    robot.run_mission(_labman_to_bft())
    assert robot.ros.mute_calls == [True, False, True, False]
    assert robot.ros.muted is False, "the fields must be live when the robot drives away"


def test_travelling_does_not_mute_anything(tmp_path: Path) -> None:
    robot = MockMiR250(tmp_path=tmp_path)
    robot.run_mission(
        Mission.build([travel("Home", "going home")], route="-> Home")
    )
    assert robot.ros.mute_calls == []


def test_a_mute_that_will_not_clear_is_a_maintenance_stop(tmp_path: Path) -> None:
    """A robot driving the cell with its safety scanners suppressed is the worst outcome
    available, so this is the one failure that must never be swallowed."""
    robot = MockMiR250(tmp_path=tmp_path)
    robot.ros.refuse_unmute = True
    with pytest.raises(MaintenanceRequired, match="unmute"):
        robot.run_mission(_labman_to_bft())


def test_a_failed_leg_still_puts_the_fields_back(tmp_path: Path) -> None:
    """The unmute is in a `finally` for this reason."""
    robot = MockMiR250(tmp_path=tmp_path, fail_on={2: "the arm is homed"})
    with pytest.raises(Exception):
        robot.run_mission(_labman_to_bft())
    assert robot.ros.muted is False


# -- the battery policy in isolation --------------------------------------


def test_the_battery_policy_thresholds_are_the_ones_promised() -> None:
    policy = BatteryPolicy()
    assert (policy.working_floor, policy.resume_at, policy.hard_floor) == (80.0, 90.0, 20.0)
    assert not policy.may_start(79.9)
    assert policy.may_start(80.0)
    assert policy.must_stop(79.9)
    assert not policy.must_stop(80.0)
    assert not policy.may_resume(89.9)
    assert policy.may_resume(90.0)


def test_charging_is_not_an_exemption_from_the_floor() -> None:
    """A robot on the dock at 45% still may not go and do work."""
    policy = BatteryPolicy()
    assert policy.must_stop(45.0, charging=True)
    assert not policy.must_stop(91.0, charging=True)


def test_an_unknown_battery_never_starts_work_but_never_aborts_a_leg() -> None:
    """Refusing to start is safe. Aborting mid-mission on a failed read would strand the
    robot for a transport error, which is worse than finishing the leg."""
    policy = BatteryPolicy()
    assert not policy.may_start(None)
    assert not policy.must_stop(None)


def test_an_incoherent_policy_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="hard_floor < working_floor"):
        BatteryPolicy(working_floor=95.0, resume_at=90.0)


# -- the emergency stop ---------------------------------------------------


def test_the_emergency_stop_actually_commands_a_stop(tmp_path: Path) -> None:
    """The old one set a boolean. This one has to reach the controller and say what it did."""
    robot = MockMiR250(tmp_path=tmp_path)
    robot.ability.state_name = "Executing"
    report = robot.emergency_stop()
    assert report.ok, report.failures
    assert robot.ros.stops == 1
    assert "protective fields unmuted" in report.actions


def test_the_emergency_stop_admits_when_it_could_not_finish(tmp_path: Path) -> None:
    robot = MockMiR250(tmp_path=tmp_path)
    robot.ros.refuse_unmute = True
    report = robot.emergency_stop()
    assert not report.ok
    assert "physical e-stop" in str(report)


# ==========================================================================
# The exported Ability program, used as a contract check
# ==========================================================================

archive_available = pytest.mark.skipif(
    not default_archive_path().is_file(),
    reason=(
        "needs the exported Ability archive; export Main and point "
        "MIR250_PROGRAM_ARCHIVE at its program.xml"
    ),
)


@archive_available
def test_every_dispatch_target_names_a_real_function() -> None:
    """A typo in either table would only surface as a failure mid-run."""
    archive = ProgramArchive()
    unknown = sorted(
        {
            name
            for name in (*APPROACH.values(), *RETREAT.values())
            if name not in archive.functions
        }
    )
    assert unknown == []


@archive_available
def test_base_moves_maintain_base_position_themselves() -> None:
    """Why calling these functions directly is safe.

    Each one sets BasePosition to 'Unknown', drives, then sets the station and saves. An
    interrupted move therefore leaves 'Unknown' rather than a confident lie, and Python does
    not have to write the variable itself.
    """
    archive = ProgramArchive()
    for function in ("HomeBase", "Charging"):
        xml = archive.function_xml(function)
        assert "<Value>Unknown</Value>" in xml, function
        assert "SaveVariable" in xml, function


@archive_available
def test_a_subset_archive_carries_the_whole_call_closure() -> None:
    archive = ProgramArchive()
    closure = archive.closure(["Go to Labman"])
    assert closure[0] == "Go to Labman"
    assert "MoveToLabmanBackApproach" in closure
    subset = archive.archive_xml(["Go to Labman"])
    for name in closure:
        assert f"<Name>{name}</Name>" in subset, name


@archive_available
def test_stripping_the_export_indentation_is_worth_it() -> None:
    """The export is mostly whitespace, which matters over a websocket."""
    archive = ProgramArchive()
    assert len(archive.archive_xml()) < archive.path.stat().st_size / 5


@archive_available
def test_a_call_instruction_names_the_function_by_uid() -> None:
    """CallFunctionBlock refers to functions by UID, prefixed with the internal name."""
    archive = ProgramArchive()
    xml = compact(call_instruction(archive, "HomeBase"))
    assert archive.uid("HomeBase") in xml


def test_a_wait_instruction_is_in_milliseconds() -> None:
    assert "<Value>1500</Value>" in compact(wait_instruction(1.5))


def test_a_synthetic_function_block_has_the_fields_the_controller_demands() -> None:
    xml = compact(function_block("PyNoOp", [wait_instruction(1.0)]))
    for required in ("<Name>PyNoOp</Name>", "IsInitialized", "RetryAttempts", "<Instructions>"):
        assert required in xml, required


def test_leg_kinds_render_as_the_words_the_dashboard_shows() -> None:
    assert str(LegKind.TRAVEL) == "travel"
    assert travel("Home", "x").to_dict()["kind"] == "travel"

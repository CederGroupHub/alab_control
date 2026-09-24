"""Unit tests for Labman.take_quadrant polling / re-request behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from alab_control.labman.error import LabmanError
from alab_control.labman.labman import Labman, QuadrantStatus


def _status(
    *,
    indexing: str = "RobotControl",
    automated: bool = True,
    running: bool = True,
    error: str = "",
) -> dict:
    return {
        "CurrentOutwardQuadrantNumber": 1,
        "HeatedRackTemperature": 23.5,
        "InAutomatedMode": automated,
        "IndexingRackStatus": indexing,
        "PipetteTipCount": 100,
        "ProcessErrorMessage": error,
        "QuadrantStatuses": [
            {
                "LoadedWorkflowName": None,
                "Progress": "Empty",
                "QuadrantNumber": i,
            }
            for i in range(1, 5)
        ],
        "RobotRunning": running,
    }


def _labman_without_db(api: MagicMock) -> Labman:
    """Build a Labman instance without touching Mongo."""
    labman = Labman.__new__(Labman)
    labman.API = api
    labman.logging = MagicMock()
    labman.STATUS_UPDATE_WINDOW = 0
    labman.last_updated_at = 0
    labman.quadrants = {i: MagicMock(status=QuadrantStatus.EMPTY) for i in range(1, 5)}
    labman._api_reachable = False
    labman._indexing_rack_status = None
    labman._robot_running = False
    labman._in_automated_mode = False
    labman._rack_under_robot_control = True
    labman._process_error_message = ""
    labman._current_outward_quadrant = None
    labman._heated_rack_temperature = None
    labman._pipette_tip_count = None
    return labman


def test_take_quadrant_succeeds_when_rack_already_user_control(monkeypatch):
    api = MagicMock()
    api.get_status.return_value = _status(indexing="UserControl")
    labman = _labman_without_db(api)
    monkeypatch.setattr("alab_control.labman.labman.time.sleep", lambda *_: None)

    labman.take_quadrant(index=1, timeout_s=30.0, rerequest_every_s=0.0)

    api.request_indexing_rack_control.assert_not_called()


def test_take_quadrant_treats_user_control_api_error_as_success(monkeypatch):
    api = MagicMock()
    api.get_status.side_effect = [
        _status(indexing="RobotControl"),
        _status(indexing="UserControl"),
    ]
    api.request_indexing_rack_control.side_effect = LabmanError(
        "Failed to request indexing rack control. "
        "The indexing rack is in the state 'UserControl'."
    )
    labman = _labman_without_db(api)
    monkeypatch.setattr("alab_control.labman.labman.time.sleep", lambda *_: None)

    labman.take_quadrant(index=1, timeout_s=30.0, rerequest_every_s=0.0)

    api.request_indexing_rack_control.assert_called_once_with(1)


def test_take_quadrant_rerequests_until_user_control(monkeypatch):
    api = MagicMock()
    statuses = [
        _status(indexing="RobotControl"),
        _status(indexing="RobotControl"),
        _status(indexing="UserControl"),
    ]
    api.get_status.side_effect = statuses
    labman = _labman_without_db(api)
    monkeypatch.setattr("alab_control.labman.labman.time.sleep", lambda *_: None)

    labman.take_quadrant(index=1, timeout_s=30.0, rerequest_every_s=0.0)

    assert api.request_indexing_rack_control.call_count >= 1
    api.request_indexing_rack_control.assert_called_with(1)
    # Cached after the successful poll inside take_quadrant (no extra get_status).
    assert labman._indexing_rack_status == "UserControl"
    assert labman._rack_under_robot_control is False


def test_take_quadrant_times_out_when_labman_keeps_rack(monkeypatch):
    api = MagicMock()
    api.get_status.return_value = _status(indexing="RobotControl")
    labman = _labman_without_db(api)
    monkeypatch.setattr("alab_control.labman.labman.time.sleep", lambda *_: None)
    # Advance time past the deadline after the first poll.
    times = iter([100.0, 100.1, 100.2, 200.0])
    monkeypatch.setattr(
        "alab_control.labman.labman.time.time", lambda: next(times, 200.0)
    )

    with pytest.raises(TimeoutError, match="did not yield indexing rack"):
        labman.take_quadrant(index=2, timeout_s=10.0, rerequest_every_s=0.0)

    assert api.request_indexing_rack_control.called


def test_api_failure_clears_ready_flags():
    api = MagicMock()
    api.get_status.side_effect = ConnectionError("down")
    labman = _labman_without_db(api)

    assert labman.is_ready_for_robot_handoff() is False
    assert labman.api_reachable is False
    assert labman.robot_is_running is False
    assert labman.in_automated_mode is False


def test_is_ready_for_robot_handoff_requires_auto_and_running():
    api = MagicMock()
    api.get_status.return_value = _status(automated=False, running=True)
    labman = _labman_without_db(api)
    assert labman.is_ready_for_robot_handoff() is False

    api.get_status.return_value = _status(automated=True, running=False)
    labman.last_updated_at = 0
    assert labman.is_ready_for_robot_handoff() is False

    api.get_status.return_value = _status(automated=True, running=True)
    labman.last_updated_at = 0
    assert labman.is_ready_for_robot_handoff() is True

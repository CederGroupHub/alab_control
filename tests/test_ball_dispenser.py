"""Unit tests for the ball dispenser driver stop conditions."""

from __future__ import annotations

import time

import pytest

from alab_control.ball_dispenser import BallDispenser, EmptyError


@pytest.fixture()
def dispenser(monkeypatch):
    device = BallDispenser(ip_address="127.0.0.1")
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    return device


def test_dispense_balls_sets_count_before_start(dispenser, monkeypatch):
    calls = []
    polls = {"n": 0}

    def send_request(endpoint, **_kwargs):
        calls.append(endpoint)
        if endpoint == "/state":
            polls["n"] += 1
            if polls["n"] == 1:
                return {"state": "STOPPED"}
            if polls["n"] < 4:
                return {"state": "RUNNING"}
            return {"state": "STOPPED"}
        return {"status": "success"}

    monkeypatch.setattr(dispenser, "send_request", send_request)

    dispenser.dispense_balls()

    assert "/change?n=1" in calls
    assert calls.index("/change?n=1") < calls.index("/start")
    assert "/stop" not in calls


def test_dispense_balls_stops_when_sensor_never_finishes(dispenser, monkeypatch):
    clock = {"now": 0.0}
    calls = []

    def send_request(endpoint, **_kwargs):
        calls.append(endpoint)
        if endpoint == "/state":
            if clock["now"] == 0.0 and "/start" not in calls:
                return {"state": "STOPPED"}
            clock["now"] += dispenser.PER_BALL_TIMEOUT / 5
            return {"state": "RUNNING"}
        return {"status": "success"}

    monkeypatch.setattr(dispenser, "send_request", send_request)
    monkeypatch.setattr(time, "time", lambda: clock["now"])

    with pytest.raises(EmptyError):
        dispenser.dispense_balls()

    assert "/change?n=1" in calls
    assert "/stop" in calls


def test_change_number_rejects_zero(dispenser):
    with pytest.raises(ValueError):
        dispenser.change_number(0)

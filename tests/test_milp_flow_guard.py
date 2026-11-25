"""The suite guard against MILP plans with opposite flows in one slot (tests/milp_flow_guard)."""
from __future__ import annotations

import pytest

from optimizer import milp_model
from tests import milp_flow_guard


@pytest.mark.allow_simultaneous_flows
def test_guard_records_a_plan_with_opposite_flows(monkeypatch):
    monkeypatch.setattr(
        milp_model, "simultaneous_flow_slots", lambda _m: {"grid": [3], "battery": []}
    )
    found, restore = milp_flow_guard.install()
    try:
        milp_model.simultaneous_flow_slots(object())
    finally:
        restore()
    assert found == [{"grid": [3], "battery": []}]
    with pytest.raises(pytest.fail.Exception, match="opposite flows"):
        milp_flow_guard.check(found)


@pytest.mark.allow_simultaneous_flows
def test_guard_ignores_clean_plans(monkeypatch):
    monkeypatch.setattr(
        milp_model, "simultaneous_flow_slots", lambda _m: {"grid": [], "battery": []}
    )
    found, restore = milp_flow_guard.install()
    try:
        milp_model.simultaneous_flow_slots(object())
    finally:
        restore()
    assert found == []
    milp_flow_guard.check(found)


@pytest.mark.allow_simultaneous_flows
def test_guard_restores_the_original_check():
    original = milp_model.simultaneous_flow_slots
    _found, restore = milp_flow_guard.install()
    assert milp_model.simultaneous_flow_slots is not original
    restore()
    assert milp_model.simultaneous_flow_slots is original


def test_guard_is_active_without_the_marker():
    """The autouse fixture wraps the check the MILP calls after each solve."""
    assert milp_model.simultaneous_flow_slots.__name__ == "_recording"

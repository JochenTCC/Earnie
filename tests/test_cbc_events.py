"""Tests für CBC-Ereignis-Sammlung."""
from __future__ import annotations

import logging

import pulp

from optimizer.cbc_events import (
    begin_cbc_event_collection,
    record_cbc_event,
    set_cbc_milp_context,
    summarize_cbc_events,
    take_cbc_events,
    update_cbc_milp_context_from_row,
)
from optimizer.cbc_solver import solve_with_strict_fallback


def test_record_cbc_event_collects_with_context():
    begin_cbc_event_collection()
    set_cbc_milp_context(
        scenario_id="runtime_settings",
        window_anchor="2025-09-28T10:00:00",
        consumer_targets_kwh={"eauto": 1.168},
    )
    update_cbc_milp_context_from_row(
        {
            "hour": 0,
            "slot_datetime": "2025-09-27T10:00:00",
            "charging_anchor": "2025-09-28T10:00:00",
        }
    )
    record_cbc_event(
        "strict_fallback",
        strict_limit_sec=3.0,
        strict_elapsed_sec=3.01,
        strict_status="Not Solved",
        gap_rel=0.10,
    )
    events = take_cbc_events()
    assert len(events) == 1
    assert events[0]["event"] == "strict_fallback"
    assert events[0]["scenario_id"] == "runtime_settings"
    assert events[0]["slot_datetime"] == "2025-09-27T10:00:00"
    assert events[0]["strict_status"] == "Not Solved"


def test_record_cbc_event_suppresses_console_while_collecting(caplog):
    begin_cbc_event_collection()
    with caplog.at_level(logging.INFO, logger="optimizer.cbc_events"):
        record_cbc_event("strict_fallback", strict_status="Infeasible")
        record_cbc_event("milp_no_optimal", final_status="Infeasible")
    events = take_cbc_events()
    assert len(events) == 2
    assert not caplog.records


def test_summarize_cbc_events():
    summary = summarize_cbc_events(
        [
            {"event": "strict_fallback"},
            {"event": "strict_fallback"},
            {"event": "milp_no_optimal", "final_status": "Infeasible"},
        ]
    )
    assert summary == (
        "CBC Horizont-Simulation: milp_no_optimal=1, strict_fallback=2, "
        "final(Infeasible:1)"
    )


def test_solve_with_strict_fallback_records_slow_strict(caplog):
    begin_cbc_event_collection()
    set_cbc_milp_context(scenario_id="test", window_anchor="2025-09-28T10:00:00")
    prob = pulp.LpProblem("t", pulp.LpMinimize)
    x = pulp.LpVariable("x", lowBound=0)
    prob += x
    prob += x >= 1
    with caplog.at_level(logging.INFO, logger="optimizer.cbc_events"):
        solve_with_strict_fallback(prob, msg=False)
    events = take_cbc_events()
    assert prob.status is not None
    assert len(events) <= 1

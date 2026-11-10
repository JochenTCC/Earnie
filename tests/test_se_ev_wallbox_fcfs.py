"""Scenario Explorer rule D9 for dynamic EVs: first come, first served (multi-EV M4)."""
from __future__ import annotations

import pytest

from house_config.wallboxes import VIEW_CHARGER_ID_KEY, normalize_wallbox, resolve_dynamic_ev_view
from simulation.ev_wallbox_fcfs import (
    assign_dynamic_evs_fcfs,
    describe_fcfs,
    fcfs_assignment,
)


def _wallbox(wid: str, max_a: float = 16.0) -> dict:
    return normalize_wallbox(
        {
            "id": wid,
            "voltage_v": 230,
            "phases": 3,
            "min_current_a": 6,
            "max_current_a": max_a,
            "unknown_vehicle": "off",
            "ehal_bindings": {f"evcs.{wid}.sens_evcs_connected": ""},
        },
        index=0,
    )


WALLBOXES = {"wb_1": _wallbox("wb_1"), "wb_2": _wallbox("wb_2", max_a=10.0)}


def _ev(ev_id: str, window: tuple[int, int], wallboxes=("wb_1", "wb_2"), weekend=None) -> dict:
    sched = {
        "forecast_when_absent": False,
        "weekday": {"car_available_from_hour": window[0], "ready_by_hour": window[1]},
    }
    if weekend is not None:
        sched["weekend"] = {"car_available_from_hour": weekend[0], "ready_by_hour": weekend[1]}
    spec = {
        "id": ev_id,
        "type": "ev",
        "phases": 3,
        "min_current_a": 6.0,
        "max_current_a": 16.0,
        "wallbox_assignment": {"mode": "dynamic", "wallbox_ids": list(wallboxes)},
        "charging_schedule": sched,
    }
    resolve_dynamic_ev_view(spec, WALLBOXES, label=ev_id)
    return spec


def _by_ev(consumers) -> dict[str, str | None]:
    return {row.ev_id: row.wallbox_id for row in fcfs_assignment(consumers)}


def test_first_arrival_takes_the_first_wallbox_ties_by_kennung():
    cars = [_ev("car_c", (18, 7)), _ev("car_b", (17, 7)), _ev("car_a", (18, 7))]
    rows = fcfs_assignment(cars)
    assert [r.ev_id for r in rows] == ["car_b", "car_a", "car_c"]
    assert _by_ev(cars) == {"car_b": "wb_1", "car_a": "wb_2", "car_c": None}


def test_cars_with_separate_windows_share_a_wallbox():
    cars = [_ev("night", (18, 7), wallboxes=("wb_1",)), _ev("day", (8, 16), wallboxes=("wb_1",))]
    assert _by_ev(cars) == {"night": "wb_1", "day": "wb_1"}
    # Touching windows (7 → 7) do not overlap either.
    cars = [_ev("night", (18, 7), wallboxes=("wb_1",)), _ev("early", (7, 12), wallboxes=("wb_1",))]
    assert _by_ev(cars) == {"night": "wb_1", "early": "wb_1"}


def test_overlap_across_midnight_blocks_the_wallbox():
    cars = [_ev("night", (18, 7), wallboxes=("wb_1",)), _ev("late", (5, 9), wallboxes=("wb_1",))]
    assert _by_ev(cars) == {"late": "wb_1", "night": None}


def test_assigned_cars_are_planned_as_pairs_and_a_car_without_wallbox_is_left_out():
    fixed = {"id": "heat_pump", "type": "thermal_annual"}
    cars = [_ev("car_a", (18, 7)), _ev("car_b", (18, 7)), _ev("car_c", (19, 7))]
    planned = assign_dynamic_evs_fcfs([fixed, *cars])
    assert [c["id"] for c in planned] == ["heat_pump", "car_a", "car_b"]
    assert planned[1][VIEW_CHARGER_ID_KEY] == "wb_1"
    assert planned[1]["nominal_power_kw"] == pytest.approx(16 * 230 * 3 / 1000)
    assert planned[2][VIEW_CHARGER_ID_KEY] == "wb_2"
    assert planned[2]["nominal_power_kw"] == pytest.approx(10 * 230 * 3 / 1000)
    lines = describe_fcfs(fcfs_assignment(cars))
    assert lines == [
        "car_a → Wallbox wb_1 (18–07 Uhr)",
        "car_b → Wallbox wb_2 (18–07 Uhr)",
        "car_c: keine freie Wallbox (19–07 Uhr) — wird nicht geladen",
    ]


def test_weekend_must_give_the_same_assignment():
    same = [_ev("car_a", (18, 7), weekend=(20, 9)), _ev("car_b", (19, 7), weekend=(21, 9))]
    assert _by_ev(same) == {"car_a": "wb_1", "car_b": "wb_2"}
    flipped = [_ev("car_a", (18, 7), weekend=(21, 9)), _ev("car_b", (19, 7), weekend=(20, 9))]
    with pytest.raises(ValueError, match="Wochenende"):
        fcfs_assignment(flipped)


def test_a_dynamic_ev_needs_its_arrival_hour():
    car = _ev("car_a", (18, 7))
    car["charging_schedule"]["weekday"] = {"ready_by_hour": 7}
    with pytest.raises(ValueError, match="car_available_from_hour"):
        fcfs_assignment([car])


def test_no_dynamic_ev_changes_nothing():
    consumers = [{"id": "car_b", "type": "ev"}]
    assert fcfs_assignment(consumers) == []
    assert assign_dynamic_evs_fcfs(consumers) == consumers


def test_scenario_consumers_apply_d9(monkeypatch):
    from simulation import engine_scenario

    cars = [_ev("car_a", (18, 7)), _ev("car_b", (18, 7))]
    monkeypatch.setattr(engine_scenario, "_scenario_planning_consumers", lambda _p: cars)
    planned = engine_scenario._flexible_consumers_from_scenario({"x": 1})
    assert [(c["id"], c[VIEW_CHARGER_ID_KEY]) for c in planned] == [
        ("car_a", "wb_1"),
        ("car_b", "wb_2"),
    ]
    assert engine_scenario.scenario_ev_wallbox_lines({"x": 1}) == [
        "car_a → Wallbox wb_1 (18–07 Uhr)",
        "car_b → Wallbox wb_2 (18–07 Uhr)",
    ]

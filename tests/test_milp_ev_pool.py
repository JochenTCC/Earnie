"""Pool constraints of dynamic EVs that are not assigned (multi-EV M4, D8)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from house_config.wallboxes import VIEW_DYNAMIC_KEY, VIEW_POOL_KEY, pool_dynamic_ev_view
from optimizer.milp import milp_horizon_schedule

START = datetime(2026, 11, 10, 0, 0)
CAR_KW = 3.5


def _wallbox(wid: str, max_a: float = 16.0) -> dict:
    return {
        "id": wid,
        "voltage_v": 230.0,
        "phases": 1,
        "min_current_a": 6.0,
        "max_current_a": max_a,
        "unknown_vehicle": "off",
    }


def _pool_ev(cid: str, pool: list[str], wallboxes: list[dict]) -> dict:
    return {
        "id": cid,
        "name": cid,
        "type": "ev",
        "nominal_power_kw": CAR_KW,
        "min_power_kw": None,
        "min_on_quarterhours": 1,
        "charging_schedule": {
            "enabled": True,
            "milp": {
                "live_modus_a_min_remaining_kwh": 2.8,
                "tie_break_on_epsilon": 0.001,
                "tie_break_time_epsilon": 0.0001,
            },
        },
        VIEW_DYNAMIC_KEY: wallboxes,
        VIEW_POOL_KEY: list(pool),
    }


DT_H = 0.25


def _matrix(hour_prices: list[float]) -> list[dict]:
    """Quarter-hour rows, four per price hour."""
    rows = []
    for t in range(4 * len(hour_prices)):
        slot = START + timedelta(minutes=15 * t)
        rows.append(
            {
                "hour": slot.hour,
                "slot_datetime": slot,
                "date": slot.date(),
                "expected_p_pv": 0.0,
                "expected_p_act": 0.3,
                "k_act": hour_prices[t // 4],
            }
        )
    return rows


def _ctx(target_kwh: float, deadline_h: int) -> dict:
    return {
        "active": True,
        "plugged_in": False,
        "anticipated": True,
        "available_from": START,
        "deadline": START + timedelta(hours=deadline_h),
        "target_kwh": target_kwh,
        "use_time_window": False,
    }


def _battery() -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 0.5,
        "efficiency": 0.95,
    }


def _plan(consumers: list[dict], contexts: dict[str, dict], prices: list[float]) -> dict[str, list[float]]:
    schedule = milp_horizon_schedule(
        _matrix(prices),
        current_soc=10.0,
        battery_params=_battery(),
        k_push=0.0,
        verbose=False,
        consumers=consumers,
        consumer_remaining_kwh={cid: ctx["target_kwh"] for cid, ctx in contexts.items()},
        charging_contexts=contexts,
    )
    assert schedule, "MILP not optimal"
    return {
        str(c["id"]): [float(slot["consumer_powers"].get(c["id"], 0.0)) for slot in schedule]
        for c in consumers
    }


def _kwh(powers: list[float]) -> float:
    return sum(powers) * DT_H


def _charging(powers: list[float]) -> list[bool]:
    return [p > 1e-6 for p in powers]


# Cheap hours 1–3 (slots 4–15), expensive otherwise.
PRICES = [30.0, 10.0, 10.0, 10.0] + [30.0] * 8
CHEAP = slice(4, 16)
TARGET = 2 * CAR_KW  # two hours at full power = 8 quarter hours


def test_two_cars_one_wallbox_never_charge_together_and_tight_deadline_wins():
    wb = [_wallbox("wb1")]
    cars = [_pool_ev("car_a", ["wb1"], wb), _pool_ev("car_b", ["wb1"], wb)]
    contexts = {"car_a": _ctx(TARGET, deadline_h=4), "car_b": _ctx(TARGET, deadline_h=12)}
    plan = _plan(cars, contexts, PRICES)
    for t, (a, b) in enumerate(zip(_charging(plan["car_a"]), _charging(plan["car_b"]))):
        assert not (a and b), f"both cars charge in slot {t}"
    # car_a must finish by hour 4: it takes two of the three cheap hours, car_b the third.
    assert _kwh(plan["car_a"][CHEAP]) == pytest.approx(TARGET, abs=0.01)
    assert _kwh(plan["car_b"]) == pytest.approx(TARGET, abs=0.01)
    assert _kwh(plan["car_b"][CHEAP]) == pytest.approx(CAR_KW, abs=0.01)


def test_without_pool_both_cars_take_the_cheap_hours():
    """Control: the same cars without pool keys charge in the same slots."""
    wb = [_wallbox("wb1")]
    cars = [_pool_ev("car_a", ["wb1"], wb), _pool_ev("car_b", ["wb1"], wb)]
    for car in cars:
        del car[VIEW_POOL_KEY]
    contexts = {"car_a": _ctx(TARGET, deadline_h=4), "car_b": _ctx(TARGET, deadline_h=12)}
    plan = _plan(cars, contexts, PRICES)
    both = [a and b for a, b in zip(_charging(plan["car_a"]), _charging(plan["car_b"]))]
    assert any(both)


def test_three_cars_two_wallboxes_at_most_two_charge():
    wbs = [_wallbox("wb1"), _wallbox("wb2")]
    cars = [_pool_ev(cid, ["wb1", "wb2"], wbs) for cid in ("car_a", "car_b", "car_c")]
    contexts = {cid: _ctx(TARGET, deadline_h=12) for cid in ("car_a", "car_b", "car_c")}
    plan = _plan(cars, contexts, PRICES)
    for t in range(4 * len(PRICES)):
        assert sum(plan[c][t] > 1e-6 for c in plan) <= 2
    for cid in plan:
        assert _kwh(plan[cid]) == pytest.approx(TARGET, abs=0.01)


def test_cars_with_different_wallbox_lists_keep_distinct_wallboxes():
    """car_c may use only wb2: with car_a / car_b on {wb1, wb2}, no slot has three cars and
    no slot has car_c with both others (Hall's condition per wallbox subset)."""
    wbs = [_wallbox("wb1"), _wallbox("wb2")]
    cars = [
        _pool_ev("car_a", ["wb1", "wb2"], wbs),
        _pool_ev("car_b", ["wb1", "wb2"], wbs),
        _pool_ev("car_c", ["wb2"], wbs),
    ]
    contexts = {cid: _ctx(TARGET, deadline_h=12) for cid in ("car_a", "car_b", "car_c")}
    plan = _plan(cars, contexts, PRICES)
    for t in range(4 * len(PRICES)):
        on = {c for c in plan if plan[c][t] > 1e-6}
        assert len(on) <= 2
        assert on != {"car_a", "car_b", "car_c"}


def test_pool_view_takes_smallest_free_pair_and_lists_free_wallboxes():
    wbs = [_wallbox("wb_big", 32.0), _wallbox("wb_small", 10.0)]
    ev = {
        "id": "car_a",
        "phases": 1,
        "min_current_a": 6.0,
        "max_current_a": 16.0,
        "charging_schedule": {},
        VIEW_DYNAMIC_KEY: wbs,
    }
    both = pool_dynamic_ev_view(ev, ["wb_big", "wb_small"])
    assert both[VIEW_POOL_KEY] == ["wb_big", "wb_small"]
    assert both["nominal_power_kw"] == pytest.approx(2.3)
    big_only = pool_dynamic_ev_view(ev, ["wb_big"])
    assert big_only[VIEW_POOL_KEY] == ["wb_big"]
    assert big_only["nominal_power_kw"] == pytest.approx(3.68)
    none_free = pool_dynamic_ev_view(ev, [])
    assert none_free[VIEW_POOL_KEY] == []


# --------------------------------------------------------------------------- charging context


def _context_ev(pool: list[str], *, forecast: bool) -> dict:
    day = {"car_available_from_hour": 18, "ready_by_hour": 7, "daily_rest_soc": 40.0}
    ev = _pool_ev("car_a", pool, [_wallbox("wb1")])
    ev["battery_capacity_kwh"] = 60.0
    ev["daily_target_source"] = "config"
    ev["charging_schedule"].update(
        {
            "target_soc_percent": 100.0,
            "charging_efficiency": 1.0,
            "forecast_when_absent": forecast,
            "weekday": dict(day),
            "weekend": dict(day),
        }
    )
    # A plug binding the pool view must never read (it is at no wallbox yet).
    ev["ehal_bindings"] = {"sens_evcs_connected": "Plug_Marker"}
    return ev


def _resolve(ev: dict, monkeypatch) -> dict:
    from integrations import ehal_live
    from optimizer.charging_resolve import resolve_charging_context

    def _no_plug_read(name):
        raise AssertionError(f"plug read for a pool EV: {name}")

    monkeypatch.setattr(ehal_live, "read_generic_value", _no_plug_read)
    matrix = _matrix([20.0] * 24)
    start = datetime(2026, 11, 10, 12, 0)
    for t, row in enumerate(matrix):
        row["slot_datetime"] = start + timedelta(minutes=15 * t)
        row["hour"] = row["slot_datetime"].hour
        row["date"] = row["slot_datetime"].date()
    return resolve_charging_context(ev, matrix, None, False)


def test_pool_ev_without_free_wallbox_is_inactive(monkeypatch):
    ctx = _resolve(_context_ev([], forecast=True), monkeypatch)
    assert ctx["active"] is False
    assert "keine freie Wallbox" in ctx["source_label"]


def test_pool_ev_without_forecast_is_not_planned(monkeypatch):
    ctx = _resolve(_context_ev(["wb1"], forecast=False), monkeypatch)
    assert ctx["active"] is False
    assert "nicht angeschlossen" in ctx["source_label"]


def test_pool_ev_with_forecast_is_anticipated_never_plugged(monkeypatch):
    ctx = _resolve(_context_ev(["wb1"], forecast=True), monkeypatch)
    assert ctx["active"] is True
    assert ctx["anticipated"] is True
    assert ctx["plugged_in"] is False
    assert ctx["available_from"] == datetime(2026, 11, 10, 18, 0)

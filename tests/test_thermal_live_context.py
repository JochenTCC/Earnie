"""ThermalHorizon P2 — Live store flex context from the horizon plan, one plan per cycle."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from house_config.planning_flex_bridge import planning_thermal_to_milp
from optimizer.live_cycle_scope import cycle_memo, live_cycle_scope
from optimizer.thermal_live_store import LiveStorePlan, live_store_slot_energy_kwh
from optimizer.thermal_model import ThermalBand

_DAY = date(2026, 10, 15)


def _source() -> dict:
    return {
        "id": "wp_heating",
        "label": "Wärmepumpe",
        "type": "thermal_annual",
        "nominal_power_kw": 1.9,
        "daily_target_source": "thermal_annual",
        "thermal": {
            "living_area_m2": 157.0,
            "building_class": 2,
            "heat_pump_type": "erde",
            "persons": 2,
            "target_temp_c": 21.5,
            "heating_limit_c": 15.0,
            "heat_storage": {
                "volume_liters": 887.0,
                "heat_loss_kw_per_k": 0.01,
                "setpoint_c": 47.0,
                "tolerance_c": 5.0,
            },
        },
    }


def _profile() -> dict:
    return {
        "id": "example_efh",
        "latitude": 47.4,
        "longitude": 9.7,
        "absent_mode": False,
        "consumers": [_source()],
    }


def _live_matrix(hours: int = 3) -> list[dict]:
    start = datetime.combine(_DAY, time(22, 0))
    rows = []
    for index in range(hours * 4):
        slot = start + timedelta(minutes=15 * index)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "consumption_mode": "live_snapshot",
            }
        )
    return rows


def _plan(electric_by_hour: list[float]) -> LiveStorePlan:
    return LiveStorePlan(
        forced_hour_flags=[kwh > 0.0 for kwh in electric_by_hour],
        floor_electric_kwh=round(sum(electric_by_hour), 3),
        opp_cap_electric_kwh=0.0,
        start_temp_c=44.0,
        temp_low_c=None,
        used_measured_eq=True,
        used_measured_low=False,
        band=ThermalBand(47.0, 5.0),
        electric_by_hour=electric_by_hour,
    )


def test_slot_energy_maps_hourly_electric_to_quarter_hours():
    energies = live_store_slot_energy_kwh(_live_matrix(3), _plan([0.0, 1.9, 0.4]))

    assert energies == [0.0] * 4 + [0.475] * 4 + [0.1] * 4


def test_live_store_context_skips_year_profile(monkeypatch):
    import optimizer.thermal_flex_context as tfc
    import optimizer.thermal_live_store as tls
    from optimizer.thermal_flex_context import resolve_thermal_flex_contexts

    def _no_year_profile(*_a, **_k):
        raise AssertionError("Live store context must not build the year profile")

    monkeypatch.setattr(tfc, "_slot_aligned_thermal_energy_kwh", _no_year_profile)
    monkeypatch.setattr(
        tls, "live_store_plan_for_matrix", lambda *_a, **_k: _plan([0.0, 1.9, 0.0])
    )
    monkeypatch.setattr(
        "optimizer.absent_mode.resolve_absent_status", lambda _p: {"effective": False}
    )
    consumer = planning_thermal_to_milp(_source())
    matrix = _live_matrix(3)

    ctx = resolve_thermal_flex_contexts(matrix, [consumer], _profile())[consumer["id"]]

    assert ctx["slot_energy_kwh"] == [0.0] * 4 + [0.475] * 4 + [0.0] * 4
    assert ctx["daily_targets"] == {_DAY: 1.9}
    assert ctx["forced_indices"] == [4, 5, 6, 7]
    assert ctx["live_store_start_c"] == 44.0


def test_one_store_plan_per_cycle_for_context_and_targets(monkeypatch):
    import optimizer.thermal_live_store as tls
    from optimizer.targets import _live_heat_storage_horizon_need_kwh
    from optimizer.thermal_flex_context import _live_store_flex_overlay

    builds = {"n": 0}

    def _build(*_a, **_k):
        builds["n"] += 1
        return _plan([1.9, 0.0, 0.0])

    monkeypatch.setattr(tls, "_build_live_store_plan", _build)
    consumer = planning_thermal_to_milp(_source())
    matrix = _live_matrix(3)

    with live_cycle_scope():
        _live_store_flex_overlay(matrix, _source(), _profile(), consumer)
        need = _live_heat_storage_horizon_need_kwh(_source(), _profile(), matrix)
        _live_store_flex_overlay(matrix, _source(), _profile(), consumer)
    assert builds["n"] == 1
    assert need == 1.9

    # Outside a Live cycle (tests, backtesting, UI) every call computes.
    _live_heat_storage_horizon_need_kwh(_source(), _profile(), matrix)
    _live_heat_storage_horizon_need_kwh(_source(), _profile(), matrix)
    assert builds["n"] == 3


def test_cycle_memo_is_scoped():
    calls = {"n": 0}

    def _compute():
        calls["n"] += 1
        return calls["n"]

    with live_cycle_scope():
        assert cycle_memo("k", _compute) == 1
        assert cycle_memo("k", _compute) == 1
    with live_cycle_scope():
        assert cycle_memo("k", _compute) == 2
    assert cycle_memo("k", _compute) == 3


def test_live_overlay_keeps_pulse_limits_without_day_targets():
    """Empty plan day targets must not skip max-on constraints (MILP unchanged vs. HDD days)."""
    from optimizer.milp_consumers import filter_feasible_consumers
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.thermal_flex_context import add_thermal_flex_constraints

    consumer = planning_thermal_to_milp(_source())
    matrix = [
        {
            **row,
            "k_act": 35.0,
            "price_buy": 0.35,
            "expected_p_act": 0.5,
            "expected_p_pv": 0.0,
        }
        for row in _live_matrix(12)
    ]
    n = len(matrix)
    contexts = {
        consumer["id"]: {
            "daily_targets": {},
            "slot_energy_kwh": [0.0] * n,
            "targets_slot_aligned": True,
            "forced_indices": [],
            "live_day_min_kwh": {},
            "floor_kwh": 0.0,
            "opp_cap_kwh": 0.0,
            "live_store_start_c": 50.0,
            "live_store_temp_low_c": None,
        }
    }
    remaining = {consumer["id"]: 2.0}
    battery = {
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "battery_capacity_kwh": 10.0,
        "efficiency": 0.95,
    }
    planned = filter_feasible_consumers(
        [consumer], remaining, matrix, list(range(n)), False, {}, {}
    )
    model = _build_milp_model(matrix, n, battery, 50.0, planned, 0.0, remaining, {})
    assert consumer["id"] in model.consumer_on
    add_thermal_flex_constraints(model, matrix, list(range(n)), contexts)

    assert any(f"{consumer['id']}_max_on_" in name for name in model.prob.constraints)

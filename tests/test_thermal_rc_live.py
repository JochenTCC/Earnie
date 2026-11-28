"""Live pool (thermal_rc): water band over the whole horizon, not a today-only delivery.

Regression: the Live plan forced the RC target of the whole horizon into the slots before
midnight (``milp_inputs._day_indices``), so the pool heated 20:00-24:00 although the night
was cheaper and the water would have stayed in the band.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from house_config.planning_flex_converters import planning_thermal_rc_to_milp
from optimizer.live_cycle_scope import live_cycle_scope
from optimizer.slot_duration import DEFAULT_DT_H, slot_step

_CID = "pool_swimspa"
_START = datetime(2026, 11, 27, 13, 0)
_END = datetime(2026, 11, 29, 8, 0)

@pytest.fixture(autouse=True)
def _product_solver_mode(monkeypatch):
    """Solve with the product's time limit: importing ``scripts.run_regression`` in another test
    of the same worker sets ``EARNIE_CBC_STRICT``, and a strict solve has no time limit."""
    monkeypatch.delenv("EARNIE_CBC_STRICT", raising=False)



def _price(moment: datetime) -> float:
    return 30.0 if moment.hour < 6 else 45.0


def _matrix(start: datetime = _START) -> list[dict]:
    rows: list[dict] = []
    moment = start
    while moment < _END:
        rows.append(
            {
                "hour": moment.hour,
                "date": moment.date(),
                "slot_datetime": moment,
                "k_act": _price(moment),
                "price_buy": _price(moment) / 100.0,
                "expected_p_act": 0.3,
                "expected_p_pv": 0.0,
                "consumption_mode": "forecast",
            }
        )
        moment += slot_step()
    return rows


def _pool() -> dict:
    return planning_thermal_rc_to_milp(
        {
            "id": _CID,
            "label": "Pool / SwimSpa",
            "type": "thermal_rc",
            "nominal_power_kw": 2.8,
            "min_on_quarterhours": 1,
            "thermal_rc": {
                "water_volume_liters": 5900.0,
                "setpoint_c": 37.5,
                "tolerance_c": 1.0,
                "heat_loss_kw_per_k": 0.02,
                "heating_efficiency": 0.99,
            },
        }
    )


_READINGS = {
    "actual_c": 37.5,
    "setpoint_c": 37.5,
    "tolerance_c": 1.0,
    "ambient_c": 2.0,
    "missing_signals": [],
}


@pytest.fixture
def readings():
    """Measured readings of the pool; tests may change them before the solve."""
    return dict(_READINGS)


@pytest.fixture
def pool_readings(readings):
    with (
        patch("integrations.ehal_live.fetch_thermal_readings", side_effect=lambda *_a, **_k: dict(readings)),
        patch(
            "optimizer.thermal_targets.get_outdoor_forecast_with_fallback",
            side_effect=lambda **kw: ([2.0] * kw["horizon"], "test"),
        ),
    ):
        yield


def _solve(matrix: list[dict], pool: dict | None = None):
    from optimizer.milp import HEAT_STORE_PLANNED_KEY, HORIZON_SCHEDULE_KEY, milp_optimizer
    from optimizer.targets import resolve_horizon_target_kwh

    pool = pool or _pool()
    target = resolve_horizon_target_kwh(pool, None, optimization_matrix=matrix)
    battery = {
        "battery_capacity_kwh": 0.01,
        "max_power_kw": 0.001,
        "min_soc": 10.0,
        "max_soc": 10.0001,
        "efficiency": 0.95,
    }
    result = milp_optimizer(
        matrix,
        matrix[0]["hour"],
        10.0,
        battery_params=battery,
        verbose=False,
        consumers=[pool],
        consumer_remaining_kwh={_CID: target},
    )
    plan = result[5]
    energy = [
        float((slot.get("consumer_powers") or {}).get(_CID, 0.0) or 0.0) * DEFAULT_DT_H
        for slot in plan[HORIZON_SCHEDULE_KEY]
    ]
    return target, energy, plan.get(HEAT_STORE_PLANNED_KEY, ())


def _kwh_between(matrix: list[dict], energy: list[float], start: datetime, end: datetime) -> float:
    return sum(
        kwh for row, kwh in zip(matrix, energy) if start <= row["slot_datetime"] < end
    )


def _simulate_temp_c(energy: list[float], start_c: float = 37.5) -> list[float]:
    """Water temperature after each slot (QH Euler of the RC model, ambient 2 °C)."""
    capacity = 5.9 * 1.163
    temp = start_c
    temps = []
    for kwh in energy:
        loss = 0.02 * (temp - 2.0) * DEFAULT_DT_H
        temp += (0.99 * kwh - loss) / capacity
        temps.append(temp)
    return temps


def test_live_pool_heats_in_the_cheap_night_and_holds_the_band(pool_readings):
    matrix = _matrix()
    with live_cycle_scope():
        target, energy, store_planned = _solve(matrix)

    assert target > 20.0  # 9 RC heating hours over the horizon
    night = _kwh_between(matrix, energy, datetime(2026, 11, 28, 0), datetime(2026, 11, 28, 6))
    today = _kwh_between(matrix, energy, _START, datetime(2026, 11, 28, 0))
    assert night > 8.0, energy
    # Only the hour the band needs before midnight (the water reaches 36.5 °C at ~23:00).
    assert today <= 2.8 + 1e-6, energy
    assert min(_simulate_temp_c(energy)) >= 36.5 - 0.05
    assert max(_simulate_temp_c(energy)) <= 38.5 + 0.05
    assert _CID in store_planned


def test_store_level_matches_the_rc_model_without_heat(pool_readings):
    from optimizer.thermal_targets import thermal_rc_live_store

    matrix = _matrix()
    store = thermal_rc_live_store(_pool(), matrix, DEFAULT_DT_H)
    capacity = 5.9 * 1.163
    assert store.capacity_kwh == pytest.approx(2.0 * capacity)
    assert store.start_kwh == pytest.approx(1.0 * capacity)
    level = store.start_kwh
    for drain in store.drain_kwh:
        level = (1.0 - store.leak_per_slot) * level - drain
    temps = _simulate_temp_c([0.0] * len(matrix))
    assert 36.5 + level / capacity == pytest.approx(temps[-1], abs=1e-9)


def test_measured_rc_target_keeps_todays_delivered_heat(monkeypatch, pool_readings):
    """The RC target starts at the measured temperature; today's kWh are already in it."""
    import optimizer

    pool = _pool()
    monkeypatch.setattr(
        optimizer,
        "_load_consumer_state",
        lambda _ctx, _active: {"delivered": {_CID: 14.0}, "charging_sessions": {}},
    )
    monkeypatch.setattr(
        optimizer,
        "resolve_horizon_consumer_targets_kwh",
        lambda _matrix, _targets: {_CID: 25.2},
    )
    monkeypatch.setattr(optimizer, "adjust_targets_for_native_filter", lambda r, *_a: r)
    with live_cycle_scope():
        remaining = optimizer.get_consumer_remaining_kwh(
            [pool], _matrix(), charging_contexts={}
        )
    assert remaining[_CID] == pytest.approx(25.2)


def test_only_live_planning_keeps_todays_delivered_heat():
    """Same condition as the Live store level: outside Live the target stays today's rest."""
    from optimizer.targets import is_measured_thermal_target

    pool = _pool()
    assert not is_measured_thermal_target(pool, _matrix())  # replay outside a Live cycle
    with live_cycle_scope():
        assert is_measured_thermal_target(pool, _matrix())
        spec = [dict(_matrix()[0], consumption_mode="profile_spec")]
        assert not is_measured_thermal_target(pool, spec)
        assert not is_measured_thermal_target({"daily_target_source": "config"}, _matrix())


@pytest.mark.parametrize("minute", [15, 30, 45])
def test_live_matrix_starting_inside_an_hour_is_planned(pool_readings, minute):
    """Review finding: a start at :15 reaches one wall hour more than its slot count."""
    matrix = _matrix(_START.replace(minute=minute))
    with live_cycle_scope():
        _target, energy, store_planned = _solve(matrix)
    assert _CID in store_planned
    night = _kwh_between(matrix, energy, datetime(2026, 11, 28, 0), datetime(2026, 11, 28, 6))
    assert night > 8.0, energy


def test_water_below_the_band_is_heated_back_at_once(pool_readings, readings):
    """Review finding: a start below the band drifted with the leak only (days)."""
    readings["actual_c"] = 35.0
    matrix = _matrix()
    with live_cycle_scope():
        _target, energy, _planned = _solve(matrix)
    temps = _simulate_temp_c(energy, start_c=35.0)
    assert energy[:4] == pytest.approx([0.7] * 4)  # heats in the first hour, at 45 ct
    # 1.5 K below the band, 2.8 kW: back in the band after about 4 h and from then on.
    assert min(temps[20:]) >= 36.5 - 0.05, temps


def test_fixed_heat_path_without_reference_fails_loud(pool_readings):
    from optimizer.thermal_targets import thermal_rc_live_store

    pool = _pool()
    pool["thermal_control"]["heat_paths"] = [{"heat_loss_kw_per_k": 0.01, "reference": "fixed"}]
    with pytest.raises(ValueError, match="reference_temp_c"):
        thermal_rc_live_store(pool, _matrix(), DEFAULT_DT_H)


def test_fixed_heat_path_enters_leak_and_drain(pool_readings):
    from optimizer.thermal_targets import thermal_rc_live_store

    pool = _pool()
    pool["thermal_control"]["heat_paths"] = [
        {"heat_loss_kw_per_k": 0.01, "reference": "fixed", "reference_temp_c": 10.0}
    ]
    store = thermal_rc_live_store(pool, _matrix(), DEFAULT_DT_H)
    capacity = 5.9 * 1.163
    assert store.leak_per_slot == pytest.approx(DEFAULT_DT_H * 0.03 / capacity)
    expected_drain = DEFAULT_DT_H * (0.02 * (36.5 - 2.0) + 0.01 * (36.5 - 10.0))
    assert store.drain_kwh[0] == pytest.approx(expected_drain)

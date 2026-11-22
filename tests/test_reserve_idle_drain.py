"""Reserve P4: idle drain of the house battery in the model and learned from the SoC reading.

Spec: ``docs/dev/virtual-reserve-price-aware.md`` § Design 4.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from house_config.battery_normalize import normalize_battery
from house_config.entity_resolution import battery_params_from_planning, planning_battery_entry
from optimizer import battery as bat
from optimizer.milp import _solve_milp_to_model, milp_horizon_schedule
from optimizer.milp_horizon import plant_battery_params
from optimizer.powerstation_reserve import VIRTUAL_RESERVE_BASE_MIN_SOC_KEY
from runtime_store import idle_drain_learner as learner

DT_H = 0.25
DRAIN_KW = 0.125
BATTERY = {
    "id": "haus",
    "battery_capacity_kwh": 15.0,
    "max_power_kw": 5.0,
    "min_soc": 5.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
    "threshold_power": 0.02,
}
DRAINING = {**BATTERY, bat.IDLE_DRAIN_KEY: DRAIN_KW}
DRAIN_PCT_PER_SLOT = DRAIN_KW * DT_H / 15.0 * 100.0  # 0.2083 %
SOC_TOLERANCE = 0.11  # planned SoC is rounded to 0.1 %


# --- battery parameter and simulation step -------------------------------------------------


def test_apply_soc_change_without_drain_is_unchanged():
    assert bat.idle_drain_kwargs(BATTERY) == {}
    assert bat.apply_soc_change(50.0, 0.0, 15.0, 0.95, 5.0, 100.0, dt_h=DT_H) == (50.0, 0.0)


def test_apply_soc_change_drains_after_the_action_and_keeps_the_power():
    soc, power = bat.apply_soc_change(
        50.0, 1.0, 15.0, 0.95, 5.0, 100.0, dt_h=DT_H, **bat.idle_drain_kwargs(DRAINING)
    )
    assert power == 1.0
    assert soc == pytest.approx(50.0 + 1.0 * 0.95 * DT_H / 15.0 * 100.0 - DRAIN_PCT_PER_SLOT)


def test_drain_stops_at_the_configured_min_soc():
    kwargs = bat.idle_drain_kwargs(DRAINING)
    soc, _ = bat.apply_soc_change(5.1, 0.0, 15.0, 0.95, 5.0, 100.0, dt_h=DT_H, **kwargs)
    assert soc == pytest.approx(5.0)
    soc, _ = bat.apply_soc_change(4.0, 0.0, 15.0, 0.95, 5.0, 100.0, dt_h=DT_H, **kwargs)
    assert soc == pytest.approx(4.0)


def test_drain_runs_through_a_virtual_reserve_floor_down_to_the_base_min_soc():
    reserved = {**DRAINING, "min_soc": 12.33, VIRTUAL_RESERVE_BASE_MIN_SOC_KEY: 5.0}
    assert bat.idle_drain_floor_soc(reserved) == 5.0
    assert bat.idle_drain_soc_pct(12.33, reserved, dt_h=DT_H) == pytest.approx(DRAIN_PCT_PER_SLOT)
    assert bat.idle_drain_soc_pct(5.0, reserved, dt_h=DT_H) == 0.0


def test_vendor_mode_hold_loses_the_drain():
    soc, power = bat.vendor_mode_step(50.0, 0.0, DRAINING, dt_h=DT_H)
    assert power == 0.0
    assert soc == pytest.approx(50.0 - DRAIN_PCT_PER_SLOT)


def test_negative_drain_fails_loud():
    with pytest.raises(ValueError, match="idle_drain_kw"):
        bat.idle_drain_kw({**BATTERY, bat.IDLE_DRAIN_KEY: -0.1})


def test_hold_cost_function_for_reserve_p2():
    assert bat.idle_drain_hold_kwh(DRAINING, 4.0) == pytest.approx(0.5)
    assert bat.idle_drain_hold_kwh(BATTERY, 4.0) == 0.0
    with pytest.raises(ValueError):
        bat.idle_drain_hold_kwh(DRAINING, -1.0)


def test_plant_battery_sums_the_drain():
    second = {**DRAINING, "id": "zwei", bat.IDLE_DRAIN_KEY: 0.05}
    assert plant_battery_params([DRAINING, second])[bat.IDLE_DRAIN_KEY] == pytest.approx(0.175)
    assert bat.IDLE_DRAIN_KEY not in plant_battery_params([BATTERY, {**BATTERY, "id": "zwei"}])


# --- house config -----------------------------------------------------------------------------


def _raw_battery(**extra) -> dict:
    return {
        "id": "haus",
        "label": "Haus",
        "type": "house",
        "inverter_id": "wr",
        "battery_capacity_kwh": 15.0,
        "battery_max_charge_power_kw": 5.0,
        "battery_max_discharge_power_kw": 5.0,
        "battery_efficiency": 0.95,
        "battery_min_soc": 5.0,
        "battery_max_soc": 100.0,
        "regulates_on": "grid",
        **extra,
    }


def test_components_battery_without_field_has_no_drain_key():
    assert "idle_drain_kw" not in normalize_battery(_raw_battery(), 0)


def test_components_battery_drain_reaches_the_optimizer_params():
    normalized = normalize_battery(_raw_battery(idle_drain_kw=0.125), 0)
    entry = {**planning_battery_entry(normalized), "inverter_efficiency": 1.0}
    assert battery_params_from_planning(entry)[bat.IDLE_DRAIN_KEY] == 0.125


@pytest.mark.parametrize("value", [-0.1, "viel"])
def test_components_battery_invalid_drain_fails_loud(value):
    with pytest.raises(ValueError, match="idle_drain_kw"):
        normalize_battery(_raw_battery(idle_drain_kw=value), 0)


# --- MILP -------------------------------------------------------------------------------------


def _matrix(prices: list[float], *, load_kw: float = 0.0) -> list[dict]:
    start = datetime(2025, 11, 21)
    return [
        {
            "hour": 0,
            "date": start.date(),
            "slot_datetime": start + timedelta(minutes=15 * t),
            "expected_p_pv": 0.0,
            "expected_p_act": load_kw,
            "k_act": price,
            "k_push_act": 0.0,
        }
        for t, price in enumerate(prices)
    ]


def _schedule(matrix: list[dict], soc: float, battery: dict) -> list[dict]:
    schedule = milp_horizon_schedule(
        matrix, soc, battery_params=battery, k_push=0.0, verbose=False, consumers=[]
    )
    assert len(schedule) == len(matrix)
    assert all(slot["planned_soc_percent"] is not None for slot in schedule)
    return schedule


def _drain_vars(battery: dict, soc: float) -> list:
    solved = _solve_milp_to_model(
        _matrix([30.0] * 4), soc, battery, 0.0, False, [], *([None] * 9)
    )
    assert solved is not None
    return [v for v in solved[0].prob.variables() if v.name.startswith("idle_drain_off")]


def test_milp_without_drain_has_no_drain_variables():
    assert _drain_vars(BATTERY, 50.0) == []
    assert len(_drain_vars(DRAINING, 50.0)) == 3  # slot 0 is a constant


def test_milp_idle_battery_loses_the_drain_each_slot():
    schedule = _schedule(_matrix([30.0] * 8), 50.0, DRAINING)
    for slot in schedule:
        assert slot["milp_plan"]["p_charge"] <= 1e-6
        assert slot["milp_plan"]["p_discharge"] <= 1e-6
    socs = [slot["planned_soc_percent"] for slot in schedule]
    assert socs[-1] == pytest.approx(50.0 - 8 * DRAIN_PCT_PER_SLOT, abs=SOC_TOLERANCE)


def test_milp_drain_stops_at_min_soc_without_forced_charge():
    schedule = _schedule(_matrix([30.0] * 8), 5.0, DRAINING)
    assert all(slot["milp_plan"]["p_charge"] <= 1e-6 for slot in schedule)
    assert all(slot["planned_soc_percent"] == pytest.approx(5.0) for slot in schedule)


def test_milp_holding_a_reserve_floor_recharges_the_drain():
    reserved = {**DRAINING, "min_soc": 12.4, VIRTUAL_RESERVE_BASE_MIN_SOC_KEY: 5.0}
    schedule = _schedule(_matrix([30.0] * 8), 12.4, reserved)
    charged_kwh = sum(slot["milp_plan"]["p_charge"] for slot in schedule) * 0.95 * DT_H
    assert charged_kwh == pytest.approx(8 * DRAIN_KW * DT_H, rel=1e-3)
    assert all(slot["planned_soc_percent"] >= 12.4 - SOC_TOLERANCE for slot in schedule)


# --- setpoint from the plan ---------------------------------------------------------------------


def _row(load_kw: float) -> dict:
    return {"expected_p_pv": 0.0, "expected_p_act": load_kw}


def test_setpoint_hold_slot_is_not_a_discharge():
    plan = {"p_charge": 0.0, "p_discharge": 0.0, "p_grid_buy": 1.0, "p_grid_sell": 0.0}
    mode, power, _ = bat.derive_control_from_milp_plan(
        plan, _row(1.0), 0.0, 50.0, 50.0 - DRAIN_PCT_PER_SLOT, {**DRAINING, "control": "full"},
        dt_h=DT_H,
    )
    assert mode == bat.MODE_ENTLADESPERRE
    assert power == 0.0


def test_setpoint_charge_power_includes_the_drain():
    p_charge = 2.0
    planned = 50.0 + (p_charge * 0.95 * DT_H / 15.0 * 100.0) - DRAIN_PCT_PER_SLOT
    plan = {"p_charge": p_charge, "p_discharge": 0.0, "p_grid_buy": 2.0, "p_grid_sell": 0.0}
    mode, power, _ = bat.derive_control_from_milp_plan(
        plan, _row(0.0), 0.0, 50.0, planned, {**DRAINING, "control": "full"}, dt_h=DT_H
    )
    assert mode == bat.MODE_ZWANGS_LADEN
    # the planned SoC is rounded to 0.1 % (= 0.06 kW on 15 kWh)
    assert power == pytest.approx(p_charge, abs=0.07)


# --- learner ------------------------------------------------------------------------------------

T0 = datetime(2026, 11, 21, 18, 0)


def _feed(path, readings, *, battery_kw=None, hold_power_kw=0.1, battery_id="haus"):
    """Feed (minute, soc) readings every 30 s between the given points; returns episodes."""
    episodes = []
    for index, (minute, soc) in enumerate(readings):
        kw = 0.0 if battery_kw is None else battery_kw(minute)
        sample = {
            "ts": (T0 + timedelta(minutes=minute)).isoformat(),
            "soc_percent": soc,
            "battery_kw": kw,
        }
        episode = learner.observe_sample(
            sample,
            battery_id=battery_id,
            capacity_kwh=15.0,
            hold_power_kw=hold_power_kw,
            state_path=str(path),
        )
        if episode is not None:
            episodes.append(episode)
    return episodes


def _steps(changes: list[tuple[float, float]], end_minute: float) -> list[tuple[float, float]]:
    """30-s samples of a reading that changes at the given (minute, soc) points."""
    out = []
    minute = 0.0
    while minute <= end_minute:
        soc = [s for m, s in changes if m <= minute][-1]
        out.append((minute, soc))
        minute += 0.5
    return out


def test_learner_drain_between_two_drops_of_the_reading(tmp_path):
    path = tmp_path / "learner.json"
    # 12 % from the start, drops at 10 min and at 82 min: 1 % of 15 kWh in 1.2 h = 0.125 kW
    episodes = _feed(path, _steps([(0, 12.0), (10, 11.0), (82, 10.0)], 90))
    assert len(episodes) == 1
    assert episodes[0]["drain_kw"] == pytest.approx(0.125)
    assert episodes[0]["hours"] == pytest.approx(1.2)
    # the first observed drop has no known start: no episode at 10 min
    assert episodes[0]["start"] == (T0 + timedelta(minutes=10)).isoformat(timespec="seconds")


def test_learner_ignores_an_interval_with_charge_or_discharge(tmp_path):
    path = tmp_path / "learner.json"
    episodes = _feed(
        path,
        _steps([(0, 12.0), (10, 11.0), (82, 10.0)], 90),
        battery_kw=lambda minute: -0.5 if 40 <= minute < 41 else 0.0,
    )
    assert episodes == []


def test_learner_needs_two_drops_not_a_rise_then_a_drop(tmp_path):
    path = tmp_path / "learner.json"
    episodes = _feed(path, _steps([(0, 12.0), (10, 13.0), (82, 12.0)], 90))
    assert episodes == []


def test_learner_starts_over_after_a_gap_in_the_samples(tmp_path):
    path = tmp_path / "learner.json"
    readings = [r for r in _steps([(0, 12.0), (10, 11.0), (82, 10.0)], 90) if not 30 < r[0] < 45]
    assert _feed(path, readings) == []


def test_learned_value_is_the_median_after_enough_episodes(tmp_path):
    path = tmp_path / "learner.json"
    # drops every 72 min (0.125 kW), one at 60 min (0.15 kW)
    readings = _steps([(0, 20.0), (10, 19.0), (82, 18.0), (154, 17.0), (214, 16.0)], 220)
    split = readings.index((160.0, 17.0))
    _feed(path, readings[:split])
    assert learner.learned_idle_drain(str(path))["drain_kw"] is None  # 2 episodes
    _feed(path, readings[split:])
    result = learner.learned_idle_drain(str(path))
    assert result["episodes"] == 3
    assert result["drain_kw"] == pytest.approx(0.125)
    assert result["battery_id"] == "haus"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 1


def test_learner_another_battery_starts_over(tmp_path):
    path = tmp_path / "learner.json"
    _feed(path, _steps([(0, 12.0), (10, 11.0), (82, 10.0)], 90))
    _feed(path, [(200, 50.0)], battery_id="neu")
    assert learner.learned_idle_drain(str(path))["episodes"] == 0


def test_live_hook_does_not_learn_with_several_house_batteries(tmp_path):
    path = tmp_path / "learner.json"
    batteries = [BATTERY, {**BATTERY, "id": "zwei"}]
    assert learner.observe_latest_live_sample(batteries, state_path=str(path)) is None
    assert "2 house batteries" in learner.learned_idle_drain(str(path))["unsupported"]


def test_live_hook_feeds_the_newest_sampler_sample(tmp_path, monkeypatch):
    path = tmp_path / "learner.json"
    from runtime_store import power_interval_sampler

    sample = {"ts": T0.isoformat(), "soc_percent": 12.0, "battery_kw": 0.0}
    monkeypatch.setattr(power_interval_sampler, "latest_sample", lambda **_: sample)
    learner.observe_latest_live_sample([BATTERY], state_path=str(path))
    state = learner.load_state(str(path))
    assert state["last"]["soc"] == 12.0
    assert state["battery_id"] == "haus"

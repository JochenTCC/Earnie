"""Chart 1 and the savings forecast show the control solve's plan (no display solve).

Bug (NAS 2.8.0-dev.40, 2026-11-24): each Live cycle solved the MILP a second time for
Chart 1 / the forecast with a shorter time limit. On a slow machine that solve stopped in
its gap fallback and showed a different plan (all flex loads in the evening price peak)
than the one that was sent. Now the control solve carries its whole horizon
(``milp_plan["horizon_schedule"]``) and the chart applies it slot by slot; an Automatik
cycle without an optimal solve shows no plan at all.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

import main as main_module
from optimizer import sim_costs
from optimizer.milp import HORIZON_SCHEDULE_KEY, milp_horizon_schedule, milp_optimizer
from optimizer.run_trigger import TRIGGER_QUARTER_HOUR
from optimizer.simulation import simulate_horizon
from optimizer.targets import consumer_column_name
from runtime_store import live_optimization_debug
from tests.main_run_harness import patch_main_run

BATTERY = {
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
    "battery_wear": {"enabled": False},
}

SPA = {
    "id": "swimspa",
    "name": "Swimspa",
    "nominal_power_kw": 2.0,
    "min_on_quarterhours": 1,
    "daily_target_kwh": 1.0,
    "daily_target_source": "config",
    "chart_color_index": 0,
}

COL_BATTERY = "Geplante Batterie-Aktion (kW)"


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr("config.get_flexible_consumers", lambda *_a, **_k: [dict(SPA)])
    monkeypatch.setattr("config.get_battery_params", lambda: dict(BATTERY))
    monkeypatch.setattr("config.get_battery_params_list", lambda: [dict(BATTERY)])


def _matrix(slots: int = 8) -> list[dict]:
    """Expensive first half, cheap second half."""
    day = datetime(2025, 6, 1)
    return [
        {
            "hour": t // 4,
            "date": day.date(),
            "slot_datetime": day.replace(hour=t // 4, minute=15 * (t % 4)),
            "expected_p_pv": 0.0,
            "expected_p_act": 0.5,
            "k_act": 40.0 if t < slots // 2 else 10.0,
            "k_push_act": 5.0,
            "expected_flex_kw": {},
        }
        for t in range(slots)
    ]


def _control_plan(matrix: list[dict], remaining: dict[str, float]) -> list[dict]:
    """The control solve's horizon, as ``milp_optimizer`` hands it to main."""
    *_controls, plan, _obs = milp_optimizer(
        matrix,
        current_hour=0,
        current_soc=50.0,
        battery_params=BATTERY,
        k_push=5.0,
        verbose=False,
        consumers=[dict(SPA)],
        consumer_remaining_kwh=remaining,
    )
    return plan[HORIZON_SCHEDULE_KEY]


def _no_solve():
    """Any MILP solve in the chart path fails the test."""
    return (
        patch("optimizer.simulation.milp_horizon_schedule", side_effect=AssertionError("solve")),
        patch("optimizer.simulation.milp_optimizer", side_effect=AssertionError("solve")),
    )


def test_control_solve_carries_its_whole_horizon():
    matrix = _matrix()
    schedule = _control_plan(matrix, {"swimspa": 1.0})
    assert len(schedule) == len(matrix)
    assert schedule == milp_horizon_schedule(
        matrix,
        50.0,
        battery_params=BATTERY,
        k_push=5.0,
        verbose=False,
        consumers=[dict(SPA)],
        consumer_remaining_kwh={"swimspa": 1.0},
    )


def test_chart_rows_reproduce_the_given_plan_without_a_solve():
    matrix = _matrix()
    schedule = _control_plan(matrix, {"swimspa": 1.0})
    no_horizon, no_slot = _no_solve()
    with no_horizon, no_slot:
        rows = simulate_horizon(
            matrix,
            50.0,
            battery_params=BATTERY,
            verbose=False,
            flexible_consumers=[dict(SPA)],
            commit_hours=len(matrix),
            matrix_prepared=True,
            charging_contexts={},
            horizon_schedule=schedule,
        )
    col = consumer_column_name(SPA)
    assert [row[col] for row in rows] == pytest.approx(
        [float(slot["consumer_powers"].get("swimspa", 0.0)) for slot in schedule]
    )
    assert sum(row[col] for row in rows) * 0.25 == pytest.approx(1.0)
    # Battery action per slot is the one the open-loop path makes of the same plan.
    with patch("optimizer.simulation.milp_horizon_schedule", return_value=schedule):
        reference = simulate_horizon(
            matrix,
            50.0,
            battery_params=BATTERY,
            verbose=False,
            flexible_consumers=[dict(SPA)],
            commit_hours=len(matrix),
            matrix_prepared=True,
            charging_contexts={},
            disable_horizon_soc_anchor=True,
        )
    assert [row[COL_BATTERY] for row in rows] == pytest.approx(
        [row[COL_BATTERY] for row in reference]
    )
    assert [row[col] for row in rows] == pytest.approx([row[col] for row in reference])


def test_a_plan_shorter_than_the_matrix_fails_loud():
    matrix = _matrix()
    schedule = _control_plan(matrix, {"swimspa": 1.0})[:-1]
    no_horizon, no_slot = _no_solve()
    with no_horizon, no_slot, pytest.raises(ValueError, match="horizon_schedule"):
        simulate_horizon(
            matrix,
            50.0,
            battery_params=BATTERY,
            verbose=False,
            flexible_consumers=[dict(SPA)],
            commit_hours=len(matrix),
            matrix_prepared=True,
            charging_contexts={},
            horizon_schedule=schedule,
        )


def test_savings_forecast_uses_the_plan_and_its_remaining_energy():
    matrix = _matrix()
    remaining = {"swimspa": 1.0}
    schedule = _control_plan(matrix, remaining)
    no_horizon, no_slot = _no_solve()
    with no_horizon, no_slot:
        info = sim_costs.calculate_optimization_savings(
            matrix,
            50.0,
            # A daily target that differs from the remaining energy: BL Ziel must not use it.
            consumer_daily_targets_kwh={"swimspa": 3.0},
            consumers=[dict(SPA)],
            horizon_schedule=schedule,
            horizon_targets_kwh=remaining,
            charging_contexts={},
        )
    col = consumer_column_name(SPA)
    planned_kwh = sum(row[col] for row in info["optimized_rows"]) * 0.25
    matched_kwh = sum(row.get(col, 0.0) for row in info["matched_baseline_rows"]) * 0.25
    assert planned_kwh == pytest.approx(1.0)
    assert matched_kwh == pytest.approx(1.0)
    applied = {item["id"]: item["target_kwh"] for item in info["applied_targets"]}
    assert applied["swimspa"] == pytest.approx(1.0)


def test_plan_inputs_belong_together():
    matrix = _matrix()
    with pytest.raises(ValueError, match="horizon_targets_kwh"):
        sim_costs.calculate_optimization_savings(
            matrix, 50.0, consumers=[dict(SPA)], horizon_schedule=[{}] * len(matrix)
        )
    with pytest.raises(ValueError, match="nur mit horizon_schedule"):
        sim_costs.calculate_optimization_savings(
            matrix, 50.0, consumers=[dict(SPA)], horizon_targets_kwh={"swimspa": 1.0}
        )


def test_automatik_fallback_has_no_plan():
    matrix = _matrix()
    with patch("optimizer.milp._solve_milp_to_model", return_value=None):
        mode, *_rest, plan, _obs = milp_optimizer(
            matrix,
            current_hour=0,
            current_soc=50.0,
            battery_params=BATTERY,
            k_push=5.0,
            verbose=False,
            consumers=[dict(SPA)],
            consumer_remaining_kwh={"swimspa": 1.0},
        )
    assert mode == 0
    assert HORIZON_SCHEDULE_KEY not in plan


def test_main_automatik_cycle_shows_no_plan_and_solves_nothing_else(monkeypatch, caplog):
    patch_main_run(monkeypatch, silent=True)
    monkeypatch.setattr(
        main_module.optimizer, "milp_optimizer", lambda *a, **k: (0, 0.0, 99.0, {}, {}, {}, {})
    )
    savings_calls: list = []
    monkeypatch.setattr(
        main_module.optimizer,
        "calculate_optimization_savings",
        lambda *a, **k: savings_calls.append(k),
    )
    saved: list[dict] = []
    monkeypatch.setattr(
        main_module.live_optimization_debug,
        "save_debug_snapshot",
        lambda payload, **_: saved.append(payload),
    )
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda _payload: None)

    with caplog.at_level("WARNING"):
        main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert savings_calls == []
    assert len(saved) == 1
    assert saved[0]["no_plan"] == live_optimization_debug.NO_PLAN_AUTOMATIK
    assert saved[0]["simulation_rows"] == []
    assert saved[0].get("planning_matrix")
    assert "kein Plan (Automatik)" in caplog.text


def test_main_passes_the_control_plan_to_the_forecast(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
    schedule = [{"marker": 1}]
    monkeypatch.setattr(
        main_module.optimizer,
        "milp_optimizer",
        lambda *a, **k: (0, 0.0, 99.0, {}, {}, {HORIZON_SCHEDULE_KEY: schedule}, {}),
    )
    monkeypatch.setattr(
        main_module.optimizer, "get_consumer_remaining_kwh", lambda **_: {"swimspa": 1.5}
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        main_module.optimizer,
        "calculate_optimization_savings",
        lambda *a, **k: calls.append(k),
    )
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda _payload: None)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert len(calls) == 1
    assert calls[0]["horizon_schedule"] is schedule
    assert calls[0]["horizon_targets_kwh"] == {"swimspa": 1.5}
    assert calls[0]["charging_contexts"] is not None


# --- the plan's live battery limits and reserves bind the baselines ------------------------


def _deficit_matrix(slots: int = 8) -> list[dict]:
    """No PV: a vendor battery discharges the whole load unless a limit holds it."""
    return [{**row, "expected_p_pv": 0.0, "expected_p_act": 1.0} for row in _matrix(slots)]


def _baseline_discharge_kw(rows: list[dict]) -> float:
    return -sum(min(0.0, float(row[COL_BATTERY])) for row in rows)


def test_live_discharge_limit_zero_binds_the_baselines():
    """Recorded live limit max_discharge_power_kw = 0 (cycle 2026-11-09 11:27 on the NAS).

    The plan cannot discharge; before the fix the baselines ran the configured 5 kW battery
    and the forecast turned negative (plan more expensive than BL Ziel).
    """
    matrix = _deficit_matrix()
    plan_battery = {**BATTERY, "max_discharge_power_kw": 0.0, "max_charge_power_kw": 5.0}
    remaining = {"swimspa": 1.0}
    *_controls, plan, _obs = milp_optimizer(
        matrix,
        current_hour=0,
        current_soc=50.0,
        battery_params=plan_battery,
        k_push=5.0,
        verbose=False,
        consumers=[dict(SPA)],
        consumer_remaining_kwh=remaining,
    )
    info = sim_costs.calculate_optimization_savings(
        matrix,
        50.0,
        consumers=[dict(SPA)],
        horizon_schedule=plan[HORIZON_SCHEDULE_KEY],
        horizon_targets_kwh=remaining,
        charging_contexts={},
        battery_params=plan_battery,
    )
    for key in ("baseline_rows", "matched_baseline_rows", "baseline_same_flex_rows"):
        assert _baseline_discharge_kw(info[key]) == pytest.approx(0.0), key
    assert _baseline_discharge_kw(info["optimized_rows"]) == pytest.approx(0.0)
    # Same battery, same energy: the plan is never worse than BL Ziel here.
    assert info["savings_matched_euro"] >= -1e-6


def test_baselines_hold_the_virtual_reserve_floor():
    from optimizer.reserve_price_floor import FLOOR_SOC_KEY
    from optimizer.sim_baseline import simulate_baseline_horizon

    matrix = _deficit_matrix()
    rows = simulate_baseline_horizon(
        matrix,
        30.0,
        consumers=[dict(SPA)],
        battery_params={**BATTERY, FLOOR_SOC_KEY: 25.0},
    )
    socs = [float(row["Simulierter SoC (%)"]) for row in rows]
    assert min(socs) >= 25.0 - 1e-6
    assert socs[-1] == pytest.approx(25.0, abs=0.5)
    # Without the floor the same battery goes below it.
    free = simulate_baseline_horizon(matrix, 30.0, consumers=[dict(SPA)], battery_params=BATTERY)
    assert float(free[-1]["Simulierter SoC (%)"]) < 25.0


def test_main_passes_the_plan_battery_to_the_forecast(monkeypatch):
    patch_main_run(monkeypatch, silent=True)
    calls: list[dict] = []
    monkeypatch.setattr(
        main_module.optimizer,
        "calculate_optimization_savings",
        lambda *a, **k: calls.append(k),
    )
    sent: list = []

    def _milp(*_a, **k):
        sent.append(k["battery_params"])
        return (0, 0.0, 99.0, {}, {}, {HORIZON_SCHEDULE_KEY: [{}]}, {})

    monkeypatch.setattr(main_module.optimizer, "milp_optimizer", _milp)
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda _payload: None)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert len(calls) == 1
    assert calls[0]["battery_params"] is sent[0]


def test_store_planned_heat_pump_baselines_deliver_the_plan_energy():
    """A store-planned heat pump's remaining kWh is no delivery for the MILP (store band and
    terminal level only): BL Ziel delivers the plan's energy, not the daily-target rest."""
    matrix = _matrix()
    schedule = _control_plan(matrix, {"swimspa": 1.0})
    no_horizon, no_slot = _no_solve()
    with no_horizon, no_slot:
        info = sim_costs.calculate_optimization_savings(
            matrix,
            50.0,
            consumers=[dict(SPA)],
            horizon_schedule=schedule,
            # The rest of the daily target is larger than what the store plan runs.
            horizon_targets_kwh={"swimspa": 3.0},
            charging_contexts={},
            plan_energy_ids=["swimspa"],
        )
    col = consumer_column_name(SPA)
    planned_kwh = sum(row[col] for row in info["optimized_rows"]) * 0.25
    matched_kwh = sum(row.get(col, 0.0) for row in info["matched_baseline_rows"]) * 0.25
    assert planned_kwh == pytest.approx(1.0)
    assert matched_kwh == pytest.approx(1.0)
    applied = {item["id"]: item["target_kwh"] for item in info["applied_targets"]}
    assert applied["swimspa"] == pytest.approx(1.0)


def test_plan_energy_ids_need_the_plan():
    with pytest.raises(ValueError, match="nur mit horizon_schedule"):
        sim_costs.calculate_optimization_savings(
            _matrix(), 50.0, consumers=[dict(SPA)], plan_energy_ids=["swimspa"]
        )


def test_control_plan_names_its_store_planned_heat_pumps(monkeypatch):
    from types import SimpleNamespace

    from optimizer import heat_storage_target, milp
    from optimizer.milp import HEAT_STORE_PLANNED_KEY

    monkeypatch.setattr(heat_storage_target, "forced_charge_ids", lambda *_a: [])
    monkeypatch.setattr(heat_storage_target, "heat_storage_targets", lambda *_a: {})
    monkeypatch.setattr(heat_storage_target, "store_level_report", lambda *_a: {})
    plan: dict = {}
    model = SimpleNamespace(live_store_plans={"wp_b": object(), "wp_a": object()})
    milp._add_heat_storage_plan(plan, model, _matrix())
    assert plan[HEAT_STORE_PLANNED_KEY] == ["wp_a", "wp_b"]


def test_main_passes_the_store_planned_heat_pumps_to_the_forecast(monkeypatch):
    from optimizer.milp import HEAT_STORE_PLANNED_KEY

    patch_main_run(monkeypatch, silent=True)
    calls: list[dict] = []
    monkeypatch.setattr(
        main_module.optimizer,
        "calculate_optimization_savings",
        lambda *a, **k: calls.append(k),
    )
    monkeypatch.setattr(
        main_module.optimizer,
        "milp_optimizer",
        lambda *_a, **_k: (
            0, 0.0, 99.0, {}, {},
            {HORIZON_SCHEDULE_KEY: [{}], HEAT_STORE_PLANNED_KEY: ["waermepumpe"]},
            {},
        ),
    )
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda _payload: None)

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert len(calls) == 1
    assert calls[0]["plan_energy_ids"] == ["waermepumpe"]


def _two_day_matrix() -> list[dict]:
    """8 slots before midnight (expensive), 8 after (cheap)."""
    from datetime import timedelta

    start = datetime(2025, 6, 1, 22, 0)
    rows = []
    for t in range(16):
        at = start + timedelta(minutes=15 * t)
        rows.append(
            {
                "hour": at.hour,
                "date": at.date(),
                "slot_datetime": at,
                "expected_p_pv": 0.0,
                "expected_p_act": 0.5,
                "k_act": 40.0 if t < 8 else 10.0,
                "k_push_act": 5.0,
                "expected_flex_kw": {},
            }
        )
    return rows


def test_bl_ziel_delivers_in_the_plans_delivery_slots():
    """The MILP delivers a consumer without deadline within the day of slot 0; BL Ziel gets
    the same slots, not the cheap night after midnight (2026-11-24 07:29 case)."""
    matrix = _two_day_matrix()
    schedule = _control_plan(matrix, {"swimspa": 1.0})
    info = sim_costs.calculate_optimization_savings(
        matrix,
        50.0,
        consumers=[dict(SPA)],
        horizon_schedule=schedule,
        horizon_targets_kwh={"swimspa": 1.0},
        charging_contexts={},
    )
    col = consumer_column_name(SPA)
    for key in ("optimized_rows", "matched_baseline_rows"):
        rows = info[key]
        assert sum(r.get(col, 0.0) for r in rows[:8]) * 0.25 == pytest.approx(1.0), key
        assert sum(r.get(col, 0.0) for r in rows[8:]) == pytest.approx(0.0), key

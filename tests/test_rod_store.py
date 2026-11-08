"""SE: the heat store caps the heating rod, per slot and across windows (L3 and L2)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from optimizer.rod_store import (
    ROD_STORE_START_KEY,
    STORE_BALANCE_CONTEXT_KEY,
    RodStoreBalance,
    next_level_kwh,
    rod_store_balance,
    rod_store_capacity_kwh,
)
from optimizer.sim_baseline import SurplusRod
from optimizer.slot_duration import DEFAULT_DT_H

DAY = date(2025, 5, 12)
ROD_ID = "wp_heating_heating_rod"
ROD_KW = 3.0
ROD_SLOT_KWH = ROD_KW * DEFAULT_DT_H
SLOTS = 96
# 100 l × 10 K = 1.163 kWh; a heat of 2.4 kWh a day leaves 0.025 kWh per slot.
LITERS = 100.0
BAND_K = 10.0
CAPACITY_KWH = 1.163
GAS = {"type": "gas"}


def _consumer(heat_source: dict = GAS, *, liters: float = LITERS, band_k: float = BAND_K) -> dict:
    return {
        "id": "wp_heating",
        "label": "Heizung",
        "type": "thermal_annual",
        "nominal_power_kw": 1.6,
        "living_area_m2": 157.0,
        "building_class": 2,
        "heat_source": heat_source,
        "persons": 2,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        "heat_storage": {
            "volume_liters": liters,
            "heat_loss_kw_per_k": 0.01,
            "setpoint_c": 60.0,
            "tolerance_c": band_k,
        },
        "parts": [{"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": ROD_KW}],
    }


def _profile(consumer: dict) -> dict:
    return {"id": "home", "latitude": 47.4, "longitude": 9.7, "annual_kwh": 9000.0, "consumers": [consumer]}


def _matrix(prices: list[float], *, first: datetime = datetime(2025, 5, 12, 0, 0)) -> list[dict]:
    rows = []
    for index, price in enumerate(prices):
        slot = first + timedelta(minutes=15 * index)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "k_act": price,
                "price_buy": price / 100.0,
                "expected_p_act": 0.5,
                "expected_p_pv": 0.0,
                "consumption_mode": "profile_spec",
            }
        )
    return rows


@pytest.fixture
def day_heat(monkeypatch):
    """Heat of the main source per day; 2.4 kWh unless a test sets another value."""
    state = {"kwh": 2.4}
    monkeypatch.setattr(
        "optimizer.thermal_flex_context.thermal_daily_heat_kwh_for_date",
        lambda *_args, **_kwargs: state["kwh"],
    )
    return state


def _solve(matrix: list[dict], consumer: dict, *, start_kwh: float | None = None):
    from house_config.planning_flex_bridge import collect_planning_flex_consumers
    from optimizer.cbc_solver import solve_with_strict_fallback
    from optimizer.milp import _add_milp_objective
    from optimizer.milp_consumers import _add_consumer_delivery_constraints, filter_feasible_consumers
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.thermal_flex_context import add_thermal_flex_constraints, resolve_thermal_flex_contexts

    profile = _profile(consumer)
    flex = collect_planning_flex_consumers(profile)
    levels = None if start_kwh is None else {ROD_ID: start_kwh}
    contexts = resolve_thermal_flex_contexts(matrix, flex, profile, rod_store_start_kwh=levels)
    remaining = {ROD_ID: 100.0}
    for entry in flex:
        remaining.setdefault(entry["id"], 0.0)
    indices = list(range(len(matrix)))
    horizon = len(matrix)
    battery = {
        "min_soc": 10.0,
        "max_soc": 10.0001,
        "max_power_kw": 0.001,
        "battery_capacity_kwh": 0.01,
        "efficiency": 0.95,
    }
    planned = filter_feasible_consumers(flex, remaining, matrix, indices, False, {}, {})
    model = _build_milp_model(matrix, horizon, battery, 10.0, planned, 0.0, remaining, {})
    _add_milp_objective(model, matrix, 0.0, {}, wear_cent_per_kwh=0.0)
    _add_consumer_delivery_constraints(model, matrix, remaining, indices, {}, False)
    add_thermal_flex_constraints(model, matrix, indices, contexts)
    assert solve_with_strict_fallback(model.prob, msg=False) == "Optimal"
    on = [slot for slot, var in enumerate(model.consumer_on[ROD_ID]) if (var.varValue or 0.0) > 0.5]
    return on, contexts


# --- the balance ------------------------------------------------------------------------------


def test_level_rises_with_rod_heat_and_falls_with_the_source():
    assert next_level_kwh(1.0, 0.75, 0.25, 10.0) == pytest.approx(1.5)
    assert next_level_kwh(1.0, 0.0, 0.25, 10.0) == pytest.approx(0.75)


def test_level_stays_inside_the_store():
    assert next_level_kwh(0.1, 0.0, 0.25, 10.0) == 0.0
    assert next_level_kwh(10.0, 0.75, 0.25, 10.0) == 10.0


def test_capacity_is_the_band_of_the_store():
    assert rod_store_capacity_kwh(_consumer(liters=500.0, band_k=30.0)) == pytest.approx(0.5 * 1.163 * 30.0)


def test_capacity_without_a_store_fails_loud():
    consumer = _consumer()
    del consumer["heat_storage"]
    with pytest.raises(ValueError, match="kein Wärmespeicher"):
        rod_store_capacity_kwh(consumer)


def test_balance_spreads_the_days_heat_over_its_slots(day_heat):
    day_heat["kwh"] = 24.0
    consumer = _consumer()
    balance = rod_store_balance(
        _matrix([10.0] * 3), ROD_ID, consumer, _profile(consumer), start_levels_kwh=None, climate=None
    )
    assert balance.drain_kwh == pytest.approx([0.25] * 3)


def test_balance_starts_empty_without_levels_and_at_the_carried_level_with_them(day_heat):
    consumer = _consumer()
    alone = rod_store_balance(_matrix([1.0]), ROD_ID, consumer, _profile(consumer), start_levels_kwh=None, climate=None)
    carried = rod_store_balance(
        _matrix([1.0]), ROD_ID, consumer, _profile(consumer), start_levels_kwh={ROD_ID: 0.5}, climate=None
    )
    assert alone.start_kwh == 0.0
    assert carried.start_kwh == 0.5


# --- MILP (L3) --------------------------------------------------------------------------------


def _cheap_noon() -> list[float]:
    """Dear power, except for twelve cheap hours around noon: far more than the store can take."""
    return [40.0] * 24 + [2.0] * 48 + [40.0] * 24


def test_a_full_store_stops_the_rod_although_the_day_needs_more_heat(day_heat):
    """Day heat 24 kWh, store 11.63 kWh: the old day cap would have allowed 32 slots."""
    day_heat["kwh"] = 24.0
    consumer = _consumer(liters=1000.0)
    on, contexts = _solve(_matrix(_cheap_noon()), consumer)
    balance: RodStoreBalance = contexts[ROD_ID][STORE_BALANCE_CONTEXT_KEY]
    assert balance.capacity_kwh == pytest.approx(11.63)
    level = peak = balance.start_kwh
    for slot in range(SLOTS):
        level = max(0.0, level + (ROD_SLOT_KWH if slot in on else 0.0) - balance.drain_kwh[slot])
        peak = max(peak, level)
    assert on
    assert peak <= balance.capacity_kwh + 1e-6
    # What the store took plus the source's heat of the cheap hours: 11.63 + 12 = 23.63 kWh at most.
    assert len(on) * ROD_SLOT_KWH <= 11.63 + 12.0 + 1e-6
    assert all(24 <= slot < 72 for slot in on)


def test_the_store_lets_the_rod_exceed_the_days_heat(day_heat):
    """The surplus of a sunny day is stored for the next one; the old cap stopped at the day's heat."""
    day_heat["kwh"] = 2.4
    on, _contexts = _solve(_matrix(_cheap_noon()), _consumer(liters=1000.0))
    assert len(on) * ROD_SLOT_KWH > 2.4


def test_the_carried_level_leaves_less_room(day_heat):
    consumer = _consumer(liters=1000.0)
    empty, _contexts = _solve(_matrix(_cheap_noon()), consumer, start_kwh=0.0)
    half, _contexts = _solve(_matrix(_cheap_noon()), consumer, start_kwh=6.0)
    assert len(half) < len(empty)


def test_a_day_without_source_heat_keeps_the_rod_off(day_heat):
    day_heat["kwh"] = 0.0
    on, _contexts = _solve(_matrix(_cheap_noon()), _consumer(liters=1000.0))
    assert on == []


def test_an_empty_store_of_one_slot_never_overflows_at_the_edge(day_heat):
    """Room for less than one slot of the rod: it stays off rather than running in part."""
    day_heat["kwh"] = 0.24
    on, _contexts = _solve(_matrix(_cheap_noon()), _consumer(liters=10.0, band_k=10.0))
    assert on == []


def test_the_store_also_caps_a_rod_beside_a_heat_pump(day_heat):
    from house_config.planning_flex_bridge import collect_planning_flex_consumers
    from optimizer.thermal_flex_context import resolve_thermal_flex_contexts

    consumer = _consumer({"type": "heat_pump", "heat_pump_type": "luft"})
    contexts = resolve_thermal_flex_contexts(
        _matrix([1.0] * 4), collect_planning_flex_consumers(_profile(consumer)), _profile(consumer)
    )
    assert contexts[ROD_ID][STORE_BALANCE_CONTEXT_KEY].capacity_kwh == pytest.approx(CAPACITY_KWH)


def test_live_keeps_its_own_bound(monkeypatch, day_heat):
    from house_config.planning_flex_bridge import collect_planning_flex_consumers
    from optimizer import thermal_flex_context

    monkeypatch.setattr("optimizer.live_cycle_scope.is_live_thermal_planning", lambda _matrix: True)
    monkeypatch.setattr(thermal_flex_context, "live_rod_ready", lambda _rod, _parent: True)
    monkeypatch.setattr(thermal_flex_context, "live_rod_heat_cap_kwh", lambda *_args: 5.0)
    consumer = _consumer()
    profile = _profile(consumer)
    contexts = thermal_flex_context.resolve_thermal_flex_contexts(
        _matrix([1.0] * 4), collect_planning_flex_consumers(profile), profile
    )
    assert STORE_BALANCE_CONTEXT_KEY not in contexts[ROD_ID]
    assert contexts[ROD_ID]["daily_heat_cap_kwh"] == {DAY: 5.0}


# --- L2 --------------------------------------------------------------------------------------


def _surplus_rod(*, capacity: float, drain: float, level: float = 0.0, eligible: list[int] | None = None) -> SurplusRod:
    slots = 8
    return SurplusRod(
        cid="rod",
        nominal_kw=ROD_KW,
        eligible=list(range(slots)) if eligible is None else eligible,
        level_kwh=level,
        balance=RodStoreBalance(capacity_kwh=capacity, start_kwh=level, drain_kwh=[drain] * slots),
    )


def test_l2_rod_stops_when_the_store_is_full():
    rod = _surplus_rod(capacity=2.0 * ROD_SLOT_KWH, drain=0.0 + 1e-6)
    assert [rod.run_kw(t, 10.0) for t in range(4)] == [ROD_KW, ROD_KW, 0.0, 0.0]


def test_l2_rod_needs_room_for_the_whole_slot():
    rod = _surplus_rod(capacity=1.5 * ROD_SLOT_KWH, drain=1e-6)
    assert [rod.run_kw(t, 10.0) for t in range(2)] == [ROD_KW, 0.0]


def test_l2_store_drains_with_the_source_while_the_rod_is_off():
    """No export on slot 0–1: the carried level falls and makes room on slot 2."""
    rod = _surplus_rod(capacity=ROD_SLOT_KWH, drain=0.5 * ROD_SLOT_KWH, level=ROD_SLOT_KWH)
    assert rod.run_kw(0, 0.0) == 0.0
    assert rod.level_kwh == pytest.approx(0.5 * ROD_SLOT_KWH)
    assert rod.run_kw(1, 10.0) == ROD_KW
    assert rod.level_kwh == pytest.approx(ROD_SLOT_KWH)


def test_l2_store_drains_outside_the_rods_window():
    rod = _surplus_rod(capacity=10.0, drain=0.5, level=2.0, eligible=[5])
    assert rod.run_kw(0, 10.0) == 0.0
    assert rod.level_kwh == pytest.approx(1.5)


def test_l2_rod_stays_off_without_export_or_source_heat():
    assert _surplus_rod(capacity=10.0, drain=0.5).run_kw(0, ROD_KW - 0.01) == 0.0
    assert _surplus_rod(capacity=10.0, drain=0.0).run_kw(0, 10.0) == 0.0


# --- carried across windows -------------------------------------------------------------------


def test_levels_after_a_window_follow_the_booked_rod(monkeypatch, day_heat):
    from house_config.planning_flex_bridge import collect_planning_flex_consumers
    from optimizer.scenario_planning_scope import planning_scenario_scope
    from simulation.anchor_step import rod_store_levels_after_window

    day_heat["kwh"] = 24.0  # 0.25 kWh per slot
    consumer = _consumer(liters=1000.0)
    profile = _profile(consumer)
    flex = collect_planning_flex_consumers(profile)
    rod = next(entry for entry in flex if entry["id"] == ROD_ID)
    column = f"{rod['name']} (kW)"
    rows = [{column: ROD_KW}, {column: ROD_KW}, {column: 0.0}]
    monkeypatch.setattr(
        "data.modeled_climate.ModeledClimateContext.from_scenario",
        classmethod(lambda cls, _params: None),
    )
    scenario = {"_house_profile": profile}
    with planning_scenario_scope(scenario):
        levels = rod_store_levels_after_window(_matrix([1.0] * 3), rows, flex, scenario, {ROD_ID: 1.0})
    assert levels[ROD_ID] == pytest.approx(1.0 + 2 * ROD_SLOT_KWH - 3 * 0.25)


def test_levels_stay_empty_without_a_rod():
    from simulation.anchor_step import rod_store_levels_after_window

    assert rod_store_levels_after_window(_matrix([1.0]), [{}], [{"id": "ev"}], {}, {}) == {}


def test_the_engine_hands_each_window_the_level_of_the_one_before(monkeypatch):
    from types import SimpleNamespace

    import pandas as pd

    from simulation import engine

    anchors = [datetime(2025, 5, 12), datetime(2025, 5, 13), datetime(2025, 5, 14)]
    started_with: list[dict] = []

    def fake_window(_cfg, _anchor, soc, _hours, _plausibility, levels, _peaks):
        started_with.append(dict(levels))
        return SimpleNamespace(sim_soc=soc, chart_rows=[], matrix=[])

    monkeypatch.setattr(engine, "list_simulation_anchors", lambda *_args: anchors)
    monkeypatch.setattr(
        engine,
        "_init_simulation_run",
        lambda *_args: SimpleNamespace(
            battery_params={}, flexible_consumers=[], feed_in_settings=None, total_hours=1.0, solver_tokens=()
        ),
    )
    monkeypatch.setattr(engine, "_reset_simulation_run", lambda _tokens: None)
    monkeypatch.setattr(engine, "_process_anchor_window", fake_window)
    monkeypatch.setattr(
        engine,
        "rod_store_levels_after_window",
        lambda _matrix, _rows, _consumers, _params, levels: {"rod": levels.get("rod", 0.0) + 1.0},
    )
    monkeypatch.setattr(engine, "_finalize_simulation_result", lambda *_args: pd.DataFrame())
    engine.run_simulation(
        pd.Timestamp("2025-05-12"),
        pd.Timestamp("2025-05-14"),
        {},
        pd.DataFrame(),
        cache=SimpleNamespace(load=lambda: None),
        horizon_mode="fixed_24h",
    )
    assert started_with == [{}, {"rod": 1.0}, {"rod": 2.0}]


def test_the_ladder_hands_each_window_the_level_of_the_one_before(monkeypatch):
    from types import SimpleNamespace

    import pandas as pd

    from simulation import engine, engine_scenario, reference_ladder

    anchors = [datetime(2025, 5, 12), datetime(2025, 5, 13), datetime(2025, 5, 14)]
    started_with: list[dict] = []

    def fake_window(_anchor, soc, **kwargs):
        started_with.append(dict(kwargs["rod_store_kwh"]))
        level = kwargs["rod_store_kwh"].get("rod", 0.0) + 1.0
        return reference_ladder._WindowResult([], {}, soc, [], [], 0, {"rod": level})

    monkeypatch.setattr(engine, "list_simulation_anchors", lambda *_args: anchors)
    monkeypatch.setattr(engine_scenario, "_flexible_consumers_from_scenario", lambda _params: [])
    monkeypatch.setattr(engine_scenario, "_scenario_to_battery_params", lambda _params: {})
    monkeypatch.setattr(engine_scenario, "scenario_standby_power_kw", lambda _params: 0.0)
    monkeypatch.setattr("config.get_backtesting_feed_in_settings", lambda runtime_override=None: None)
    monkeypatch.setattr(reference_ladder, "_shape_source", lambda _cache, _params: None)
    monkeypatch.setattr(reference_ladder, "_window_rows", fake_window)
    monkeypatch.setattr(
        reference_ladder, "validate_window_consumption", lambda _rows, _meta: SimpleNamespace(ok=True)
    )
    monkeypatch.setattr(reference_ladder.PlausibilityReport, "add", lambda _self, _result: None)
    reference_ladder._compute_ladder_step(
        pd.Timestamp("2025-05-12"),
        pd.Timestamp("2025-05-14"),
        {},
        pd.DataFrame(),
        SimpleNamespace(load=lambda: None),
        initial_soc=50.0,
        horizon_mode="fixed_24h",
        rule_params=None,
    )
    assert started_with == [{}, {"rod": 1.0}, {"rod": 2.0}]


def test_the_window_plan_reads_the_carried_level(monkeypatch, day_heat):
    from house_config.planning_flex_bridge import collect_planning_flex_consumers
    from optimizer.milp_inputs import _resolve_thermal_flex_contexts
    from optimizer.scenario_planning_scope import planning_scenario_scope

    consumer = _consumer(liters=1000.0)
    profile = _profile(consumer)
    monkeypatch.setattr(
        "data.modeled_climate.ModeledClimateContext.from_scenario",
        classmethod(lambda cls, _params: None),
    )
    with planning_scenario_scope({"_house_profile": profile, ROD_STORE_START_KEY: {ROD_ID: 3.5}}):
        contexts = _resolve_thermal_flex_contexts(
            _matrix([1.0] * 2), collect_planning_flex_consumers(profile), None
        )
    assert contexts[ROD_ID][STORE_BALANCE_CONTEXT_KEY].start_kwh == 3.5


def test_rod_kwh_of_a_year_stay_within_heat_plus_store():
    """Chain of windows with a free rod: over many days its heat cannot pass demand plus one store."""
    capacity = 5.0
    drain = 0.1
    level = 0.0
    total = 0.0
    for _slot in range(96 * 30):
        heat = ROD_SLOT_KWH if level + ROD_SLOT_KWH - drain <= capacity else 0.0
        level = next_level_kwh(level, heat, drain, capacity)
        total += heat
    assert total <= capacity + 96 * 30 * drain + 1e-6

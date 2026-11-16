"""HeatControl P5: COP by temperature (design § 8.2): curve, sink segments, band, state 4."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pulp
import pytest

from ehal.heat_fields import KIND_SOURCE_TEMP, sg_ready_state_for_plan
from optimizer.heat_pump_cop import CopCurve, cop_curve_from_points
from optimizer.thermal_live_cop import (
    EFFICIENCY_JAZ,
    EFFICIENCY_JAZ_NO_SOURCE_VALUE,
    EFFICIENCY_OUTSIDE_FORECAST,
    EFFICIENCY_SOURCE_SIGNAL,
    LiveEfficiency,
    resolve_live_efficiency,
    segment_edges_c,
)
from optimizer.thermal_store_model import StoreLevelModel, StoreSegment, add_store_level
from tests.test_thermal_store_model import _BAND, _C, _CID, _matrix, _plan, _power, _solve_live

POINTS = [
    {"source_c": 0, "sink_c": 35, "cop": 4.4},
    {"source_c": 0, "sink_c": 55, "cop": 2.8},
    {"source_c": 10, "sink_c": 35, "cop": 5.6},
    {"source_c": 10, "sink_c": 55, "cop": 3.6},
]


def _curve(points=POINTS) -> CopCurve:
    return cop_curve_from_points(points, label="test")


# --- curve ----------------------------------------------------------------------------


def test_curve_returns_the_points_and_interpolates_between_them():
    curve = _curve()
    assert curve.cop_at(0, 35) == pytest.approx(4.4)
    assert curve.cop_at(10, 55) == pytest.approx(3.6)
    assert curve.cop_at(0, 45) == pytest.approx(3.6)  # halfway between 4.4 and 2.8
    assert curve.cop_at(5, 35) == pytest.approx(5.0)
    assert curve.cop_at(5, 45) == pytest.approx((4.4 + 2.8 + 5.6 + 3.6) / 4)


def test_curve_holds_the_edge_value_outside_the_grid():
    curve = _curve()
    assert curve.cop_at(-20, 35) == pytest.approx(4.4)
    assert curve.cop_at(25, 35) == pytest.approx(5.6)
    assert curve.cop_at(0, 20) == pytest.approx(4.4)
    assert curve.cop_at(0, 70) == pytest.approx(2.8)


def test_one_source_temperature_means_no_source_dependence():
    curve = _curve(POINTS[:2])
    assert curve.cop_at(-10, 45) == curve.cop_at(15, 45) == pytest.approx(3.6)


def test_a_two_segment_curve_over_the_source_is_reproduced():
    """SUSI P7 form: two linear pieces over the outside temperature, constant above 12 °C."""
    points = [
        {"source_c": -7, "sink_c": 35, "cop": 3.4},
        {"source_c": 2, "sink_c": 35, "cop": 4.0},
        {"source_c": 12, "sink_c": 35, "cop": 5.5},
    ]
    curve = _curve(points)
    assert curve.cop_at(-2.5, 35) == pytest.approx(3.7)
    assert curve.cop_at(7, 35) == pytest.approx(4.75)
    assert curve.cop_at(20, 35) == pytest.approx(5.5)


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ([], "nicht leere Liste"),
        (POINTS[:3], "kein Raster"),
        (POINTS + [dict(POINTS[0])], "doppelt"),
        ([{"source_c": 0, "sink_c": 35, "cop": 0}], "cop muss > 0"),
        ([{"source_c": 0, "sink_c": 35}], "cop fehlt"),
        ([{"source_c": 0, "sink_c": 35, "cop": 4, "flow": 1}], "unbekannte Felder flow"),
        (
            [{"source_c": 0, "sink_c": 35, "cop": 3.0}, {"source_c": 0, "sink_c": 55, "cop": 3.5}],
            "muss mit der Senkentemperatur fallen",
        ),
        (
            [{"source_c": 0, "sink_c": 35, "cop": 4.0}, {"source_c": 10, "sink_c": 35, "cop": 3.5}],
            "darf mit der Quellentemperatur nicht fallen",
        ),
    ],
)
def test_inconsistent_points_fail_loud(points, message):
    with pytest.raises(ValueError, match=message):
        _curve(points)


def test_heat_source_keeps_cop_points_only_on_a_heat_pump():
    from house_config.heat_source import heat_source_cop_curve, normalize_heat_source

    raw = {"type": "heat_pump", "heat_pump_type": "erde", "cop_points": list(reversed(POINTS))}
    source = normalize_heat_source(raw, label="hs")
    assert source["cop_points"] == [{k: float(v) for k, v in p.items()} for p in POINTS]
    assert heat_source_cop_curve(source).cop_at(0, 35) == pytest.approx(4.4)
    plain = normalize_heat_source({"type": "heat_pump", "heat_pump_type": "erde"}, label="hs")
    assert "cop_points" not in plain and heat_source_cop_curve(plain) is None
    with pytest.raises(ValueError, match="unbekannte Felder.*cop_points"):
        normalize_heat_source({"type": "gas", "cop_points": POINTS}, label="hs")
    with pytest.raises(ValueError, match="nicht leere Liste"):
        normalize_heat_source({**raw, "cop_points": []}, label="hs")


def test_schema_accepts_cop_points():
    import json
    from pathlib import Path

    import jsonschema

    schema = json.loads(
        Path("share/config/house_profiles.schema.json").read_text(encoding="utf-8")
    )
    heat_source = {"definitions": schema["definitions"], **schema["definitions"]["heat_source"]}
    ok = {"type": "heat_pump", "heat_pump_type": "erde", "cop_points": POINTS}
    jsonschema.validate(ok, heat_source)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**ok, "cop_points": [{"source_c": 0, "sink_c": 35}]}, heat_source)


# --- sink segments on a toy problem -----------------------------------------------------


def _segments(n: int, cops=(4.0, 2.0), caps=(5.0, 5.0)) -> tuple[StoreSegment, ...]:
    return tuple(StoreSegment(capacity_kwh=cap, cop=[cop] * n) for cap, cop in zip(caps, cops))


def _toy(prices: list[float], store: StoreLevelModel, max_kwh: float = 10.0):
    """Buy generator electricity per slot at ``prices``; heat by segment."""
    prob = pulp.LpProblem("toy", pulp.LpMinimize)
    power = [pulp.LpVariable(f"e_{t}", 0.0, max_kwh) for t in range(len(prices))]
    prob += pulp.lpSum(p * e for p, e in zip(prices, power))
    level = add_store_level(
        SimpleNamespace(prob=prob), "s", store, list(range(len(prices))),
        lambda t: 0.0, generator_kwh_at=lambda t: power[t],
    )
    assert prob.solve(pulp.PULP_CBC_CMD(msg=0)) == pulp.LpStatusOptimal
    return [e.varValue or 0.0 for e in power], level


def _store(n: int, **kw) -> StoreLevelModel:
    base = dict(
        capacity_kwh=10.0, start_kwh=0.0, efficiency=3.0, drain_kwh=[0.0] * n, segments=_segments(n)
    )
    return StoreLevelModel(**{**base, **kw})


def test_segments_fill_in_the_order_of_their_cop():
    """Done criterion: the efficient segment first, the hot one only for what is left."""
    power, level = _toy([1.0], _store(1, terminal_min_kwh=7.0))
    # 5 kWh at COP 4 and 2 kWh at COP 2.
    assert level.segment_charge_kwh(0) == [pytest.approx(1.25), pytest.approx(1.0)]
    assert power[0] == pytest.approx(2.25)
    assert level.level_kwh(0) == pytest.approx(7.0)


def test_a_partial_charge_stays_in_the_efficient_segment():
    power, level = _toy([1.0], _store(1, terminal_min_kwh=4.0))
    assert level.segment_charge_kwh(0) == [pytest.approx(1.0), pytest.approx(0.0)]


def test_charging_hotter_only_pays_with_a_large_price_spread():
    """Cheap slot 0, demand in slot 1: the hot segment's COP is half, so it needs half the price."""
    drain = [0.0, 8.0]
    spread_small, _ = _toy([6.0, 10.0], _store(2, drain_kwh=drain))
    spread_large, _ = _toy([4.0, 10.0], _store(2, drain_kwh=drain))
    # 6 ct at COP 2 = 3 ct/kWh heat, dearer than 10 ct at COP 4 = 2.5 ct/kWh in slot 1.
    assert spread_small[0] == pytest.approx(5.0 / 4.0)
    assert spread_small[1] == pytest.approx(3.0 / 4.0)
    assert spread_large[0] == pytest.approx(5.0 / 4.0 + 3.0 / 2.0)
    assert spread_large[1] == pytest.approx(0.0)


def test_a_hot_store_is_not_recharged_at_the_cop_of_the_cold_segment():
    """Full store, 5 kWh drawn and recharged in one slot: physically all of it in the hot
    segment (COP 2). The fill order bounds the plan to half of it at the better COP."""
    store = _store(1, start_kwh=10.0, drain_kwh=[5.0], terminal_min_kwh=10.0)
    power, level = _toy([1.0], store)
    assert level.segment_charge_kwh(0) == [pytest.approx(2.5 / 4.0), pytest.approx(2.5 / 2.0)]
    assert power[0] > 5.0 / 4.0 + 0.5  # not all at COP 4


def test_segment_levels_follow_drain_and_leak():
    store = _store(3, start_kwh=8.0, drain_kwh=[1.0] * 3, leak_per_slot=0.1)
    power, level = _toy([1.0] * 3, store)
    assert power == [0.0, 0.0, 0.0]
    expected = 8.0
    for slot in range(3):
        expected = 0.9 * expected - 1.0
        assert level.level_kwh(slot) == pytest.approx(expected)
    assert level.slack_kwh() == pytest.approx(0.0)


def test_segments_with_collector_heat_and_a_start_outside_the_band_stay_feasible():
    above = _store(3, start_kwh=12.0, drain_kwh=[-1.0] * 3, spill_max_kwh=[1.0] * 3)
    _power_kwh, level = _toy([1.0] * 3, above)
    assert level.slack_kwh() == pytest.approx(0.0)
    below = _store(2, start_kwh=-2.0, drain_kwh=[1.0, 0.0], terminal_min_kwh=3.0)
    power, level = _toy([1.0, 1.0], below, max_kwh=100.0)
    assert level.level_kwh(1) == pytest.approx(3.0)


def test_inconsistent_segments_fail_loud():
    with pytest.raises(ValueError, match="zusammen die Speicherkapazität"):
        _store(1, capacity_kwh=12.0)
    with pytest.raises(ValueError, match="muss mit der Temperatur fallen"):
        _store(1, segments=_segments(1, cops=(2.0, 4.0)))
    prob = pulp.LpProblem("toy", pulp.LpMinimize)
    with pytest.raises(ValueError, match="Strom des Erzeugers"):
        add_store_level(SimpleNamespace(prob=prob), "s", _store(1), [0], lambda t: 0.0)


def test_charge_limit_keeps_the_generator_below_the_reserved_room():
    """Cheap heat now, but room is kept free: the generator stops at the limit."""
    n = 2
    prob = pulp.LpProblem("toy", pulp.LpMinimize)
    heat = [pulp.LpVariable(f"h_{t}", 0.0) for t in range(n)]
    on = [pulp.LpVariable(f"on_{t}", cat=pulp.LpBinary) for t in range(n)]
    for t in range(n):
        prob += heat[t] <= 20.0 * on[t]
    prob += pulp.lpSum([1.0 * heat[0], 50.0 * heat[1]])
    store = StoreLevelModel(
        capacity_kwh=10.0, start_kwh=0.0, efficiency=1.0, drain_kwh=[0.0, 8.0],
        charge_limit_kwh=[4.0, 10.0],
    )
    level = add_store_level(
        SimpleNamespace(prob=prob), "s", store, [0, 1], lambda t: heat[t],
        generator_on_at=lambda t: on[t],
    )
    assert prob.solve(pulp.PULP_CBC_CMD(msg=0)) == pulp.LpStatusOptimal
    assert heat[0].varValue == pytest.approx(4.0)
    assert heat[1].varValue == pytest.approx(4.0)
    assert level.slack_kwh() == pytest.approx(0.0)


# --- Live plan: efficiency, band, segments ------------------------------------------------


def _consumer(points=POINTS, bindings: dict | None = None) -> dict:
    source = {"type": "heat_pump", "heat_pump_type": "erde"}
    if points is not None:
        source["cop_points"] = points
    return {
        "id": _CID,
        "type": "thermal_annual",
        "thermal": {"heat_source": source},
        "ehal_bindings": bindings or {},
    }


def test_efficiency_without_cop_points_stays_the_jaz():
    efficiency = resolve_live_efficiency(_consumer(points=None), {KIND_SOURCE_TEMP: 6.0})
    assert efficiency.source == EFFICIENCY_JAZ and not efficiency.by_temperature


def test_efficiency_uses_the_held_source_signal_or_the_outside_forecast():
    signal = resolve_live_efficiency(_consumer(), {KIND_SOURCE_TEMP: 6.5})
    assert (signal.source, signal.source_temp_c) == (EFFICIENCY_SOURCE_SIGNAL, 6.5)
    outside = resolve_live_efficiency(_consumer(), {})
    assert (outside.source, outside.source_temp_c) == (EFFICIENCY_OUTSIDE_FORECAST, None)
    assert outside.by_temperature


def test_mapped_source_signal_without_a_value_falls_back_loud(caplog):
    efficiency = resolve_live_efficiency(_consumer(), {KIND_SOURCE_TEMP: None})
    assert efficiency.source == EFFICIENCY_JAZ_NO_SOURCE_VALUE
    assert not efficiency.by_temperature
    assert "liefert aber keinen Wert" in caplog.text


def _cop_plan(start_c: float = 44.0, **changes):
    base = replace(
        _plan(start_c),
        efficiency=LiveEfficiency(source=EFFICIENCY_SOURCE_SIGNAL, curve=_curve(), source_temp_c=5.0),
    )
    return replace(base, **changes)


def test_band_above_the_setpoint_stays_off_without_cop_points():
    """Done criterion: the reported maximum releases the band only with COP points."""
    jaz = replace(_plan(44.0), boost_k=0.0, store_max_c=60.0, target_mapped=True)
    assert jaz.charge_max_c == pytest.approx(_BAND.setpoint_c)
    assert not jaz.band_released
    with_boost = replace(jaz, boost_k=5.0)
    assert with_boost.charge_max_c == pytest.approx(_BAND.setpoint_c + 5.0)  # as before P5
    curve = _cop_plan(boost_k=0.0, store_max_c=60.0, target_mapped=True)
    assert curve.band_released and curve.charge_max_c == pytest.approx(60.0)


def test_band_release_needs_the_target_signal_and_the_reported_maximum():
    no_target = _cop_plan(boost_k=5.0, store_max_c=60.0, target_mapped=False)
    assert no_target.charge_max_c == pytest.approx(_BAND.setpoint_c + 5.0)
    no_max = _cop_plan(boost_k=5.0, store_max_c=None, target_mapped=True)
    assert no_max.charge_max_c == pytest.approx(_BAND.setpoint_c + 5.0)


def test_no_charge_above_the_setpoint_while_the_source_signal_has_no_value():
    plan = replace(
        _plan(44.0),
        store_max_c=60.0,
        target_mapped=True,
        efficiency=LiveEfficiency(source=EFFICIENCY_JAZ_NO_SOURCE_VALUE),
    )
    assert plan.charge_max_c == pytest.approx(_BAND.setpoint_c)


def test_segment_edges_split_the_band_in_at_most_four_parts():
    assert segment_edges_c(42.0, 47.0, 47.0) == [42.0, 47.0]
    assert segment_edges_c(42.0, 47.0, 57.0) == [42.0, 47.0, 52.0, 57.0]
    assert segment_edges_c(42.0, 47.0, 54.0) == [42.0, 47.0, 50.5, 54.0]
    # 20 K above the setpoint would be four steps of 5 K: three wider ones instead.
    wide = segment_edges_c(42.0, 47.0, 67.0)
    assert len(wide) == 5 and wide[-1] == pytest.approx(67.0)
    assert segment_edges_c(47.0, 47.0, 57.0) == [47.0, 52.0, 57.0]
    with pytest.raises(ValueError, match="ohne Breite"):
        segment_edges_c(47.0, 47.0, 47.0)


def test_live_level_model_gets_segments_with_the_cop_of_their_upper_edge():
    from optimizer.thermal_live_store import live_store_level_model

    plan = _cop_plan()
    store = live_store_level_model(_matrix(), plan, 0.25)
    curve = plan.efficiency.curve
    # Band 42–47 °C, boost 10 K: edges 42 / 47 / 52 / 57 °C, C = 2 kWh/K.
    assert [segment.capacity_kwh for segment in store.segments] == [pytest.approx(10.0)] * 3
    for segment, upper in zip(store.segments, (47.0, 52.0, 57.0)):
        assert segment.cop == [pytest.approx(curve.cop_at(5.0, upper))] * 96
    assert live_store_level_model(_matrix(), _plan(44.0), 0.25).segments == ()


def test_live_level_model_takes_the_outside_forecast_per_slot_without_a_source_signal():
    from optimizer.thermal_live_store import live_store_level_model

    ambient = [float(hour % 12) for hour in range(24)]
    plan = _cop_plan(
        ambient_c=ambient,
        efficiency=LiveEfficiency(source=EFFICIENCY_OUTSIDE_FORECAST, curve=_curve()),
    )
    store = live_store_level_model(_matrix(), plan, 0.25)
    curve = plan.efficiency.curve
    assert store.segments[0].cop[0] == pytest.approx(curve.cop_at(0.0, 47.0))
    assert store.segments[0].cop[4 * 9] == pytest.approx(curve.cop_at(9.0, 47.0))
    assert store.segments[0].cop[4 * 9] > store.segments[0].cop[0]


def test_live_plans_the_store_with_the_cop_curve():
    plan = _cop_plan()
    model, matrix = _solve_live(plan)
    store, levels = model.live_store_levels[_CID]
    assert levels.slack_kwh() == pytest.approx(0.0, abs=1e-6)
    heat = 0.0
    for slot in range(len(matrix)):
        parts = levels.segment_charge_kwh(slot)
        assert sum(parts) == pytest.approx(_power(model, slot) * 0.25, abs=1e-6)
        heat += sum(seg.cop[slot] * part for seg, part in zip(store.segments, parts))
    # Loss-free store: heat in = heat drawn + change of the level.
    drawn = sum(store.drain_kwh[: len(matrix)])
    assert heat == pytest.approx(drawn + levels.level_kwh(len(matrix) - 1) - store.start_kwh, abs=1e-4)


def test_a_steep_curve_keeps_the_plan_out_of_the_hot_segments():
    """Same prices: with a COP that collapses above the setpoint the plan charges less hot."""
    flat = [
        {"source_c": 5, "sink_c": 47, "cop": 4.0},
        {"source_c": 5, "sink_c": 57, "cop": 3.9},
    ]
    steep = [
        {"source_c": 5, "sink_c": 47, "cop": 4.0},
        {"source_c": 5, "sink_c": 52, "cop": 0.5},
    ]

    def top_c(points) -> float:
        plan = _cop_plan(
            efficiency=LiveEfficiency(
                source=EFFICIENCY_SOURCE_SIGNAL, curve=_curve(points), source_temp_c=5.0
            )
        )
        model, matrix = _solve_live(plan)
        _store_model, levels = model.live_store_levels[_CID]
        return _BAND.min_c + max(levels.level_kwh(t) for t in range(len(matrix))) / _C

    steep_top = top_c(steep)
    # The pump runs at fixed power, so the last quarter hour of a run may end a little above.
    assert steep_top <= _BAND.setpoint_c + 1.0
    assert top_c(flat) > steep_top + 2.0


def test_a_charge_limit_at_the_capacity_is_none():
    """Start above the band: the limit applies below the capacity only, not to the drifted bound."""
    prob = pulp.LpProblem("toy", pulp.LpMinimize)
    on = pulp.LpVariable("on", cat=pulp.LpBinary)
    store = StoreLevelModel(
        capacity_kwh=10.0, start_kwh=14.0, efficiency=1.0, drain_kwh=[0.0, 0.0],
        charge_limit_kwh=[10.0, 6.0],
    )
    add_store_level(
        SimpleNamespace(prob=prob), "s", store, [0, 1], lambda t: 0.0,
        generator_on_at=lambda t: on,
    )
    rows = [name for name in prob.constraints if name.startswith("s_charge_limit")]
    assert rows == ["s_charge_limit_1"]


def _collector_plan(collector_kw: float, hours: int = 24):
    """Collector heat from 10:00 to 14:00 beside a draw of 1 kW (net draw = draw − collector)."""
    collector = [0.0] * 10 + [collector_kw] * 4 + [0.0] * (hours - 14)
    return replace(
        _plan(44.0, hours),
        collector_kw_by_hour=collector,
        draw_kw_by_hour=[1.0 - kw for kw in collector],
    )


def test_collector_surplus_closes_the_band_above_the_setpoint_for_the_generator():
    from optimizer.thermal_live_store import live_store_level_model

    plan = _collector_plan(4.0)  # 3 kW beyond the draw for 4 h: 12 kWh surplus
    store = live_store_level_model(_matrix(), plan, 0.25)
    capacity = store.capacity_kwh
    assert capacity == pytest.approx(_C * 15.0)
    # 00:00: the house draws 9.75 kWh before the collector heat comes, 2.25 kWh need room.
    assert store.charge_limit_kwh[0] == pytest.approx(capacity - 2.25)
    # 09:45: the whole surplus lies ahead. 11:45: half of it.
    assert store.charge_limit_kwh[4 * 10 - 1] == pytest.approx(capacity - 12.0)
    assert store.charge_limit_kwh[4 * 12 - 1] == pytest.approx(capacity - 6.0)
    assert store.charge_limit_kwh[4 * 14] == pytest.approx(capacity)
    # In the MILP: no generator run ends above the limit before the collector heat.
    model, matrix = _solve_live(plan)
    _store_model, levels = model.live_store_levels[_CID]
    assert any(_power(model, slot) > 1e-3 for slot in range(4 * 10))
    for slot in range(4 * 14):
        if _power(model, slot) > 1e-3:
            assert levels.level_kwh(slot) <= store.charge_limit_kwh[slot] + 1e-6


def test_the_limit_never_goes_below_the_setpoint():
    from optimizer.thermal_live_store import live_store_level_model

    store = live_store_level_model(_matrix(), _collector_plan(12.0), 0.25)  # 44 kWh surplus
    normal = _C * (_BAND.setpoint_c - _BAND.min_c)
    assert store.charge_limit_kwh[4 * 10 - 1] == pytest.approx(normal)


def test_collector_heat_the_house_uses_up_needs_no_room():
    from optimizer.thermal_live_store import live_store_level_model

    assert live_store_level_model(_matrix(), _collector_plan(0.8), 0.25).charge_limit_kwh == []
    assert live_store_level_model(_matrix(), _plan(44.0), 0.25).charge_limit_kwh == []


def test_the_terminal_level_does_not_ask_for_more_than_the_last_limit():
    """Book to 10:00, surplus right after: normal operation's mean level lies above the limit."""
    from optimizer.thermal_live_store import live_store_terminal_kwh

    plan = replace(_collector_plan(4.0), store_temp_c=[53.0] * 24)
    book_slots = 4 * 10
    model, matrix = _solve_live(plan, book_slots=book_slots)
    store, _levels = model.live_store_levels[_CID]
    limit = store.charge_limit_kwh[book_slots - 1]
    assert live_store_terminal_kwh(matrix, plan, book_slots - 1, 0.25) > limit + 1.0
    assert store.terminal_min_kwh == pytest.approx(limit)


# --- forced charge (SG-Ready state 4) ---------------------------------------------------


def test_state_4_only_for_a_forced_run():
    assert sg_ready_state_for_plan(True, forced=True) == 4
    assert sg_ready_state_for_plan(True) == 3
    assert sg_ready_state_for_plan(False, forced=True) == 2


def _run_model(plan, powers=(2.0, 2.0, 0.0)):
    from optimizer.thermal_store_model import StoreLevelVars

    levels = StoreLevelVars(
        levels={slot: SimpleNamespace(varValue=4.0) for slot in range(len(powers))}, slack={}
    )
    return SimpleNamespace(
        horizon=len(powers),
        dt_h=0.25,
        planned_consumers=[{"id": _CID}],
        consumer_p={_CID: [SimpleNamespace(varValue=p) for p in powers]},
        live_store_plans={_CID: plan},
        live_store_levels={_CID: (None, levels)},
    )


@pytest.mark.parametrize(
    ("price", "curtail_kw", "powers", "with_curve", "expected"),
    [
        (-1.0, 0.0, (2.0, 2.0, 0.0), True, [_CID]),
        (12.0, 1.5, (2.0, 2.0, 0.0), True, [_CID]),
        (12.0, 0.0, (2.0, 2.0, 0.0), True, []),
        (-1.0, 0.0, (0.0, 2.0, 2.0), True, []),  # not running now
        (-1.0, 0.0, (2.0, 2.0, 0.0), False, []),  # JAZ: the energy above the setpoint is not priced
    ],
)
def test_forced_charge_on_negative_price_or_curtailed_surplus(
    price, curtail_kw, powers, with_curve, expected
):
    from optimizer.heat_storage_target import forced_charge_ids

    plan = _cop_plan() if with_curve else _plan(44.0)
    matrix = [{"k_act": price}]
    assert forced_charge_ids(_run_model(plan, powers), matrix, curtail_kw) == expected


def test_forced_charge_targets_the_upper_end_of_the_band():
    from optimizer.heat_storage_target import heat_storage_targets

    plan = _cop_plan(store_max_c=60.0, target_mapped=True)
    model = _run_model(plan)
    assert heat_storage_targets(model)[_CID] == pytest.approx(_BAND.setpoint_c)
    assert heat_storage_targets(model, [_CID])[_CID] == pytest.approx(60.0)


def test_state_4_is_written_for_a_forced_heat_pump():
    from integrations.loxone_writes import _flexible_consumer_output_values

    key = f"heatpump.{_CID}.set_sg_ready_state"
    consumer = {"id": _CID, "name": "WP", "type": "thermal_annual", "ehal_bindings": {key: ""}}
    forced = _flexible_consumer_output_values(
        consumer, {_CID: 2.0}, {}, heat_forced_charge=frozenset({_CID})
    )
    assert forced == {key: 4.0}
    assert _flexible_consumer_output_values(consumer, {_CID: 2.0}, {}) == {key: 3.0}
    off = _flexible_consumer_output_values(
        consumer, {_CID: 0.0}, {}, heat_forced_charge=frozenset({_CID})
    )
    assert off == {key: 2.0}


def test_observability_names_the_efficiency_source():
    from optimizer.thermal_live_cop import efficiency_observability

    assert efficiency_observability(_cop_plan().efficiency, 4.0) == {
        "source": EFFICIENCY_SOURCE_SIGNAL,
        "jaz": 4.0,
        "source_temp_c": 5.0,
        "cop_points": 4,
    }

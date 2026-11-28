"""Live thermal consumers plan over the whole horizon, not only until midnight.

Regression (Live, 2026-11-27): in Live the thermal paths only got the slots of
the current calendar day (``milp_inputs._day_indices``). The heat pump store level ended at
23:45 with its terminal level there, later days had no heat pump load at all, day targets of
later days were dropped, and a heating rod was forced off after midnight.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from house_config.heating_rod_bindings import ROD_BINDINGS_KEY
from house_config.planning_flex_bridge import collect_planning_flex_consumers
from optimizer.slot_duration import DEFAULT_DT_H, slot_step

_CID = "wp_heating"
_ROD_ID = "wp_heating_heating_rod"
_BOUND = {
    f"heatpump.{_ROD_ID}.set_enable": "Rod_En",
    f"heatpump.{_ROD_ID}.sens_power_act": "Rod_P",
}
_VOLUME_L = 2000.0  # band of about 11.6 kWh: a heat pump run of an hour fits into it
_STORAGE = {
    "volume_liters": _VOLUME_L,
    "heat_loss_kw_per_k": 0.002,
    "setpoint_c": 50.0,
    "tolerance_c": 5.0,
}
_HP = {"type": "heat_pump", "heat_pump_type": "luft"}
_GAS = {"type": "gas"}
_START = datetime(2024, 1, 15, 12, 0)
_END = datetime(2024, 1, 16, 12, 0)
_MIDNIGHT = datetime(2024, 1, 16, 0, 0)


@pytest.fixture(autouse=True)
def _product_solver_mode(monkeypatch):
    """Solve with the product's time limit: importing ``scripts.run_regression`` in another test
    of the same worker sets ``EARNIE_CBC_STRICT``, and a strict solve has no time limit."""
    monkeypatch.delenv("EARNIE_CBC_STRICT", raising=False)


def _price(moment: datetime) -> float:
    """Dear before midnight, cheap after; a slight ramp gives the solver one best slot order
    (flat prices leave many equal plans, and the strict test solve has no time limit)."""
    ramp = (moment - _START).total_seconds() / 3600.0 * 0.01
    return (40.0 if moment < _MIDNIGHT else 10.0) + ramp


def _matrix() -> list[dict]:
    rows: list[dict] = []
    moment = _START
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


def _consumer(heat_source: dict, *, storage: dict | None = _STORAGE, rod: bool = False) -> dict:
    consumer = {
        "id": _CID,
        "label": "Heizung",
        "type": "thermal_annual",
        "nominal_power_kw": 1.6,
        "living_area_m2": 0.0,
        "building_class": 2,
        "heat_source": heat_source,
        "persons": 2,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        "parts": [{"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}]
        if rod
        else [],
        "ehal_bindings": {f"heatpump.{_CID}.sens_temperature_heat_storage": "T_Speicher"},
    }
    if storage is not None:
        consumer["heat_storage"] = storage
    if rod:
        consumer[ROD_BINDINGS_KEY] = _BOUND
    return consumer


def _profile(consumer: dict) -> dict:
    return {
        "id": "home",
        "latitude": 47.4,
        "longitude": 9.7,
        "annual_kwh": 9000.0,
        "consumers": [consumer],
    }


def _store_plan(start_c: float, *, jaz: float, wp_kw: float = 1.6, horizon: int = 48):
    """A store that draws heat (two persons' hot water, loss) over two days."""
    from optimizer.thermal_coupled import capacity_kwh_per_k_from_volume
    from optimizer.thermal_live_store import ThermalBand, plan_live_store_horizon

    return plan_live_store_horizon(
        start_temp_c=start_c,
        ambient_forecast_c=[5.0] * horizon,
        band=ThermalBand(50.0, 5.0),
        capacity_kwh_per_k=capacity_kwh_per_k_from_volume(_VOLUME_L),
        heat_loss_kw_per_k=0.01,
        wp_electric_kw=wp_kw,
        jaz=jaz,
        persons=2,
    )


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr("optimizer.live_cycle_scope.is_live_thermal_planning", lambda _m: True)
    monkeypatch.setattr(
        "optimizer.absent_mode.resolve_absent_status", lambda _profile: {"effective": False}
    )
    monkeypatch.setattr("optimizer.thermal_flex_context.live_rod_ready", lambda _r, _p: True)

    def use(profile, *, plan=None, house_slot_kwh=None):
        monkeypatch.setattr(
            "config.get_resolved_runtime_settings", lambda: {"_house_profile": profile}
        )
        monkeypatch.setattr(
            "optimizer.thermal_live_store.live_store_plan_for_matrix",
            lambda _source, _profile, _matrix: plan,
        )
        if house_slot_kwh is not None:
            monkeypatch.setattr(
                "optimizer.thermal_flex_context._live_house_slot_energy_kwh",
                lambda matrix, _source, _profile: [house_slot_kwh] * len(matrix),
            )
            monkeypatch.setattr(
                "optimizer.targets._live_house_horizon_need_kwh",
                lambda _source, _profile, matrix: house_slot_kwh * len(matrix),
            )

    return use


def _solve(matrix: list[dict], profile: dict):
    """The Live control solve as ``main`` runs it (no SE book)."""
    from optimizer.milp import HORIZON_SCHEDULE_KEY, milp_optimizer
    from optimizer.targets import resolve_horizon_consumer_targets_kwh

    flex = collect_planning_flex_consumers(profile)
    remaining = resolve_horizon_consumer_targets_kwh(matrix, None, flexible_consumers=flex)
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
        consumers=flex,
        consumer_remaining_kwh=remaining,
    )
    return result[5][HORIZON_SCHEDULE_KEY]


def _kwh(matrix: list[dict], schedule: list[dict], cid: str, start: datetime, end: datetime):
    return sum(
        float((slot.get("consumer_powers") or {}).get(cid, 0.0) or 0.0) * DEFAULT_DT_H
        for row, slot in zip(matrix, schedule)
        if start <= row["slot_datetime"] < end
    )


def test_heat_pump_store_is_planned_after_midnight(live):
    from house_config.heat_source import heat_source_efficiency

    profile = _profile(_consumer(_HP))
    plan = _store_plan(46.0, jaz=heat_source_efficiency(_HP))
    live(profile, plan=plan)
    matrix = _matrix()
    schedule = _solve(matrix, profile)
    tomorrow = _kwh(matrix, schedule, _CID, _MIDNIGHT, _END)
    today = _kwh(matrix, schedule, _CID, _START, _MIDNIGHT)
    # The store draws heat on both days; the cheap night after midnight carries the load.
    assert tomorrow > 1.0, schedule
    assert today < tomorrow


def test_heat_pump_store_level_spans_the_horizon(live, monkeypatch):
    from house_config.heat_source import heat_source_efficiency
    from optimizer import milp_model

    profile = _profile(_consumer(_HP))
    live(profile, plan=_store_plan(46.0, jaz=heat_source_efficiency(_HP)))
    captured = {}
    original = milp_model._add_flex_side_constraints

    def spy(model, *args, **kwargs):
        original(model, *args, **kwargs)
        captured["model"] = model

    monkeypatch.setattr(milp_model, "_add_flex_side_constraints", spy)
    matrix = _matrix()
    _solve(matrix, profile)
    store, levels = captured["model"].live_store_levels[_CID]
    assert sorted(levels.levels) == list(range(len(matrix)))
    assert levels.slack_kwh() == pytest.approx(0.0, abs=1e-6)
    assert store.terminal_min_kwh is not None


def test_live_build_relaxes_far_slots_before_the_pulse_limit(live, monkeypatch):
    """The relaxation must run before the thermal constraints: their pulse starts copy the
    on-variable type, and a binary start on a continuous on-variable forces a whole start."""
    import pulp

    from house_config.heat_source import heat_source_efficiency
    from optimizer import milp_model
    from optimizer.live_thermal_binaries import live_thermal_binary_slots

    profile = _profile(_consumer(_HP))
    live(profile, plan=_store_plan(46.0, jaz=heat_source_efficiency(_HP)))
    captured = {}
    original = milp_model._add_flex_side_constraints

    def spy(model, *args, **kwargs):
        original(model, *args, **kwargs)
        captured["model"] = model

    monkeypatch.setattr(milp_model, "_add_flex_side_constraints", spy)
    _solve(_matrix(), profile)
    model = captured["model"]
    window = live_thermal_binary_slots(float(model.dt_h))
    on_cats = [var.cat for var in model.consumer_on[_CID]]
    assert set(on_cats[:window]) == {pulp.LpInteger}
    assert set(on_cats[window:]) == {pulp.LpContinuous}
    starts = {
        int(var.name.rsplit("_", 1)[1]): var.cat
        for var in model.prob.variables()
        if var.name.startswith(f"{_CID}_") and "_start_" in var.name
    }
    assert starts, "no pulse starts built"
    assert {cat for slot, cat in starts.items() if slot < window} == {pulp.LpInteger}
    assert {cat for slot, cat in starts.items() if slot >= window} == {pulp.LpContinuous}


def test_heat_pump_without_store_delivers_every_days_target(live):
    profile = _profile(_consumer(_HP, storage=None))
    live(profile, house_slot_kwh=0.05)  # 0.2 kW house heat need, electric
    matrix = _matrix()
    schedule = _solve(matrix, profile)
    tomorrow_slots = sum(1 for row in matrix if row["slot_datetime"].date() == date(2024, 1, 16))
    tomorrow = _kwh(matrix, schedule, _CID, _MIDNIGHT, _MIDNIGHT + timedelta(days=1))
    assert tomorrow == pytest.approx(0.05 * tomorrow_slots, abs=0.41), schedule


def test_gas_house_rod_runs_in_the_cheap_slots_after_midnight(live):
    profile = _profile(_consumer(_GAS, rod=True))
    plan = _store_plan(40.0, jaz=0.95, wp_kw=15.0)
    live(profile, plan=plan)
    matrix = _matrix()
    schedule = _solve(matrix, profile)
    assert _kwh(matrix, schedule, _ROD_ID, _MIDNIGHT, _END) > 0.0, schedule
    # Cumulative cap: up to any slot the rod adds at most the room plus the draw until then.
    total = 0.0
    start_minute = _START.minute / 60.0
    for index, (_row, slot) in enumerate(zip(matrix, schedule)):
        total += float((slot.get("consumer_powers") or {}).get(_ROD_ID, 0.0) or 0.0) * DEFAULT_DT_H
        elapsed = (index + 1) * DEFAULT_DT_H + start_minute
        assert total <= plan.charge_room_heat_kwh_within(elapsed) + 1e-6


def test_live_heat_pump_target_label_names_the_live_plan(live):
    """The label tested ``consumption_mode == "live_snapshot"``; a Live cycle whose first row
    stays ``forecast`` showed "HDD-Tagesziel" for a store-planned heat pump."""
    from optimizer.targets import _live_thermal_annual_label

    consumer = {"id": _CID}
    live(_profile(_consumer(_HP)))
    assert _live_thermal_annual_label(consumer, _matrix()) == "thermal_annual (Wärmespeicher Live)"
    live(_profile(_consumer(_HP, storage=None)))
    assert _live_thermal_annual_label(consumer, _matrix()) == "thermal_annual (Hausplan Live)"


def test_live_heat_pump_label_without_house_entry_warns(live, caplog):
    """No silent fall back to "HDD-Tagesziel": the consumer is still planned in Live."""
    from optimizer.targets import _live_thermal_annual_label

    live(_profile(_consumer(_HP)))
    with caplog.at_level("WARNING", logger="optimizer.targets"):
        label = _live_thermal_annual_label({"id": "renamed_heating"}, _matrix())
    assert label == "thermal_annual (Live)"
    assert "renamed_heating" in caplog.text

def test_thermal_annual_label_outside_live_is_left_to_the_table():
    from optimizer.targets import _live_thermal_annual_label

    assert _live_thermal_annual_label({"id": _CID}, _matrix()) is None


@pytest.mark.parametrize(("is_live", "book", "expected"), [
    (True, None, [0, 1, 2, 3]),  # Live: the whole horizon
    (False, None, [0, 1]),  # book-less solve outside Live (diagnosis): the first day only
    (True, [1, 2], [1, 2]),  # SE book
])
def test_thermal_slots_span_the_horizon_only_in_live(monkeypatch, is_live, book, expected):
    from types import SimpleNamespace

    from optimizer.milp_model import _thermal_schedule_indices

    monkeypatch.setattr(
        "optimizer.live_cycle_scope.is_live_thermal_planning", lambda _matrix: is_live
    )
    inputs = SimpleNamespace(
        book_indices=book, schedule_indices=book if book is not None else [0, 1], horizon=4
    )
    assert _thermal_schedule_indices([{}] * 4, inputs) == expected

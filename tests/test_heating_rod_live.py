"""SUSI P1 follow-up — Live control of the heating rod: bindings, gate, caps, writes."""
from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import patch

import pytest

from house_config.heat_source import heat_source_efficiency
from house_config.heating_rod_bindings import (
    ROD_BINDINGS_KEY,
    missing_live_signals,
    normalize_rod_bindings,
    rewrite_rod_bindings_slug,
    rod_binding_entity,
    rod_field,
)
from house_config.planning_flex_bridge import collect_planning_flex_consumers
from settings.ehal_marker_resolve import (
    marker_flex_enable,
    marker_flex_power,
    marker_sens_consumer_active,
)

_CID = "wp_heating"
_ROD_ID = "wp_heating_heating_rod"
_ENABLE = f"heatpump.{_ROD_ID}.set_enable"
_POWER = f"heatpump.{_ROD_ID}.sens_power_act"
_ACTIVE = f"heatpump.{_ROD_ID}.sens_consumer_active"
_STORE_TEMP = f"heatpump.{_CID}.sens_temperature_heat_storage"
_STORAGE = {
    "volume_liters": 500.0,
    "heat_loss_kw_per_k": 0.002,
    "setpoint_c": 50.0,
    "tolerance_c": 5.0,
}
_ROD = {"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}


def _consumer(heat_source: dict, *, rod_bindings: dict | None = None, **extra) -> dict:
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
        "heat_storage": _STORAGE,
        "parts": [_ROD],
        "ehal_bindings": {_STORE_TEMP: "T_Speicher"},
        **extra,
    }
    if rod_bindings is not None:
        consumer[ROD_BINDINGS_KEY] = rod_bindings
    return consumer


def _profile(consumer: dict) -> dict:
    return {
        "id": "home",
        "latitude": 47.4,
        "longitude": 9.7,
        "annual_kwh": 9000.0,
        "consumers": [consumer],
    }


_BOUND = {_ENABLE: "Rod_En", _POWER: "Rod_P"}
_GAS = {"type": "gas"}
_HP = {"type": "heat_pump", "heat_pump_type": "luft"}


# --- bindings ---------------------------------------------------------------------------


def test_rod_keys_use_the_heatpump_namespace_and_composite_kennung():
    assert rod_field(_CID, "set_enable") == _ENABLE


def test_normalize_rejects_a_foreign_key():
    with pytest.raises(ValueError, match="unbekanntes Feld 'heatpump.wp_heating.set_enable'"):
        normalize_rod_bindings(
            {"heatpump.wp_heating.set_enable": "x"}, consumer_id=_CID, label="t"
        )


def test_rod_enable_never_becomes_the_parents_release():
    """Regression guard: why the map is not part of ``ehal_bindings``."""
    parent = _consumer(_HP, rod_bindings=_BOUND)
    assert marker_flex_enable(parent) == ""
    assert marker_flex_power(parent) == ""


def test_normalized_consumer_keeps_the_map_and_the_parents_bindings():
    from house_config.profiles_consumers import _copy_rod_bindings

    spec = {"id": _CID, "type": "thermal_annual"}
    _copy_rod_bindings({ROD_BINDINGS_KEY: _BOUND}, spec, profile_id="home")
    assert spec[ROD_BINDINGS_KEY] == _BOUND
    assert "ehal_bindings" not in spec


def test_map_on_another_consumer_type_fails_loud():
    from house_config.profiles_consumers import _copy_rod_bindings

    with pytest.raises(ValueError, match="gehört an den Haus-Wärme-Verbraucher"):
        _copy_rod_bindings(
            {ROD_BINDINGS_KEY: _BOUND}, {"id": "wm", "type": "generic"}, profile_id="home"
        )


def test_serialize_keeps_the_map():
    from house_config.profiles_consumers import _attach_ehal_entity_fields

    out: dict = {}
    _attach_ehal_entity_fields(out, _consumer(_HP, rod_bindings=_BOUND))
    assert out[ROD_BINDINGS_KEY] == _BOUND


def test_planning_entry_carries_only_the_rods_bindings():
    flex = collect_planning_flex_consumers(_profile(_consumer(_HP, rod_bindings=_BOUND)))
    parent, rod = flex
    assert _ENABLE not in (parent.get("ehal_bindings") or {})
    assert rod["ehal_bindings"] == _BOUND
    assert marker_flex_enable(rod) == "Rod_En"
    assert marker_flex_power(rod) == "Rod_P"


def test_empty_address_is_an_activation_flag_with_the_qualified_id():
    rod = rod_binding_entity(_consumer(_GAS, rod_bindings={_ENABLE: ""}))
    assert marker_flex_enable(rod) == _ENABLE


def test_rename_of_the_parent_rewrites_the_rod_kennung():
    assert rewrite_rod_bindings_slug({_ENABLE: "Rod_En"}, new_consumer_id="heizung") == {
        "heatpump.heizung_heating_rod.set_enable": "Rod_En"
    }


def test_push_sources_list_the_rod_signals():
    from ehal.push_signals import _binding_entries

    house = {"profiles": {"home": _profile(_consumer(_GAS, rod_bindings=_BOUND))}}
    entries = _binding_entries(house, {})
    assert ("consumer", _ROD_ID, "heating_rod", _POWER, "Rod_P") in entries
    assert all(entry[1] != _CID or "_heating_rod." not in entry[3] for entry in entries)


def _raw_house(**consumer_fields) -> tuple[dict, dict]:
    consumer = {"id": _CID, "type": "thermal_annual", "heating_system_id": "sys", **consumer_fields}
    components = {
        "heating_systems": [
            {
                "id": "sys",
                "heat_source": _GAS,
                "heating_power_kw": 10.0,
                "heat_storage": _STORAGE,
                "parts": [_ROD],
            }
        ]
    }
    return {"profiles": {"home": {"id": "home", "consumers": [consumer]}}}, components


def test_signal_catalog_offers_the_rod_as_optional_and_activation_writes_its_map():
    from ehal.signal_catalog import iter_catalog_entries, set_binding_activation

    house, components = _raw_house()
    rows = [e for e in iter_catalog_entries(house, components) if e.entity_id == _ROD_ID]
    assert {row.binding_key for row in rows} == {_ENABLE, _POWER, _ACTIVE}
    assert not any(row.is_required for row in rows)

    out, _ = set_binding_activation(
        house,
        components,
        component_kind="consumer",
        entity_id=_ROD_ID,
        binding_key=_ENABLE,
        activated=True,
        consumer_type="heating_rod",
    )
    consumer = out["profiles"]["home"]["consumers"][0]
    assert consumer[ROD_BINDINGS_KEY] == {_ENABLE: ""}
    assert "ehal_bindings" not in consumer


def test_mapping_page_lists_the_rod_and_saves_into_its_map():
    from ui.ehal_loxone_mapping import build_entity_rows
    from ui.ehal_loxone_mapping_persist import apply_entity_bindings

    house, components = _raw_house()
    rows = build_entity_rows(house, "home", components_doc=components)
    row = next(item for item in rows if item["id"] == _ROD_ID)
    assert _ENABLE in row["fields"]

    out = apply_entity_bindings(
        house, profile_id="home", entity_id=_ROD_ID, bindings={_ENABLE: "Rod_En"}
    )
    consumer = out["profiles"]["home"]["consumers"][0]
    assert consumer[ROD_BINDINGS_KEY] == {_ENABLE: "Rod_En"}
    assert "ehal_bindings" not in consumer


# --- gate -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rod_bindings, store_bound, missing",
    [
        ({_ENABLE: "E", _POWER: "P"}, True, []),
        ({_ENABLE: "E", _ACTIVE: "A"}, True, []),
        ({_POWER: "P"}, True, ["set_enable"]),
        ({_ENABLE: "E"}, True, ["sens_power_act oder sens_consumer_active"]),
        ({_ENABLE: "E", _POWER: "P"}, False, ["sens_temperature_heat_storage"]),
    ],
)
def test_missing_live_signals(rod_bindings, store_bound, missing):
    rod = {"id": _ROD_ID, "ehal_bindings": rod_bindings}
    parent = _consumer(_GAS)
    if not store_bound:
        parent["ehal_bindings"] = {}
    assert missing_live_signals(rod, parent) == missing


# --- Live planning ----------------------------------------------------------------------


def _matrix(prices: list[float], day: date = date(2024, 1, 15), start: int = 0) -> list[dict]:
    return [
        {
            "hour": (start + index) % 24,
            "date": day,
            "slot_datetime": datetime.combine(day, time((start + index) % 24, 0)),
            "k_act": price,
            "price_buy": price / 100.0,
            "expected_p_act": 0.5,
            "expected_p_pv": 0.0,
            "consumption_mode": "forecast",  # Live; "profile_spec" would read the SE book
        }
        for index, price in enumerate(prices)
    ]


def _store_plan(start_c: float, *, horizon: int = 24, jaz: float = 1.0, wp_kw: float = 1.6):
    from optimizer.thermal_coupled import capacity_kwh_per_k_from_volume
    from optimizer.thermal_live_store import ThermalBand, plan_live_store_horizon

    return plan_live_store_horizon(
        start_temp_c=start_c,
        ambient_forecast_c=[5.0] * horizon,
        band=ThermalBand(50.0, 5.0),
        capacity_kwh_per_k=capacity_kwh_per_k_from_volume(500.0),
        heat_loss_kw_per_k=0.0,
        wp_electric_kw=wp_kw,
        jaz=jaz,
        persons=0,
    )


@pytest.fixture
def live(monkeypatch):
    """Live semantics over a plain matrix; the store plan comes from ``use_plan``."""
    monkeypatch.setattr("optimizer.live_cycle_scope.is_live_thermal_planning", lambda _m: True)
    monkeypatch.setattr(
        "optimizer.absent_mode.resolve_absent_status", lambda _profile: {"effective": False}
    )

    def use_plan(plan, profile):
        monkeypatch.setattr(
            "optimizer.thermal_live_store.live_store_plan_for_matrix",
            lambda _source, _profile, _matrix: plan,
        )
        monkeypatch.setattr(
            "config.get_resolved_runtime_settings", lambda: {"_house_profile": profile}
        )

    return use_plan


def _solve(matrix: list[dict], profile: dict):
    from optimizer.cbc_solver import solve_with_strict_fallback
    from optimizer.milp import _add_milp_objective
    from optimizer.milp_consumers import (
        _add_consumer_delivery_constraints,
        filter_feasible_consumers,
    )
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.targets import resolve_horizon_consumer_targets_kwh
    from optimizer.thermal_flex_context import (
        add_thermal_flex_constraints,
        resolve_thermal_flex_contexts,
    )

    flex = collect_planning_flex_consumers(profile)
    horizon = len(matrix)
    remaining = resolve_horizon_consumer_targets_kwh(matrix, None, flexible_consumers=flex)
    contexts = resolve_thermal_flex_contexts(matrix, flex, profile)
    battery = {
        "min_soc": 10.0,
        "max_soc": 10.0001,
        "max_power_kw": 0.001,
        "battery_capacity_kwh": 0.01,
        "efficiency": 0.95,
    }
    indices = list(range(horizon))
    planned = filter_feasible_consumers(flex, remaining, matrix, indices, False, {}, {})
    model = _build_milp_model(matrix, horizon, battery, 10.0, planned, 0.0, remaining, {})
    _add_milp_objective(model, matrix, 0.0, {}, wear_cent_per_kwh=0.0)
    _add_consumer_delivery_constraints(model, matrix, remaining, indices, {}, False)
    add_thermal_flex_constraints(model, matrix, indices, contexts)
    assert solve_with_strict_fallback(model.prob, msg=False) == "Optimal"
    return model, remaining, contexts


def _on_slots(model, cid: str) -> list[int]:
    return [
        slot
        for slot, var in enumerate(model.consumer_on.get(cid, []))
        if var.varValue is not None and var.varValue > 0.5
    ]


def _rod_kwh(model) -> float:
    return len(_on_slots(model, _ROD_ID)) * 3.0 * float(model.dt_h)


_CHEAP_NOON = [40.0] * 10 + [2.0] * 4 + [40.0] * 10


def test_gas_house_rod_is_capped_by_the_free_store_heat(live):
    profile = _profile(_consumer(_GAS, rod_bindings=_BOUND))
    plan = _store_plan(47.0, jaz=0.95)  # 3 K below the setpoint: room for two slots
    live(plan, profile)
    model, remaining, contexts = _solve(_matrix(_CHEAP_NOON), profile)
    cap = plan.opp_cap_electric_kwh * 0.95
    assert cap > 0.0
    assert remaining[_ROD_ID] == pytest.approx(cap, abs=1e-3)
    assert contexts[_ROD_ID]["daily_heat_cap_kwh"] == {date(2024, 1, 15): pytest.approx(cap, abs=1e-3)}
    assert 0.0 < _rod_kwh(model) <= cap + 1e-6
    assert all(10 <= slot < 14 for slot in _on_slots(model, _ROD_ID))


def test_free_heat_below_one_slot_leaves_the_binary_rod_off(live):
    profile = _profile(_consumer(_GAS, rod_bindings=_BOUND))
    live(_store_plan(49.0, jaz=0.95), profile)  # about 0.6 kWh free, one slot delivers 0.75
    model, remaining, _contexts = _solve(_matrix(_CHEAP_NOON), profile)
    assert 0.0 < remaining[_ROD_ID] < 0.75
    assert _on_slots(model, _ROD_ID) == []


def test_full_store_leaves_the_rod_off(live):
    profile = _profile(_consumer(_GAS, rod_bindings=_BOUND))
    live(_store_plan(50.0, jaz=0.95), profile)
    model, remaining, _contexts = _solve(_matrix(_CHEAP_NOON), profile)
    assert remaining[_ROD_ID] == 0.0
    assert _on_slots(model, _ROD_ID) == []


def test_missing_signal_keeps_the_rod_out_of_the_live_plan(live):
    profile = _profile(_consumer(_GAS, rod_bindings={_ENABLE: "Rod_En"}))
    live(_store_plan(30.0, jaz=0.95), profile)
    model, remaining, contexts = _solve(_matrix(_CHEAP_NOON), profile)
    assert remaining[_ROD_ID] == 0.0
    assert contexts[_ROD_ID] == {}
    assert _on_slots(model, _ROD_ID) == []


def test_gas_house_rod_stays_off_after_the_first_day(live):
    profile = _profile(_consumer(_GAS, rod_bindings=_BOUND))
    live(_store_plan(30.0, jaz=0.95), profile)
    today = _matrix([40.0] * 24)
    tomorrow = _matrix([2.0] * 24, day=date(2024, 1, 16))
    model, _remaining, _contexts = _solve(today + tomorrow, profile)
    assert _on_slots(model, _ROD_ID) == []


def test_heat_pump_house_rod_runs_only_within_the_store_overlay(live):
    from optimizer.thermal_live_store import live_min_kwh_by_day

    profile = _profile(_consumer(_HP, rod_bindings=_BOUND))
    jaz = heat_source_efficiency(_HP)
    plan = _store_plan(45.0, jaz=jaz)
    live(plan, profile)
    matrix = _matrix([-5.0] * 4 + [30.0] * 20)
    model, remaining, contexts = _solve(matrix, profile)
    assert contexts[_ROD_ID] == {"live_pulse_limit": True}
    assert remaining[_ROD_ID] == pytest.approx(plan.opp_cap_electric_kwh * jaz, abs=1e-2)
    assert contexts[_CID]["live_day_min_kwh"] == live_min_kwh_by_day(matrix, plan)
    assert 0.0 < _rod_kwh(model) <= remaining[_ROD_ID] + 1e-6
    assert all(slot < 4 for slot in _on_slots(model, _ROD_ID))


def test_live_rod_has_a_pulse_limit(live):
    profile = _profile(_consumer(_GAS, rod_bindings=_BOUND))
    live(_store_plan(10.0, jaz=0.95), profile)
    prices = []
    for _ in range(8):
        prices += [2.0, 40.0]
    model, _remaining, _contexts = _solve(_matrix(prices), profile)
    slots = _on_slots(model, _ROD_ID)
    starts = [slot for slot in slots if slot - 1 not in slots]
    assert 0 < len(starts) <= 4


# --- write and read path ----------------------------------------------------------------


def test_rod_enable_follows_the_plan_and_publishes_on_its_own_id():
    from integrations.loxone_comm_trace import LoxoneWriteRecord
    from integrations.loxone_writes import _write_flexible_consumer_output

    rod = next(
        c
        for c in collect_planning_flex_consumers(
            _profile(_consumer(_GAS, rod_bindings={_ENABLE: "", _POWER: ""}))
        )
        if c["id"] == _ROD_ID
    )
    published: list[tuple[str, float]] = []

    def _pub(qid, value, *, io_name=""):
        published.append((qid, float(value)))
        return LoxoneWriteRecord(
            io_name=io_name or qid, value=float(value), success=True, written_at="t"
        )

    with patch("integrations.loxone_writes._publish_setpoint_traced", side_effect=_pub):
        for power in (3.0, 0.0):
            _write_flexible_consumer_output(
                rod, {_ROD_ID: power}, {}, None, None, send=True,
                publish_kinds=frozenset({"set_enable"}),
            )
    assert published == [(_ENABLE, 1.0), (_ENABLE, 0.0)]


def _rod_entry(bindings: dict) -> dict:
    return next(
        c
        for c in collect_planning_flex_consumers(_profile(_consumer(_GAS, rod_bindings=bindings)))
        if c["id"] == _ROD_ID
    )


def test_live_power_reads_the_rods_meter_as_power():
    from integrations.loxone_live_power import _read_consumer_meter_kw

    rod = _rod_entry({_ENABLE: "E", _POWER: "Rod_P"})
    with patch("integrations.loxone_live_power.fetch_loxone_generic_value", return_value=1.5):
        assert _read_consumer_meter_kw(rod) == pytest.approx(1.5)


def test_live_power_without_meter_is_run_state_times_nominal():
    from integrations.loxone_live_power import _read_consumer_meter_kw

    rod = _rod_entry({_ENABLE: "E", _ACTIVE: "Rod_A"})
    assert marker_sens_consumer_active(rod) == "Rod_A"
    with patch("integrations.loxone_live_power.fetch_loxone_generic_value", return_value=1.0):
        assert _read_consumer_meter_kw(rod) == pytest.approx(3.0)
    with patch("integrations.loxone_live_power.fetch_loxone_generic_value", return_value=0.0):
        assert _read_consumer_meter_kw(rod) == pytest.approx(0.0)


def test_baseload_subtracts_the_measured_rod():
    from data.live_consumption import build_consumption_snapshot

    snapshot = build_consumption_snapshot(
        {"house": 3.5, "pv": 0.0, "grid": 3.5, "battery": 0.0}, {_ROD_ID: 3.0}
    )
    assert snapshot["baseload_kw"] == pytest.approx(0.5)

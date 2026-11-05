"""SUSI P1 — heat sources, fuel path, heating rod part and SE fuel / CO2 rows."""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd
import pytest

from house_config.house_thermal import default_house_thermal
from house_config.heat_source import (
    consumer_heat_source,
    fuel_price_eur_per_kwh,
    heat_source_efficiency,
    heat_source_is_electric,
    heating_rod_fuel_credit_cent_per_kwh,
    normalize_heat_source,
    normalize_parts,
)

_STORAGE = {
    "volume_liters": 800.0,
    "heat_loss_kw_per_k": 0.01,
    "setpoint_c": 45.0,
    "tolerance_c": 5.0,
}
_ROD = {"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}
# Normalized: the loader writes the internal-gain factor explicitly (SUSI P2, always 0).
_ROD_NORMALIZED = {**_ROD, "internal_gain_factor": 0.0}


# --- heat_source normalization and defaults ---------------------------------------------


def test_heat_pump_defaults_keep_previous_jaz():
    assert heat_source_efficiency({"type": "heat_pump", "heat_pump_type": "luft"}) == 3.5
    assert heat_source_efficiency({"type": "heat_pump", "heat_pump_type": "erde"}) == 4.3
    assert heat_source_efficiency({"type": "heat_pump", "heat_pump_type": "grundwasser"}) == 4.2


def test_fuel_defaults_and_units():
    gas = normalize_heat_source({"type": "gas"}, label="t")
    assert gas == {"type": "gas"}  # defaults are resolved by getters, never stored
    assert not heat_source_is_electric(gas)
    assert heat_source_efficiency(gas) == 0.95
    assert fuel_price_eur_per_kwh(gas) == pytest.approx(0.1043)
    assert fuel_price_eur_per_kwh({"type": "oil"}) == pytest.approx(1.048 / 10.0)
    assert fuel_price_eur_per_kwh({"type": "pellets"}) == pytest.approx(322.0 / 4900.0)
    assert fuel_price_eur_per_kwh({"type": "oil", "fuel_price": 120.0}) == pytest.approx(0.12)
    assert heating_rod_fuel_credit_cent_per_kwh(gas) == pytest.approx(10.43 / 0.95)
    assert heat_source_is_electric({"type": "electric_direct"})
    assert heat_source_efficiency({"type": "electric_direct"}) == 0.99


@pytest.mark.parametrize(
    "raw, match",
    [
        (None, "heat_source fehlt"),
        ({"type": "coal"}, "unbekannt"),
        ({"type": "heat_pump"}, "heat_pump_type"),
        ({"type": "heat_pump", "heat_pump_type": "luft", "fuel_price": 1.0}, "fuel_price"),
        ({"type": "gas", "heat_pump_type": "luft"}, "heat_pump_type"),
        ({"type": "gas", "efficiency": 0}, "efficiency"),
    ],
)
def test_heat_source_fails_loud(raw, match):
    with pytest.raises(ValueError, match=match):
        normalize_heat_source(raw, label="t")


def test_heating_rod_requires_heat_storage():
    with pytest.raises(ValueError, match="nur mit Wärmespeicher"):
        normalize_parts([_ROD], label="t", has_heat_storage=False)
    assert normalize_parts([_ROD], label="t", has_heat_storage=True) == [_ROD_NORMALIZED]
    with pytest.raises(ValueError, match="unbekannt"):
        normalize_parts([{**_ROD, "type": "filter"}], label="t", has_heat_storage=True)


def _catalog(**fields) -> dict:
    from house_config.heating_systems import heating_systems_by_id
    from tests.fixtures.heating_catalog import legacy_entry

    return heating_systems_by_id({"heating_systems": [legacy_entry({"id": "hs", **fields})]})


def test_legacy_heat_pump_type_is_rejected_on_load():
    from house_config.profiles_thermal_annual import normalize_thermal_annual_consumer

    with pytest.raises(ValueError, match="heat_pump_type wird nicht mehr unterstützt"):
        normalize_thermal_annual_consumer(
            {"id": "wp", "heat_pump_type": "luft", "heating_system_id": "hs"},
            {},
            copy_loxone_binding=lambda *_: None,
            house_thermal=default_house_thermal(),
            persons=2,
            heating_systems=_catalog(heat_source={"type": "gas"}),
        )


def test_profile_takes_parts_and_storage_from_the_catalog_entry():
    from house_config.profiles_thermal_annual import normalize_thermal_annual_consumer

    spec: dict = {}
    normalize_thermal_annual_consumer(
        {"id": "wp", "heating_system_id": "hs"},
        spec,
        copy_loxone_binding=lambda *_: None,
        house_thermal=default_house_thermal(),
        persons=2,
        heating_systems=_catalog(
            heat_source={"type": "gas"}, heat_storage=_STORAGE, parts=[_ROD]
        ),
    )
    assert spec["heating_system_id"] == "hs"
    assert spec["thermal"]["heat_source"] == {"type": "gas"}
    assert spec["thermal"]["heat_storage"]["volume_liters"] == _STORAGE["volume_liters"]
    assert spec["parts"] == [_ROD_NORMALIZED]
    assert "parts" not in spec["thermal"]


def test_inline_heat_generation_on_the_consumer_needs_migration():
    from house_config.profiles_thermal_annual import normalize_thermal_annual_consumer

    for raw in (
        {"id": "wp", "heat_source": {"type": "gas"}},
        {"id": "wp", "heating_system_id": "hs", "heat_source": {"type": "gas"}},
        {"id": "wp", "heating_system_id": "hs", "heat_storage": _STORAGE},
    ):
        with pytest.raises(ValueError, match="Heizsystem-Katalog"):
            normalize_thermal_annual_consumer(
                raw,
                {},
                copy_loxone_binding=lambda *_: None,
                house_thermal=default_house_thermal(),
                persons=2,
                heating_systems=_catalog(heat_source={"type": "gas"}),
            )


def test_unknown_heating_system_id_fails_loud():
    from house_config.profiles_thermal_annual import normalize_thermal_annual_consumer

    with pytest.raises(ValueError, match="'nope' fehlt in components.json"):
        normalize_thermal_annual_consumer(
            {"id": "wp", "heating_system_id": "nope"},
            {},
            copy_loxone_binding=lambda *_: None,
            house_thermal=default_house_thermal(),
            persons=2,
            heating_systems=_catalog(heat_source={"type": "gas"}),
        )


def test_profile_save_keeps_flex_fields_and_writes_only_the_reference():
    """Regression (rod lost on save) moved: the rod lives in the catalog entry now."""
    from house_config.profiles_store import _normalize_consumer, _serialize_consumer

    catalog = _catalog(
        heat_source={"type": "heat_pump", "heat_pump_type": "erde"},
        nominal_power_kw=1.9,
        heat_storage=_STORAGE,
        parts=[_ROD],
    )
    raw = {
        "id": "wp",
        "label": "Wärmepumpe",
        "type": "thermal_annual",
        "heating_system_id": "hs",
        "optimizer_flex": True,
        "max_on_quarterhours": 12,
        "max_pulses_per_day": 3,
        "thermal_flex_window": {"start_hour": 10, "end_hour": 16},
    }
    spec = _normalize_consumer(
        raw, 0, "home", heating_systems=catalog, house_thermal=default_house_thermal(), persons=2
    )
    assert spec["parts"] == [_ROD_NORMALIZED]
    assert spec["nominal_power_kw"] == 1.9
    out = _serialize_consumer(spec)
    assert out["heating_system_id"] == "hs"
    for key in (
        "parts",
        "heat_source",
        "heat_storage",
        "heating_power_kw",
        "nominal_power_kw",
        "min_on_quarterhours",
    ):
        assert key not in out
    assert out["optimizer_flex"] is True
    assert out["max_on_quarterhours"] == 12
    assert out["max_pulses_per_day"] == 3
    assert out["thermal_flex_window"] == {"start_hour": 10, "end_hour": 16}
    again = _normalize_consumer(
        out, 0, "home", heating_systems=catalog, house_thermal=default_house_thermal(), persons=2
    )
    assert again["parts"] == spec["parts"]
    assert again["thermal"] == spec["thermal"]


def test_catalog_entry_rejects_rod_without_storage():
    with pytest.raises(ValueError, match="Heizstab nur mit Wärmespeicher"):
        _catalog(heat_source={"type": "gas"}, parts=[_ROD])


# --- year simulation: fuel path ----------------------------------------------------------


def _year_kwargs(**overrides) -> dict:
    kwargs = {
        "living_area_m2": 120.0,
        "building_class": 3,
        "persons": 2,
        "latitude": 47.4,
        "longitude": 9.7,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        "hp_electric_kw": 3.0,
        "daily_temps": [(-2.0 + 0.05 * day) for day in range(365)],
        "daily_radiation_mj": [5.0] * 365,
        "house_heat_loss_kw_per_k": 0.12,
    }
    kwargs.update(overrides)
    return kwargs


def test_fuel_source_books_fuel_not_power():
    from data.heating_need import daily_electric_kwh, daily_fuel_kwh

    gas = _year_kwargs(heat_efficiency=0.95, heat_electric=False, hp_electric_kw=10.0)
    assert sum(daily_electric_kwh(**gas)) == 0.0
    fuel = sum(daily_fuel_kwh(**gas))
    assert fuel > 0.0
    # Same house with an electric heater of the same input power: same input energy.
    direct = _year_kwargs(heat_efficiency=0.95, heat_electric=True, hp_electric_kw=10.0)
    assert sum(daily_electric_kwh(**direct)) == pytest.approx(fuel)
    assert sum(daily_fuel_kwh(**direct)) == 0.0


def test_fuel_equals_heat_over_efficiency():
    """Gas house: fuel = delivered heat / 0.95 (heat from an ideal η = 1 source)."""
    from data.heating_need import daily_electric_kwh, daily_fuel_kwh

    ideal = sum(daily_electric_kwh(**_year_kwargs(heat_efficiency=1.0, hp_electric_kw=20.0)))
    gas = sum(
        daily_fuel_kwh(
            **_year_kwargs(heat_efficiency=0.95, heat_electric=False, hp_electric_kw=20.0 / 0.95)
        )
    )
    assert gas == pytest.approx(ideal / 0.95, rel=1e-3)


# --- MILP: heating rod part ----------------------------------------------------------------


def _thermal_consumer(heat_source: dict, *, nominal: float = 1.6) -> dict:
    return {
        "id": "wp_heating",
        "label": "Heizung",
        "type": "thermal_annual",
        "nominal_power_kw": nominal,
        "living_area_m2": 157.0,
        "building_class": 2,
        "heat_source": heat_source,
        "persons": 2,
        "target_temp_c": 21.5,
        "heating_limit_c": 15.0,
        "heat_storage": _STORAGE,
        "parts": [_ROD],
    }


def _profile(consumer: dict) -> dict:
    return {
        "id": "home",
        "latitude": 47.4,
        "longitude": 9.7,
        "annual_kwh": 9000.0,
        "consumers": [consumer],
    }


def test_collect_flex_gas_house_has_only_the_rod():
    from house_config.planning_flex_bridge import collect_planning_flex_consumers

    flex = collect_planning_flex_consumers(_profile(_thermal_consumer({"type": "gas"})))
    assert [entry["id"] for entry in flex] == ["wp_heating_heating_rod"]
    rod = flex[0]
    assert rod["parent_id"] == "wp_heating"
    assert rod["parent_heat_electric"] is False
    assert rod["fuel_credit_cent_per_kwh"] == pytest.approx(10.43 / 0.95)


def test_collect_flex_heat_pump_with_rod():
    from house_config.planning_flex_bridge import collect_planning_flex_consumers

    consumer = _thermal_consumer({"type": "heat_pump", "heat_pump_type": "erde"})
    flex = collect_planning_flex_consumers(_profile(consumer))
    assert [entry["id"] for entry in flex] == ["wp_heating", "wp_heating_heating_rod"]
    rod = flex[1]
    assert rod["parent_heat_electric"] is True
    assert rod["parent_heat_efficiency"] == 4.3
    assert "fuel_credit_cent_per_kwh" not in rod


def test_rod_beside_heat_pump_without_milp_fails_loud():
    from house_config.planning_flex_bridge import collect_planning_flex_consumers

    consumer = _thermal_consumer({"type": "heat_pump", "heat_pump_type": "luft"})
    consumer["optimizer_flex"] = False
    with pytest.raises(ValueError, match="MILP-Planung"):
        collect_planning_flex_consumers(_profile(consumer))


def _matrix(prices: list[float], day: date = date(2024, 1, 15)) -> list[dict]:
    return [
        {
            "hour": hour,
            "date": day,
            "slot_datetime": datetime.combine(day, time(hour, 0)),
            "k_act": price,
            "price_buy": price / 100.0,
            "expected_p_act": 0.5,
            "expected_p_pv": 0.0,
            "consumption_mode": "profile_spec",
        }
        for hour, price in enumerate(prices)
    ]


def _solve(matrix: list[dict], flex: list[dict], profile: dict, remaining: dict) -> object:
    from optimizer.cbc_solver import solve_with_strict_fallback
    from optimizer.milp import _add_milp_objective
    from optimizer.milp_consumers import (
        _add_consumer_delivery_constraints,
        filter_feasible_consumers,
    )
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.thermal_flex_context import (
        add_thermal_flex_constraints,
        resolve_thermal_flex_contexts,
    )

    horizon = len(matrix)
    contexts = resolve_thermal_flex_contexts(matrix, flex, profile)
    battery = {
        "min_soc": 10.0,
        "max_soc": 10.0001,
        "max_power_kw": 0.001,
        "battery_capacity_kwh": 0.01,
        "efficiency": 0.95,
    }
    planned = filter_feasible_consumers(
        flex, remaining, matrix, list(range(horizon)), False, {}, {}
    )
    model = _build_milp_model(matrix, horizon, battery, 10.0, planned, 0.0, remaining, {})
    _add_milp_objective(model, matrix, 0.0, {}, wear_cent_per_kwh=0.0)
    _add_consumer_delivery_constraints(model, matrix, remaining, list(range(horizon)), {}, False)
    add_thermal_flex_constraints(model, matrix, list(range(horizon)), contexts)
    assert solve_with_strict_fallback(model.prob, msg=False) == "Optimal"
    return model, contexts


def _on_hours(model, cid: str) -> list[int]:
    return [
        hour
        for hour, var in enumerate(model.consumer_on[cid])
        if var.varValue is not None and var.varValue > 0.5
    ]


def test_rod_runs_at_negative_price_instead_of_heat_pump():
    from house_config.planning_flex_bridge import collect_planning_flex_consumers

    consumer = _thermal_consumer({"type": "heat_pump", "heat_pump_type": "luft"})
    profile = _profile(consumer)
    flex = collect_planning_flex_consumers(profile)
    prices = [-5.0] * 4 + [30.0] * 20
    matrix = _matrix(prices)
    from optimizer.thermal_flex_context import resolve_thermal_flex_contexts

    target = next(
        iter(resolve_thermal_flex_contexts(matrix, flex, profile)["wp_heating"]["daily_targets"].values())
    )
    remaining = {"wp_heating": target, "wp_heating_heating_rod": 100.0}
    model, _ctx = _solve(matrix, flex, profile, remaining)
    rod_hours = _on_hours(model, "wp_heating_heating_rod")
    assert rod_hours and all(hour < 4 for hour in rod_hours)


def test_rod_stays_off_when_heat_pump_heat_is_cheaper():
    from house_config.planning_flex_bridge import collect_planning_flex_consumers
    from optimizer.thermal_flex_context import resolve_thermal_flex_contexts

    consumer = _thermal_consumer({"type": "heat_pump", "heat_pump_type": "luft"})
    profile = _profile(consumer)
    flex = collect_planning_flex_consumers(profile)
    matrix = _matrix([20.0] * 24)
    target = next(
        iter(resolve_thermal_flex_contexts(matrix, flex, profile)["wp_heating"]["daily_targets"].values())
    )
    model, _ctx = _solve(
        matrix, flex, profile, {"wp_heating": target, "wp_heating_heating_rod": 100.0}
    )
    assert _on_hours(model, "wp_heating_heating_rod") == []
    assert _on_hours(model, "wp_heating")


def test_rod_beside_gas_runs_when_power_is_cheaper_than_gas_heat():
    from house_config.planning_flex_bridge import collect_planning_flex_consumers

    consumer = _thermal_consumer({"type": "gas"})
    profile = _profile(consumer)
    flex = collect_planning_flex_consumers(profile)
    prices = [40.0] * 10 + [2.0] * 4 + [40.0] * 10  # cheap noon < 10.98 ct gas heat
    matrix = _matrix(prices)
    model, contexts = _solve(matrix, flex, profile, {"wp_heating_heating_rod": 100.0})
    rod_hours = _on_hours(model, "wp_heating_heating_rod")
    assert rod_hours and all(10 <= hour < 14 for hour in rod_hours)
    cap = sum(contexts["wp_heating_heating_rod"]["daily_heat_cap_kwh"].values())
    rod_kwh = len(rod_hours) * 3.0 * float(model.dt_h)
    assert rod_kwh <= cap + 1e-6


@pytest.mark.parametrize("mode", ["profile_spec", "logged_day"])
def test_se_book_without_rod_entry_still_plans_the_rod(monkeypatch, mode):
    """SE path: the book holds no rod target, the rod still gets its heat bound and runs."""
    from house_config.planning_flex_bridge import collect_planning_flex_consumers
    from optimizer.milp_inputs import _resolve_thermal_flex_contexts
    from optimizer.targets import resolve_horizon_consumer_targets_kwh

    consumer = _thermal_consumer({"type": "gas"})
    profile = _profile(consumer)
    monkeypatch.setattr(
        "config.get_resolved_runtime_settings", lambda: {"_house_profile": profile}
    )
    monkeypatch.setattr(
        "optimizer.thermal_flex_context.thermal_daily_heat_kwh_for_date",
        lambda *_args, **_kwargs: 30.0,
    )
    flex = collect_planning_flex_consumers(profile)
    matrix = _matrix([40.0] * 10 + [2.0] * 4 + [40.0] * 10)
    for row in matrix:
        row["consumption_mode"] = mode
    book = {"wp_heating_heating_rod": 0.0}  # what resolve_profile_spec_flex_targets books
    targets = resolve_horizon_consumer_targets_kwh(matrix, book, flexible_consumers=flex)
    assert targets["wp_heating_heating_rod"] == pytest.approx(30.0)
    # The MILP entry builds the rod caps although a gas house has no thermal flex consumer.
    contexts = _resolve_thermal_flex_contexts(matrix, flex, None)
    assert contexts["wp_heating_heating_rod"]["daily_heat_cap_kwh"]
    model, _contexts = _solve(matrix, flex, profile, targets)
    rod_hours = _on_hours(model, "wp_heating_heating_rod")
    assert rod_hours and all(10 <= hour < 14 for hour in rod_hours)


def test_plausibility_counts_rod_as_parent_energy():
    from simulation.plausibility import plausibility_flex_kwh

    gas_rod = {"id": "a_heating_rod", "daily_target_source": "heating_rod",
               "parent_heat_electric": False, "parent_heat_efficiency": 0.95}
    hp_rod = {"id": "b_heating_rod", "daily_target_source": "heating_rod",
              "parent_heat_electric": True, "parent_heat_efficiency": 4.0}
    hp = {"id": "b", "daily_target_source": "thermal_annual"}
    delivered = {"a_heating_rod": 6.0, "b_heating_rod": 8.0, "b": 3.0}
    out = plausibility_flex_kwh(delivered, [gas_rod, hp_rod, hp])
    assert out == {"a_heating_rod": 0.0, "b_heating_rod": pytest.approx(2.0), "b": 3.0}


def test_rod_without_signals_is_not_planned_in_live(monkeypatch):
    from optimizer.targets import resolve_heating_rod_horizon_kwh

    profile = _profile(_thermal_consumer({"type": "gas"}))
    monkeypatch.setattr(
        "config.get_resolved_runtime_settings", lambda: {"_house_profile": profile}
    )
    monkeypatch.setattr(
        "optimizer.live_cycle_scope.is_live_thermal_planning", lambda _matrix: True
    )
    rod = {"id": "wp_heating_heating_rod", "parent_id": "wp_heating"}
    assert resolve_heating_rod_horizon_kwh(rod, _matrix([10.0] * 4)) == 0.0


# --- SE: fuel and CO2 per result ----------------------------------------------------------


def test_heat_fuel_for_result_subtracts_rod_heat(monkeypatch):
    from simulation.heat_fuel import heat_fuel_for_result

    monkeypatch.setattr(
        "optimizer.thermal_flex_context.thermal_daily_fuel_kwh_for_date",
        lambda *_args, **_kwargs: 40.0,
    )
    monkeypatch.setattr(
        "data.modeled_climate.ModeledClimateContext.from_scenario",
        classmethod(lambda cls, _params: None),
    )
    index = pd.date_range("2024-01-15", periods=96, freq="15min")
    df = pd.DataFrame(
        {
            "import_kwh": [0.5] * 96,
            "wp_heating_heating_rod_kw": [4.0] * 4 + [0.0] * 92,  # 4 kWh rod heat
        },
        index=index,
    )
    consumer = {**_thermal_consumer({"type": "gas"}), "heating_system_id": "gas_rod"}
    block = heat_fuel_for_result(df, {"_house_profile": _profile(consumer)})
    expected_fuel = 40.0 - 4.0 / 0.95
    assert block["fuel_kwh"] == pytest.approx(expected_fuel, abs=0.05)
    assert block["fuel_eur"] == pytest.approx(expected_fuel * 0.1043, abs=0.01)
    assert block["import_kwh"] == pytest.approx(48.0)
    assert block["co2_kg"] == pytest.approx((48.0 * 226 + expected_fuel * 249) / 1000, abs=0.1)
    assert block["carriers"] == ["gas"]
    assert block["heating_systems"] == {"wp_heating": "gas_rod"}
    assert block["rod_kwh"] == pytest.approx(4.0)


def test_heat_fuel_without_profile_has_only_electricity():
    from simulation.heat_fuel import heat_fuel_for_result

    df = pd.DataFrame(
        {"import_kwh": [1.0] * 4}, index=pd.date_range("2024-01-15", periods=4, freq="15min")
    )
    block = heat_fuel_for_result(df, None)
    assert block["fuel_kwh"] == 0.0
    assert block["co2_kg"] == pytest.approx(4 * 226 / 1000, abs=0.1)


def test_annual_cost_rows_add_fuel_to_jahres_kosten():
    from ui.backtesting_results_helpers import build_annual_cost_rows

    meta = {
        "summary": {"total_eur": {"historisch": 1000.0}},
        "labels": {"historisch": "Historisch"},
        "reference_id": "historisch",
        "heat_fuel": {
            "historisch": {"fuel_kwh": 12000.0, "fuel_eur": 1250.0, "co2_kg": 4000.0}
        },
    }
    row = build_annual_cost_rows(meta)[0]
    assert row["Jahres Kosten [€]"] == "2250,00 €"
    assert row["Brennstoffkosten [€]"] == "1250,00 €"
    assert row["CO2 [kg]"] == "4000"


def test_consumer_heat_source_reads_normalized_or_raw():
    raw = {"id": "wp", "heat_source": {"type": "oil"}}
    assert consumer_heat_source(raw) == {"type": "oil"}
    normalized = {"id": "wp", "thermal": {"heat_source": {"type": "wood"}}}
    assert consumer_heat_source(normalized) == {"type": "wood"}

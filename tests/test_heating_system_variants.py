"""Heating systems as scenario variants: catalog, order guard, cache key, residual, guards."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from house_config.heating_systems import (
    BASELOAD_REFERENCE_CONSUMERS_KEY,
    HEATING_VARIANTS_KEY,
    apply_scenario_heating_systems,
    assert_heating_system_deletable,
    heating_systems_by_id,
    merge_inline_reference_systems,
    normalize_heating_systems,
)
from house_config.profiles_store import normalize_house_profiles_document

_HP = {
    "id": "heating_home",
    "label": "Erdwärmepumpe",
    "heat_source": {"type": "heat_pump", "heat_pump_type": "erde"},
    "nominal_power_kw": 1.9,
}
_GAS = {"id": "gas", "label": "Gasbrennwert", "heat_source": {"type": "gas"}}


def _catalog() -> dict:
    return heating_systems_by_id({"heating_systems": [_HP, _GAS]})


def _house_raw(**profile_fields) -> dict:
    return {
        "profiles": [
            {
                "id": "home",
                "label": "Home",
                "annual_kwh": 9000.0,
                "latitude": 47.4,
                "longitude": 9.7,
                "timezone_name": "Europe/Vienna",
                "netznutzung": {"area_id": "user_no_grid_fee"},
                "consumers": [
                    {
                        "id": "waermepumpe",
                        "label": "Wärmepumpe",
                        "type": "thermal_annual",
                        "heating_system_id": "heating_home",
                        "living_area_m2": 150.0,
                        "building_class": 2,
                        "persons": 2,
                        "hwb_kwh_m2": 40.0,
                    },
                    {"id": "herd", "type": "generic", "annual_kwh": 500.0},
                ],
                **profile_fields,
            }
        ]
    }


def _profile(**profile_fields) -> dict:
    doc = normalize_house_profiles_document(
        _house_raw(**profile_fields), heating_systems=_catalog()
    )
    return doc["profiles"]["home"]


# --- catalog ---------------------------------------------------------------------------


def test_catalog_rejects_duplicates_and_unknown_fields():
    with pytest.raises(ValueError, match="doppelte id"):
        normalize_heating_systems([_GAS, _GAS])
    with pytest.raises(ValueError, match="unbekannte Felder"):
        normalize_heating_systems([{**_GAS, "living_area_m2": 100}])
    with pytest.raises(ValueError, match="heat_source fehlt"):
        normalize_heating_systems([{"id": "x"}])


def test_house_without_catalog_fails_loud():
    with pytest.raises(ValueError, match="nicht übergeben"):
        normalize_house_profiles_document(_house_raw())


def test_delete_guard_names_house_and_scenario():
    house = _house_raw()
    scenarios = {"scenarios": [{"id": "s1", "settings": {"heating_system_ids": {"waermepumpe": "gas"}}}]}
    with pytest.raises(ValueError, match="Hausprofil 'home'"):
        assert_heating_system_deletable("heating_home", house_doc=house, scenarios_doc=scenarios)
    with pytest.raises(ValueError, match="Szenario 's1'"):
        assert_heating_system_deletable("gas", house_doc=house, scenarios_doc=scenarios)
    assert_heating_system_deletable("unused", house_doc=house, scenarios_doc=scenarios)


def test_components_save_refuses_to_drop_the_catalog(tmp_path):
    from house_config.components_store import save_components_document

    path = tmp_path / "components.json"
    path.write_text(json.dumps({"heating_systems": [_GAS]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Heizsystem-Katalog"):
        save_components_document(str(path), {"inverters": [], "batteries": [], "pv_systems": []})
    save_components_document(
        str(path), {"inverters": [], "batteries": [], "pv_systems": [], "heating_systems": [_GAS]}
    )
    assert json.loads(path.read_text(encoding="utf-8"))["heating_systems"][0]["id"] == "gas"


def test_house_configurator_edits_the_reference_entry_in_place():
    raw = _house_raw()["profiles"][0]
    consumer = {**raw["consumers"][0], "heat_source": {"type": "oil"}, "nominal_power_kw": 0.0}
    del consumer["heating_system_id"]
    profile = {**raw, "consumers": [consumer]}
    catalog = [dict(_HP), dict(_GAS)]
    out, new_catalog = merge_inline_reference_systems(
        profile, catalog, existing_refs={"waermepumpe": "heating_home"}
    )
    assert out["consumers"][0]["heating_system_id"] == "heating_home"
    assert "heat_source" not in out["consumers"][0]
    entry = next(e for e in new_catalog if e["id"] == "heating_home")
    assert entry["heat_source"] == {"type": "oil"}
    assert entry["label"] == "Erdwärmepumpe"  # label kept
    assert [e["id"] for e in new_catalog] == ["heating_home", "gas"]


def test_new_house_gets_a_reference_entry():
    consumer = {"id": "wp", "type": "thermal_annual", "heat_source": {"type": "gas"}}
    out, catalog = merge_inline_reference_systems(
        {"id": "neu", "label": "Neubau", "consumers": [consumer]}, [{"id": "heating_neu"}]
    )
    assert out["consumers"][0]["heating_system_id"] == "heating_neu_2"
    assert catalog[-1] == {
        "id": "heating_neu_2",
        "label": "Heizsystem Neubau",
        "heat_source": {"type": "gas"},
    }


# --- scenario variants -----------------------------------------------------------------


def test_picking_the_reference_system_changes_nothing():
    profile = _profile()
    assert apply_scenario_heating_systems(
        profile, {"waermepumpe": "heating_home"}, _catalog(), label="t"
    ) is profile


def test_unknown_pick_fails_loud():
    profile = _profile()
    with pytest.raises(ValueError, match="kein thermal_annual"):
        apply_scenario_heating_systems(profile, {"herd": "gas"}, _catalog(), label="t")
    with pytest.raises(ValueError, match="'nope' fehlt"):
        apply_scenario_heating_systems(profile, {"waermepumpe": "nope"}, _catalog(), label="t")


def test_variant_swaps_generation_and_keeps_reference_consumers():
    profile = _profile()
    variant = apply_scenario_heating_systems(profile, {"waermepumpe": "gas"}, _catalog(), label="t")
    consumer = variant["consumers"][0]
    assert consumer["heating_system_id"] == "gas"
    assert consumer["thermal"]["heat_source"] == {"type": "gas"}
    assert consumer["thermal"]["living_area_m2"] == 150.0  # building demand unchanged
    reference = variant[BASELOAD_REFERENCE_CONSUMERS_KEY][0]
    assert reference["heating_system_id"] == "heating_home"
    assert variant[HEATING_VARIANTS_KEY] == [
        {
            "consumer_id": "waermepumpe",
            "reference_system_id": "heating_home",
            "system_id": "gas",
            "measured_heat_meter": None,
        }
    ]
    assert profile["consumers"][0]["heating_system_id"] == "heating_home"  # input untouched


def test_order_guard_same_baseload_different_heat_load(monkeypatch):
    """Applying the scenario's system before the baseload would shift the baseload."""
    from house_config.baseload import consumer_annual_kwh, profile_baseload_kwh
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    reference = _profile()
    variant = apply_scenario_heating_systems(
        _profile(), {"waermepumpe": "gas"}, _catalog(), label="t"
    )
    ref_heat = consumer_annual_kwh(reference["consumers"][0])
    gas_heat = consumer_annual_kwh(variant["consumers"][0])
    assert ref_heat > 100.0
    assert gas_heat < ref_heat
    assert profile_baseload_kwh(variant) == pytest.approx(profile_baseload_kwh(reference))


def test_measured_data_marks_whether_the_reference_has_a_meter(tmp_path):
    total = tmp_path / "total.csv"
    total.write_text("timestamp,kw\n", encoding="utf-8")
    variant = apply_scenario_heating_systems(
        _profile(total_profile_csv=str(total)), {"waermepumpe": "gas"}, _catalog(), label="t"
    )
    assert variant[HEATING_VARIANTS_KEY][0]["measured_heat_meter"] is False


def test_variant_does_not_replay_the_reference_meter_csv():
    raw = _house_raw()
    raw["profiles"][0]["consumers"][0].update(
        {"profile_csv": "wp.csv", "use_profile_csv": True, "annual_kwh": 3000.0}
    )
    profile = normalize_house_profiles_document(raw, heating_systems=_catalog())["profiles"]["home"]
    variant = apply_scenario_heating_systems(profile, {"waermepumpe": "gas"}, _catalog(), label="t")
    assert variant["consumers"][0]["use_profile_csv"] is False
    assert variant[BASELOAD_REFERENCE_CONSUMERS_KEY][0]["use_profile_csv"] is True


def test_measured_residual_subtracts_the_reference_system(monkeypatch, tmp_path):
    """Hourly residual: total − reference heat pump; the variant only adds its own load."""
    from data import consumption_profiles

    rows = ["timestamp,kw"] + [f"2024-01-01 {h:02d}:00:00,3.0" for h in range(24)]
    total = tmp_path / "total.csv"
    total.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def fake_kw(consumer, _slot_dt, climate=None):
        del climate
        if consumer.get("type") != "thermal_annual":
            return 0.0
        return 1.0 if consumer["heating_system_id"] == "heating_home" else 0.0

    monkeypatch.setattr(consumption_profiles, "modeled_consumer_kw_at_datetime", fake_kw)
    monkeypatch.setattr(
        consumption_profiles,
        "load_hourly_profile_csv",
        lambda _path: [(f"2024-01-01 {h:02d}:00:00", 3.0) for h in range(24)],
    )
    reference = _profile(total_profile_csv=str(total))
    variant = apply_scenario_heating_systems(
        reference, {"waermepumpe": "gas"}, _catalog(), label="t"
    )
    ref_series = consumption_profiles._by_consumer_aligned_to_total_csv(
        reference, str(total), hours=24
    )
    var_series = consumption_profiles._by_consumer_aligned_to_total_csv(
        variant, str(total), hours=24
    )
    assert ref_series["baseload"] == [2.0] * 24
    assert var_series["baseload"] == ref_series["baseload"]
    assert var_series["waermepumpe"] == [0.0] * 24


def test_thermal_year_cache_is_keyed_by_heating_system(monkeypatch):
    from data.modeled_climate import ModeledClimateContext
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    climate = ModeledClimateContext(lat=47.4, lon=9.7, timezone="Europe/Vienna")
    reference = _profile()
    variant = apply_scenario_heating_systems(reference, {"waermepumpe": "gas"}, _catalog(), label="t")
    hp = climate._thermal_hourly_profile_for_year(reference["consumers"][0], 2024)
    gas = climate._thermal_hourly_profile_for_year(variant["consumers"][0], 2024)
    assert sum(hp) > sum(gas)
    assert len(climate._thermal_year_profiles) == 2


# --- scenario resolution ---------------------------------------------------------------


def _write_pack(config_dir) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "house_profiles.json").write_text(json.dumps(_house_raw()), encoding="utf-8")
    (config_dir / "components.json").write_text(
        json.dumps({"inverters": [], "batteries": [], "pv_systems": [], "heating_systems": [_HP, _GAS]}),
        encoding="utf-8",
    )


def test_resolve_scenario_settings_applies_the_variant(tmp_path, monkeypatch):
    from house_config import scenario_resolution

    config_dir = tmp_path / "config"
    _write_pack(config_dir)
    monkeypatch.setattr(scenario_resolution, "_attach_tariffs", lambda out, **_kw: None)
    resolved = scenario_resolution.resolve_scenario_settings(
        {"house_profile_id": "home", "heating_system_ids": {"waermepumpe": "gas"}},
        raw_config={},
        components_path=str(config_dir / "components.json"),
        tariffs_path=str(config_dir / "tariffs.json"),
        house_profiles_path=str(config_dir / "house_profiles.json"),
    )
    profile = resolved["_house_profile"]
    assert profile["consumers"][0]["heating_system_id"] == "gas"
    assert "heating_system_ids" not in resolved
    flex_ids = [c["id"] for c in resolved.get("_planning_flex_consumers") or []]
    assert "waermepumpe_heating_rod" not in flex_ids


def test_live_scenario_rejects_heating_variants():
    from house_config.scenario_resolution import _prepare_live_scenario_settings

    with pytest.raises(ValueError, match="Live rechnet immer mit dem Referenz-Heizsystem"):
        _prepare_live_scenario_settings(
            {"house_profile_id": "home", "heating_system_ids": {"waermepumpe": "gas"}},
            house_profiles_path="unused.json",
        )


def _two_houses_raw(second_ref: str = "heating_other") -> dict:
    raw = _house_raw()
    other = json.loads(json.dumps(raw["profiles"][0]))
    other.update(id="other", label="Other")
    other["consumers"][0]["heating_system_id"] = second_ref
    raw["profiles"].append(other)
    return raw


_OTHER_HP = {**_HP, "id": "heating_other", "label": "Other WP"}


def _two_house_catalog() -> dict:
    return heating_systems_by_id({"heating_systems": [_HP, _OTHER_HP, _GAS]})


def test_shared_reference_entry_fails_loud_on_save(tmp_path):
    from house_config.profiles_store import save_house_profiles_document

    (tmp_path / "components.json").write_text(
        json.dumps({"heating_systems": [_HP, _GAS]}), encoding="utf-8"
    )
    path = tmp_path / "house_profiles.json"
    with pytest.raises(ValueError, match="höchstens einem Haus"):
        save_house_profiles_document(str(path), _two_houses_raw("heating_home"))
    assert not path.exists()


def test_another_houses_reference_system_fails_loud_in_a_scenario():
    from house_config.heating_systems import foreign_reference_ids

    house = normalize_house_profiles_document(
        _two_houses_raw(), heating_systems=_two_house_catalog()
    )
    profile = house["profiles"]["home"]
    foreign = foreign_reference_ids(house, "home")
    assert foreign == {"heating_other"}
    with pytest.raises(ValueError, match="Referenzsystem eines anderen Hauses"):
        apply_scenario_heating_systems(
            profile,
            {"waermepumpe": "heating_other"},
            _two_house_catalog(),
            label="t",
            foreign_references=foreign,
        )
    variant = apply_scenario_heating_systems(
        profile, {"waermepumpe": "gas"}, _two_house_catalog(), label="t", foreign_references=foreign
    )
    assert variant["consumers"][0]["heating_system_id"] == "gas"


def test_scenario_choices_are_own_reference_and_variants():
    from house_config.heating_systems import scenario_heating_choices

    choices = scenario_heating_choices(
        ["heating_home", "heating_other", "gas"],
        house_doc=_two_houses_raw(),
        profile_id="home",
        consumer_id="waermepumpe",
    )
    assert choices == ["heating_home", "gas"]


def test_resolution_rejects_another_houses_reference_system(tmp_path, monkeypatch):
    from house_config import scenario_resolution

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "house_profiles.json").write_text(
        json.dumps(_two_houses_raw()), encoding="utf-8"
    )
    (config_dir / "components.json").write_text(
        json.dumps(
            {
                "inverters": [],
                "batteries": [],
                "pv_systems": [],
                "heating_systems": [_HP, _OTHER_HP, _GAS],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(scenario_resolution, "_attach_tariffs", lambda out, **_kw: None)
    with pytest.raises(ValueError, match="Referenzsystem eines anderen Hauses"):
        scenario_resolution.resolve_scenario_settings(
            {"house_profile_id": "home", "heating_system_ids": {"waermepumpe": "heating_other"}},
            raw_config={},
            components_path=str(config_dir / "components.json"),
            tariffs_path=str(config_dir / "tariffs.json"),
            house_profiles_path=str(config_dir / "house_profiles.json"),
        )


# --- reference-system change in the house configurator --------------------------------


def _form_consumer(source: dict) -> dict:
    consumer = dict(_house_raw()["profiles"][0]["consumers"][0])
    consumer.pop("heating_system_id")
    return {**consumer, "heat_source": source}


@pytest.mark.parametrize(
    "source, changed",
    [
        ({"type": "gas"}, True),
        ({"type": "heat_pump", "heat_pump_type": "luft"}, False),  # heat_pump_type: calibration
        ({"type": "heat_pump", "heat_pump_type": "erde", "efficiency": 3.1}, False),
    ],
)
def test_reference_change_counts_only_the_heat_source_type(source, changed):
    from house_config.heating_systems import reference_heat_source_changes

    out = reference_heat_source_changes(
        [_form_consumer(source)],
        saved_house_doc=_house_raw(),
        heating_systems=_catalog(),
        profile_id="home",
    )
    assert bool(out) is changed
    if changed:
        assert out[0]["old_heat_source"]["type"] == "heat_pump"
        assert out[0]["new_type"] == "gas"


def test_reference_change_needs_a_saved_house():
    from house_config.heating_systems import reference_heat_source_changes

    assert reference_heat_source_changes(
        [_form_consumer({"type": "gas"})],
        saved_house_doc={"profiles": []},
        heating_systems=_catalog(),
        profile_id="home",
    ) == []


def test_consumption_data_kind():
    from house_config.heating_systems import consumption_data_kind

    consumer = {"id": "waermepumpe", "type": "thermal_annual"}
    measured = {"annual_kwh": 9000.0, "total_profile_csv": "t.csv", "consumers": [consumer]}
    assert consumption_data_kind(measured, "waermepumpe") == "csv"
    metered = {**consumer, "use_profile_csv": True, "profile_csv": "wp.csv"}
    assert consumption_data_kind({"annual_kwh": 9000.0, "consumers": [metered]}, "waermepumpe") == "csv"
    assert consumption_data_kind({"annual_kwh": 9000.0, "consumers": [consumer]}, "waermepumpe") == "annual"
    assert consumption_data_kind({"annual_kwh": 0.0, "consumers": [consumer]}, "waermepumpe") is None


def test_reference_fingerprint_separates_heating_variants():
    from house_config.planning_flex_bridge import heating_reference_fingerprint

    reference = _profile()
    variant = apply_scenario_heating_systems(reference, {"waermepumpe": "gas"}, _catalog(), label="t")
    assert heating_reference_fingerprint({"_house_profile": reference}) == ()
    assert heating_reference_fingerprint({"_house_profile": variant}) == (("waermepumpe", "gas"),)


def test_loaded_profile_reads_catalog_and_reloads_after_catalog_change(tmp_path):
    import os
    import time

    from house_config.profiles_store import (
        clear_house_profiles_doc_cache,
        load_house_profiles_document,
    )

    config_dir = tmp_path / "config"
    _write_pack(config_dir)
    clear_house_profiles_doc_cache()
    path = str(config_dir / "house_profiles.json")
    first = load_house_profiles_document(path)["profiles"]["home"]["consumers"][0]
    assert first["nominal_power_kw"] == 1.9
    comp = config_dir / "components.json"
    doc = json.loads(comp.read_text(encoding="utf-8"))
    doc["heating_systems"][0]["nominal_power_kw"] = 2.5
    comp.write_text(json.dumps(doc), encoding="utf-8")
    stamp = time.time() + 5
    os.utime(comp, (stamp, stamp))
    again = load_house_profiles_document(path)["profiles"]["home"]["consumers"][0]
    assert again["nominal_power_kw"] == 2.5


# --- heating rod: no measured data (decided 2026-11-03) ----------------------------------

_STORAGE = {"volume_liters": 500.0}
_ROD = {"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}
_HP_ROD = {**_HP, "heat_storage": _STORAGE, "parts": [_ROD]}


def _rod_catalog() -> dict:
    return heating_systems_by_id({"heating_systems": [_HP_ROD, _GAS]})


def _rod_profile(**consumer_fields) -> dict:
    raw = _house_raw()
    raw["profiles"][0]["consumers"][0].update(consumer_fields)
    return normalize_house_profiles_document(raw, heating_systems=_rod_catalog())["profiles"]["home"]


@pytest.mark.parametrize(
    "field, value",
    [("heating_rod_annual_kwh", 300.0), ("heating_rod_profile_csv", "rod.csv")],
)
def test_measured_rod_fields_fail_loud_on_load(field, value):
    with pytest.raises(ValueError, match=f"{field} wird nicht mehr unterstützt — Feld entfernen"):
        _rod_profile(**{field: value})


@pytest.mark.parametrize(
    "field, value",
    [
        ("heat_source", {"type": "gas"}),
        ("heat_storage", _STORAGE),
        ("parts", [_ROD]),
        ("nominal_power_kw", 2.0),
        ("min_on_quarterhours", 4),
    ],
)
def test_inline_generation_fields_fail_loud_next_to_the_reference(field, value):
    raw = _house_raw()
    raw["profiles"][0]["consumers"][0][field] = value
    with pytest.raises(ValueError, match=f"{field} gehört in den Heizsystem-Katalog"):
        normalize_house_profiles_document(raw, heating_systems=_catalog())


def test_rod_has_no_demand_of_its_own(monkeypatch):
    from house_config.baseload import profile_baseload_kwh
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    store_only = heating_systems_by_id({"heating_systems": [{**_HP, "heat_storage": _STORAGE}]})
    without_rod = normalize_house_profiles_document(_house_raw(), heating_systems=store_only)
    assert profile_baseload_kwh(_rod_profile()) == pytest.approx(
        profile_baseload_kwh(without_rod["profiles"]["home"])
    )


def _rod_profile_total(total: str, **consumer_fields) -> dict:
    raw = _house_raw(total_profile_csv=total)
    raw["profiles"][0]["consumers"][0].update(consumer_fields)
    return normalize_house_profiles_document(raw, heating_systems=_rod_catalog())["profiles"]["home"]


def test_variant_hints_name_exact_or_modeled_subtraction(tmp_path):
    from house_config.heating_systems import heating_variant_hints

    total = str(tmp_path / "total.csv")
    modeled = apply_scenario_heating_systems(
        _rod_profile_total(total), {"waermepumpe": "gas"}, _rod_catalog(), label="t"
    )
    assert "modellierte Profil" in heating_variant_hints(modeled)[0]
    metered = apply_scenario_heating_systems(
        _rod_profile_total(total, profile_csv="wp.csv", use_profile_csv=True, annual_kwh=3000.0),
        {"waermepumpe": "gas"},
        _rod_catalog(),
        label="t",
    )
    assert "exakt abgezogen" in heating_variant_hints(metered)[0]
    assert heating_variant_hints(_rod_profile()) == []


def test_hourly_residual_keeps_a_real_rod_in_the_baseload(monkeypatch, tmp_path):
    from data import consumption_profiles

    total = tmp_path / "total.csv"
    total.write_text("timestamp,kw\n", encoding="utf-8")
    monkeypatch.setattr(
        consumption_profiles, "modeled_consumer_kw_at_datetime", lambda *_a, **_k: 0.0
    )
    monkeypatch.setattr(
        consumption_profiles,
        "load_hourly_profile_csv",
        lambda _path: [(f"2024-01-01 {h:02d}:00:00", 3.0) for h in range(24)],
    )
    profile = _rod_profile_total(str(total))
    series = consumption_profiles._by_consumer_aligned_to_total_csv(profile, str(total), hours=24)
    # Accepted double count (decided 2026-11-03): nothing is subtracted for the rod.
    assert series["baseload"] == [3.0] * 24
    assert not any("heating_rod" in key for key in series)


# --- SE planning uses the scenario's profile (rod bound, thermal contexts) --------------

_GAS_ROD = {**_GAS, "id": "gas_rod", "heat_storage": _STORAGE, "parts": [_ROD]}
_ROD_ID = "waermepumpe_heating_rod"


def _gas_catalog() -> dict:
    return heating_systems_by_id({"heating_systems": [_GAS, _GAS_ROD]})


def _gas_house(system_id: str, *, consumer_id: str = "waermepumpe") -> dict:
    raw = _house_raw()
    consumer = raw["profiles"][0]["consumers"][0]
    consumer.update(id=consumer_id, heating_system_id=system_id)
    return normalize_house_profiles_document(raw, heating_systems=_gas_catalog())["profiles"][
        "home"
    ]


def _scenario_params(profile: dict) -> dict:
    from house_config.planning_flex_bridge import collect_planning_flex_consumers

    return {
        "_house_profile": profile,
        "_planning_flex_consumers": collect_planning_flex_consumers(profile),
    }


def _se_rod_plan(monkeypatch, live_profile: dict, scenario_profile: dict) -> tuple[list, float]:
    """Flex ids and rod energy [kWh] of one SE day: cheap noon, gas house (book has no rod)."""
    from datetime import date, time

    from optimizer.cbc_solver import solve_with_strict_fallback
    from optimizer.milp import _add_milp_objective
    from optimizer.milp_consumers import (
        _add_consumer_delivery_constraints,
        filter_feasible_consumers,
    )
    from optimizer.milp_horizon import _build_milp_model
    from optimizer.milp_inputs import _resolve_thermal_flex_contexts
    from optimizer.scenario_planning_scope import planning_scenario_scope
    from optimizer.targets import resolve_horizon_consumer_targets_kwh
    from optimizer.thermal_flex_context import add_thermal_flex_constraints
    from simulation.engine_scenario import _flexible_consumers_from_scenario

    live = _scenario_params(live_profile)
    monkeypatch.setattr("config.get_resolved_runtime_settings", lambda: live)
    # The backtesting fixture adds its own consumers in load_flexible_consumers.
    monkeypatch.setattr(
        "config.get_flexible_consumers",
        lambda optimizer_only=False: list(live["_planning_flex_consumers"]),
    )
    monkeypatch.setattr(
        "data.modeled_climate.ModeledClimateContext.from_scenario",
        classmethod(lambda cls, _params: None),
    )
    scenario = _scenario_params(scenario_profile)
    day = date(2024, 1, 15)
    prices = [40.0] * 10 + [2.0] * 4 + [40.0] * 10
    matrix = [
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
    with planning_scenario_scope(scenario):
        flex = _flexible_consumers_from_scenario(scenario)
        book = {str(c["id"]): 0.0 for c in flex}  # resolve_profile_spec_flex_targets books no rod
        remaining = resolve_horizon_consumer_targets_kwh(matrix, book, flexible_consumers=flex)
        contexts = _resolve_thermal_flex_contexts(matrix, flex, None)
    horizon = len(matrix)
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
    rod_on = [
        var.varValue for var in model.consumer_on.get(_ROD_ID, []) if var.varValue is not None
    ]
    rod_kwh = sum(1.0 for value in rod_on if value > 0.5) * 3.0 * float(model.dt_h)
    return [str(c["id"]) for c in flex], rod_kwh


def test_se_variant_with_rod_plans_the_rod_beside_a_reference_without(monkeypatch):
    live = _gas_house("gas")
    variant = apply_scenario_heating_systems(
        live, {"waermepumpe": "gas_rod"}, _gas_catalog(), label="t"
    )
    flex_ids, rod_kwh = _se_rod_plan(monkeypatch, live, variant)
    assert _ROD_ID in flex_ids
    assert rod_kwh > 0.0


def test_se_variant_without_rod_has_no_rod_beside_a_reference_with(monkeypatch):
    live = _gas_house("gas_rod")
    variant = apply_scenario_heating_systems(live, {"waermepumpe": "gas"}, _gas_catalog(), label="t")
    flex_ids, rod_kwh = _se_rod_plan(monkeypatch, live, variant)
    assert _ROD_ID not in flex_ids
    assert rod_kwh == 0.0


def test_se_rod_bound_and_contexts_read_the_scenario_house(monkeypatch):
    """Another house (other thermal id) than Live: the rod must not look into the Live house."""
    live = _gas_house("gas", consumer_id="heizung_live")
    scenario = _gas_house("gas_rod")
    flex_ids, rod_kwh = _se_rod_plan(monkeypatch, live, scenario)
    assert flex_ids == [_ROD_ID]
    assert rod_kwh > 0.0


def test_se_anchor_step_plans_inside_the_scenario_scope(monkeypatch):
    from optimizer.scenario_planning_scope import planning_runtime_settings
    from simulation import anchor_step

    scenario = _scenario_params(_gas_house("gas_rod"))
    seen: list[dict] = []

    def _capture(*_args, **_kwargs):
        seen.append(planning_runtime_settings())
        raise RuntimeError("stop")

    monkeypatch.setattr(anchor_step, "_build_anchor_window_plan", _capture)
    with pytest.raises(RuntimeError, match="stop"):
        anchor_step._simulate_anchor_step(
            datetime(2024, 1, 15),
            50.0,
            horizon_mode="fixed_24h",
            cache=None,
            prices_df=None,
            scenario_params=scenario,
            battery_params={},
            feed_in_settings=None,
            hours_done=0,
            collect_cbc=False,
        )
    assert seen == [scenario]
    assert planning_runtime_settings() is not scenario

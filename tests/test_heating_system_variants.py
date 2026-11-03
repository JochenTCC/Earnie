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


# --- measured heating rod (SE baseload) ------------------------------------------------

_STORAGE = {"volume_liters": 500.0}
_ROD = {"id": "heating_rod", "type": "heating_rod", "nominal_power_kw": 3.0}
_HP_ROD = {**_HP, "heat_storage": _STORAGE, "parts": [_ROD]}


def _rod_catalog() -> dict:
    return heating_systems_by_id({"heating_systems": [_HP_ROD, _GAS]})


def _rod_profile(**consumer_fields) -> dict:
    raw = _house_raw()
    raw["profiles"][0]["consumers"][0].update(consumer_fields)
    return normalize_house_profiles_document(raw, heating_systems=_rod_catalog())["profiles"]["home"]


def test_measured_rod_fields_are_exclusive_and_need_a_rod():
    with pytest.raises(ValueError, match="schließen sich aus"):
        _rod_profile(heating_rod_annual_kwh=300.0, heating_rod_profile_csv="rod.csv")
    with pytest.raises(ValueError, match="einen Heizstab hat"):
        normalize_house_profiles_document(
            _house_raw_with(heating_rod_annual_kwh=300.0), heating_systems=_catalog()
        )
    with pytest.raises(ValueError, match="muss > 0"):
        _rod_profile(heating_rod_annual_kwh=0)


def _house_raw_with(**consumer_fields) -> dict:
    raw = _house_raw()
    raw["profiles"][0]["consumers"][0].update(consumer_fields)
    return raw


def test_measured_rod_fields_survive_save():
    from house_config.profiles_store import _serialize_consumer

    profile = _rod_profile(heating_rod_annual_kwh=300.0)
    out = _serialize_consumer(profile["consumers"][0])
    assert out["heating_rod_annual_kwh"] == 300.0
    assert "heating_rod_profile_csv" not in out


def test_annual_rod_kwh_comes_off_the_baseload_for_every_variant(monkeypatch):
    from house_config.baseload import profile_baseload_kwh
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    without = profile_baseload_kwh(_rod_profile())
    with_rod = _rod_profile(heating_rod_annual_kwh=400.0)
    assert profile_baseload_kwh(with_rod) == pytest.approx(without - 400.0)
    gas = apply_scenario_heating_systems(
        _rod_profile(heating_rod_annual_kwh=400.0), {"waermepumpe": "gas"}, _rod_catalog(), label="t"
    )
    assert profile_baseload_kwh(gas) == pytest.approx(without - 400.0)


def test_measured_rod_kw_from_csv_or_lump_sum(monkeypatch):
    from data import consumption_profiles
    from house_config.heating_systems import profile_measured_rod_kw_at

    slot = datetime(2024, 1, 1, 12)
    lump = _rod_profile(heating_rod_annual_kwh=876.0)
    assert profile_measured_rod_kw_at(lump, slot) == pytest.approx(0.1)
    monkeypatch.setattr(consumption_profiles, "csv_kw_at_datetime", lambda _p, _dt: 2.5)
    measured = _rod_profile(heating_rod_profile_csv="rod.csv")
    assert profile_measured_rod_kw_at(measured, slot) == 2.5
    assert profile_measured_rod_kw_at(_rod_profile(), slot) == 0.0


def test_double_count_hint_only_with_measured_data_and_no_rod_data(tmp_path):
    from house_config.heating_systems import heating_rod_double_count_hint

    total = str(tmp_path / "total.csv")
    assert heating_rod_double_count_hint(_rod_profile()) is None  # profile_spec house
    hint = heating_rod_double_count_hint(_rod_profile_total(total))
    assert hint is not None and "doppelt gezählt" in hint
    assert heating_rod_double_count_hint(
        _rod_profile_total(total, heating_rod_annual_kwh=300.0)
    ) is None


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


def test_hourly_residual_subtracts_the_measured_rod(monkeypatch, tmp_path):
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
    profile = _rod_profile_total(str(total), heating_rod_annual_kwh=8760.0)
    series = consumption_profiles._by_consumer_aligned_to_total_csv(profile, str(total), hours=24)
    assert series["baseload"] == [2.0] * 24
    assert "__measured_heating_rod" not in series

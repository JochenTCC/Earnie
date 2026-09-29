"""Unit tests for live-only holiday / absent mode."""
from __future__ import annotations

from optimizer.absent_mode import (
    apply_absent_mode_to_live_flex,
    apply_thermal_absent_override,
    effective_absent_mode,
    ehal_read_state,
    matrix_is_live_snapshot,
    thermal_source_with_live_absent,
)


def test_effective_absent_or_logic():
    assert effective_absent_mode(False, None) is False
    assert effective_absent_mode(False, False) is False
    assert effective_absent_mode(True, False) is True
    assert effective_absent_mode(False, True) is True
    assert effective_absent_mode(True, True) is True
    assert effective_absent_mode(True, None) is True


def test_ehal_read_state_labels():
    assert ehal_read_state(None, bound=False) == "unbound"
    assert ehal_read_state(None, bound=True) == "unreadable"
    assert ehal_read_state(True, bound=True) == "on"
    assert ehal_read_state(False, bound=True) == "off"


def test_apply_live_flex_excludes_opt_in_non_thermal():
    profile = {
        "consumers": [
            {
                "id": "haus",
                "type": "thermal_annual",
                "absent_mode_enabled": True,
            },
            {
                "id": "wasch",
                "type": "generic",
                "absent_mode_enabled": True,
            },
            {
                "id": "ev1",
                "type": "ev",
                "absent_mode_enabled": False,
            },
            {
                "id": "ev2",
                "type": "ev",
                "absent_mode_enabled": True,
            },
            {
                "id": "pool",
                "type": "thermal_rc",
                "absent_mode_enabled": True,
            },
        ]
    }
    milp = [
        {"id": "haus", "daily_target_source": "thermal_annual"},
        {"id": "wasch"},
        {"id": "ev1"},
        {"id": "ev2", "type": "ev"},
        {"id": "pool"},
    ]
    assert apply_absent_mode_to_live_flex(milp, profile, active=False) == milp
    kept = apply_absent_mode_to_live_flex(milp, profile, active=True)
    assert [c["id"] for c in kept] == ["haus", "ev1"]


def test_live_absent_skip_fixed_ids_known_opt_in():
    from optimizer.absent_mode import live_absent_skip_fixed_ids

    profile = {
        "consumers": [
            {
                "id": "kochen",
                "type": "generic",
                "earnie_role": "known",
                "absent_mode_enabled": True,
            },
            {
                "id": "tv",
                "type": "generic",
                "earnie_role": "known",
                "absent_mode_enabled": False,
            },
            {
                "id": "haus",
                "type": "thermal_annual",
                "absent_mode_enabled": True,
            },
        ]
    }
    assert live_absent_skip_fixed_ids(profile, active=False) == set()
    assert live_absent_skip_fixed_ids(profile, active=True) == {"kochen"}

def test_thermal_absent_override_sets_temp_and_persons_zero():
    source = {
        "id": "haus",
        "type": "thermal_annual",
        "absent_mode_enabled": True,
        "thermal": {
            "target_temp_c": 21.5,
            "absent_temp_reduction_c": 5.5,
            "persons": 3,
            "heating_limit_c": 15.0,
        },
    }
    out = apply_thermal_absent_override(source)
    assert out["thermal"]["target_temp_c"] == 16.0
    assert out["thermal"]["persons"] == 0
    assert out["persons"] == 0
    assert source["thermal"]["persons"] == 3


def test_thermal_source_with_live_absent_respects_opt_in():
    source = {
        "id": "haus",
        "absent_mode_enabled": False,
        "thermal": {
            "target_temp_c": 21.5,
            "absent_temp_reduction_c": 7.5,
            "persons": 2,
        },
    }
    assert thermal_source_with_live_absent(source, live_absent_active=True) is source
    opted = dict(source, absent_mode_enabled=True)
    overridden = thermal_source_with_live_absent(opted, live_absent_active=True)
    assert overridden["thermal"]["target_temp_c"] == 14.0
    assert overridden["thermal"]["persons"] == 0
    assert thermal_source_with_live_absent(opted, live_absent_active=False) is opted


def test_matrix_is_live_snapshot():
    assert matrix_is_live_snapshot([]) is False
    assert matrix_is_live_snapshot([{"consumption_mode": "profile_spec"}]) is False
    assert matrix_is_live_snapshot([{"consumption_mode": "live_snapshot"}]) is True


def test_normalize_absent_fields_roundtrip(tmp_path, monkeypatch):
    from house_config.profiles_store import (
        normalize_house_profiles_document,
        save_house_profiles_document,
        load_house_profiles_document,
    )
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)

    doc = {
        "profiles": [
            {
                "id": "home",
                "label": "Home",
                "annual_kwh": 4000,
                "absent_mode": True,
                "latitude": 48.0,
                "longitude": 11.0,
                "consumers": [
                    {
                        "id": "haus",
                        "label": "Haus Wärme",
                        "type": "thermal_annual",
                        "nominal_power_kw": 3.5,
                        "absent_mode_enabled": True,
                        "living_area_m2": 100,
                        "building_class": 3,
                        "heat_pump_type": "luft",
                        "persons": 2,
                        "target_temp_c": 21.5,
                        "absent_temp_reduction_c": 4.0,
                    }
                ],
            }
        ]
    }
    normalized = normalize_house_profiles_document(doc)
    profile = normalized["profiles"]["home"]
    assert profile["absent_mode"] is True
    consumer = profile["consumers"][0]
    assert consumer["absent_mode_enabled"] is True
    assert consumer["thermal"]["absent_temp_reduction_c"] == 4.0
    assert "absent_temp_c" not in consumer["thermal"]
    path = tmp_path / "house_profiles.json"
    save_house_profiles_document(str(path), {"profiles": [doc["profiles"][0]]})
    reloaded = load_house_profiles_document(str(path))
    assert reloaded["profiles"]["home"]["absent_mode"] is True
    thermal = reloaded["profiles"]["home"]["consumers"][0]["thermal"]
    assert thermal["absent_temp_reduction_c"] == 4.0
    assert "absent_temp_c" not in thermal


def test_normalize_migrates_legacy_absent_temp_c(tmp_path, monkeypatch):
    from house_config.profiles_store import (
        normalize_house_profiles_document,
        save_house_profiles_document,
        load_house_profiles_document,
    )
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)

    doc = {
        "profiles": [
            {
                "id": "home",
                "label": "Home",
                "annual_kwh": 4000,
                "latitude": 48.0,
                "longitude": 11.0,
                "consumers": [
                    {
                        "id": "haus",
                        "label": "Haus Wärme",
                        "type": "thermal_annual",
                        "nominal_power_kw": 3.5,
                        "living_area_m2": 100,
                        "building_class": 3,
                        "heat_pump_type": "luft",
                        "persons": 2,
                        "target_temp_c": 21.5,
                        "absent_temp_c": 15.0,
                    }
                ],
            }
        ]
    }
    normalized = normalize_house_profiles_document(doc)
    thermal = normalized["profiles"]["home"]["consumers"][0]["thermal"]
    assert thermal["absent_temp_reduction_c"] == 6.5
    path = tmp_path / "house_profiles.json"
    save_house_profiles_document(str(path), {"profiles": [doc["profiles"][0]]})
    reloaded = load_house_profiles_document(str(path))
    assert reloaded["profiles"]["home"]["consumers"][0]["thermal"][
        "absent_temp_reduction_c"
    ] == 6.5


def _plant_doc(binding: str) -> dict:
    return {"plant": {"ehal_bindings": {"sens_absent_mode": binding}}}


def test_read_ehal_absent_unbound():
    from optimizer.absent_mode import read_ehal_absent_mode

    value, bound = read_ehal_absent_mode({"plant": {"ehal_bindings": {}}})
    assert value is None
    assert bound is False


def test_read_ehal_absent_loxone(monkeypatch):
    from optimizer import absent_mode

    monkeypatch.setattr(
        "integrations.ehal_live.is_ha_backend", lambda: False
    )
    monkeypatch.setattr(
        "integrations.ehal_live.is_openems_backend", lambda: False
    )
    monkeypatch.setattr(
        "integrations.loxone_client.fetch_loxone_generic_value",
        lambda _name: 1.0,
    )
    value, bound = absent_mode.read_ehal_absent_mode(_plant_doc("Earnie_Abwesend"))
    assert bound is True
    assert value is True


def test_read_ehal_absent_ha(monkeypatch):
    from optimizer import absent_mode

    class _Cfg:
        entities = {"sens_absent_mode": "input_boolean.holiday"}

    class _Adapter:
        cfg = _Cfg()

        def read_state(self, entity_id: str) -> dict:
            assert entity_id == "input_boolean.holiday"
            return {"state": "on"}

    monkeypatch.setattr("integrations.ehal_live.is_ha_backend", lambda: True)
    monkeypatch.setattr("integrations.ehal_live.is_openems_backend", lambda: False)
    monkeypatch.setattr("integrations.ehal_live.get_ha_adapter", lambda: _Adapter())
    value, bound = absent_mode.read_ehal_absent_mode(
        _plant_doc("input_boolean.holiday")
    )
    assert bound is True
    assert value is True


def test_read_ehal_absent_openems(monkeypatch):
    from optimizer import absent_mode

    class _Adapter:
        def read_channel(self, component: str, channel: str) -> float:
            assert component == "ctrlHoliday0"
            assert channel == "HolidayMode"
            return 1.0

    monkeypatch.setattr("integrations.ehal_live.is_ha_backend", lambda: False)
    monkeypatch.setattr("integrations.ehal_live.is_openems_backend", lambda: True)
    monkeypatch.setattr(
        "integrations.ehal_live.get_openems_adapter", lambda: _Adapter()
    )
    value, bound = absent_mode.read_ehal_absent_mode(
        _plant_doc("ctrlHoliday0/HolidayMode")
    )
    assert bound is True
    assert value is True


def test_read_ehal_absent_openems_invalid_channel(monkeypatch):
    from optimizer import absent_mode

    monkeypatch.setattr("integrations.ehal_live.is_ha_backend", lambda: False)
    monkeypatch.setattr("integrations.ehal_live.is_openems_backend", lambda: True)
    value, bound = absent_mode.read_ehal_absent_mode(_plant_doc("no-slash"))
    assert bound is True
    assert value is None


def test_ha_all_fields_includes_absent_mode():
    from house_config.ha_ehal_bindings import HA_ALL_FIELDS, aggregate_ha_entities

    assert "sens_absent_mode" in HA_ALL_FIELDS
    house = {
        "plant": {
            "ehal_bindings": {
                "sens_ess_soc": "sensor.soc",
                "sens_absent_mode": "binary_sensor.holiday",
            }
        },
        "profiles": {},
    }
    aggregated = aggregate_ha_entities(house)
    assert aggregated["sens_absent_mode"] == "binary_sensor.holiday"

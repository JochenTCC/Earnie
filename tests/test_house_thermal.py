"""House-level thermal properties: loader, switch „Heizung betrachten“, save round trip."""
from __future__ import annotations

import copy

import pytest

from house_config.heating_systems import (
    apply_scenario_heating_systems,
    heating_systems_by_id,
    reference_ids_by_profile,
)
from house_config.profiles_store import (
    _serialize_profile,
    normalize_house_profiles_document,
)

_CATALOG = heating_systems_by_id(
    {
        "heating_systems": [
            {
                "id": "heating_home",
                "heat_source": {"type": "heat_pump", "heat_pump_type": "luft"},
                "nominal_power_kw": 2.0,
            },
            {"id": "gas", "heat_source": {"type": "gas"}},
        ]
    }
)


def _raw(**profile_fields) -> dict:
    profile = {
        "id": "home",
        "label": "Home",
        "annual_kwh": 9000.0,
        "latitude": 47.4,
        "longitude": 9.7,
        "netznutzung": {"area_id": "user_no_grid_fee"},
        "heating_enabled": True,
        "persons": 3,
        "thermal": {"living_area_m2": 140.0, "hwb_kwh_m2": 55.0, "absent_mode_enabled": True},
        "consumers": [
            {"id": "herd", "type": "generic", "annual_kwh": 500.0},
            {
                "id": "wp",
                "type": "thermal_annual",
                "heating_system_id": "heating_home",
                "solar_thermal_area_m2": 4.0,
            },
        ],
    }
    profile.update(profile_fields)
    return {"profiles": [profile]}


def _load(doc: dict) -> dict:
    return normalize_house_profiles_document(doc, heating_systems=_CATALOG)["profiles"]["home"]


def test_consumer_takes_the_building_fields_from_the_house():
    profile = _load(_raw())
    assert profile["heating_enabled"] is True
    assert profile["persons"] == 3
    assert profile["thermal"]["living_area_m2"] == 140.0
    wp = next(c for c in profile["consumers"] if c["id"] == "wp")
    assert wp["thermal"]["living_area_m2"] == 140.0
    assert wp["thermal"]["hwb_kwh_m2"] == 55.0
    assert wp["thermal"]["persons"] == 3
    assert wp["thermal"]["solar_thermal_area_m2"] == 4.0
    assert wp["thermal"]["heat_source"]["type"] == "heat_pump"
    assert wp["absent_mode_enabled"] is True
    assert "absent_mode_enabled" not in wp["thermal"]


def test_switch_off_keeps_consumer_and_block_out_of_planning():
    profile = _load(_raw(heating_enabled=False))
    assert [c["id"] for c in profile["consumers"]] == ["herd"]
    assert [c["id"] for c in profile["inactive_consumers"]] == ["wp"]
    assert profile["thermal"]["living_area_m2"] == 140.0
    # The reference system stays protected while the switch is off.
    assert reference_ids_by_profile({"profiles": {"home": profile}}) == {
        "home": {"wp": "heating_home"}
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_save_round_trip_keeps_every_value(enabled: bool):
    raw = _raw(heating_enabled=enabled)
    profile = _load(raw)
    out = _serialize_profile(profile)
    assert out["heating_enabled"] is enabled
    assert out["persons"] == 3
    assert out["thermal"]["living_area_m2"] == 140.0
    assert out["thermal"]["hwb_kwh_m2"] == 55.0
    wp = next(c for c in out["consumers"] if c["id"] == "wp")
    assert wp == {
        "id": "wp",
        "label": "wp",
        "type": "thermal_annual",
        "use_profile_csv": False,
        "solar_thermal_area_m2": 4.0,
        "solar_thermal_tilt_deg": 18.0,
        "solar_thermal_azimuth_deg": 0.0,
        "heating_system_id": "heating_home",
    }
    assert _load({"profiles": [out]}) == profile


@pytest.mark.parametrize("enabled", [True, False])
def test_normalized_profile_saves_through_the_catalog_merge(enabled: bool):
    """Pages that save the loaded document: inline generation goes back to the catalog."""
    from house_config.heating_systems import merge_inline_reference_systems

    profile = _load(_raw(heating_enabled=enabled))
    merged, catalog = merge_inline_reference_systems(
        copy.deepcopy(profile),
        [{"id": "heating_home", "label": "WP", "heat_source": {"type": "gas"}}],
    )
    assert catalog[0]["heat_source"]["type"] == "heat_pump"
    assert _load({"profiles": [merged]}) == profile


def test_turning_the_switch_on_again_brings_the_consumer_back():
    out = _serialize_profile(_load(_raw(heating_enabled=False)))
    on = _load({"profiles": [{**out, "heating_enabled": True}]})
    assert [c["id"] for c in on["consumers"]] == ["herd", "wp"]
    assert "inactive_consumers" not in on
    assert on["consumers"][1]["thermal"]["living_area_m2"] == 140.0


def test_house_without_heating_needs_no_switch_or_block():
    raw = _raw(consumers=[{"id": "herd", "type": "generic", "annual_kwh": 500.0}])
    for key in ("heating_enabled", "thermal", "persons"):
        raw["profiles"][0].pop(key)
    profile = normalize_house_profiles_document(raw)["profiles"]["home"]
    assert profile["heating_enabled"] is False
    assert profile["persons"] == 2
    assert "thermal" not in profile


def test_heating_consumer_without_switch_needs_migration():
    raw = _raw()
    raw["profiles"][0].pop("heating_enabled")
    with pytest.raises(ValueError, match="heating_enabled fehlt.*migrieren"):
        _load(raw)


def test_switch_on_without_building_block_fails_loud():
    raw = _raw()
    raw["profiles"][0].pop("thermal")
    with pytest.raises(ValueError, match="Gebäude-Wärmedaten"):
        _load(raw)


@pytest.mark.parametrize("key", ["living_area_m2", "persons", "target_temp_c", "absent_temp_c"])
def test_building_field_on_the_consumer_fails_loud(key: str):
    raw = _raw()
    raw["profiles"][0]["consumers"][1][key] = 1.0
    with pytest.raises(ValueError, match="gehört ans Hausprofil"):
        _load(raw)


def test_unknown_field_in_the_house_block_fails_loud():
    raw = _raw()
    raw["profiles"][0]["thermal"]["heat_source"] = {"type": "gas"}
    with pytest.raises(ValueError, match="unbekannte Felder heat_source"):
        _load(raw)


def test_switch_must_be_a_bool():
    with pytest.raises(ValueError, match="true oder false"):
        _load(_raw(heating_enabled="yes"))


def test_scenario_pick_for_a_house_with_the_switch_off_fails_loud():
    profile = _load(_raw(heating_enabled=False))
    with pytest.raises(ValueError, match="„Heizung betrachten“ ausgeschaltet"):
        apply_scenario_heating_systems(profile, {"wp": "gas"}, _CATALOG, label="Szenario s1")

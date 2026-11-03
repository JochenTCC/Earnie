"""HK soft defaults come from house_profiles.schema.json (single source)."""
from __future__ import annotations

import pytest

from house_config.profile_schema_defaults import (
    consumer_default,
    ev_schedule_default,
    heat_storage_default,
    house_thermal_default,
    profile_default,
    schema_default,
    thermal_rc_default,
)


def test_getters_read_schema_defaults():
    assert house_thermal_default("absent_temp_reduction_c") == 2.5
    assert house_thermal_default("living_area_m2") == 120.0
    assert house_thermal_default("building_mass") == "mittel"
    assert house_thermal_default("absent_mode_enabled") is False
    assert profile_default("persons") == 2
    assert profile_default("heating_enabled") is False
    assert profile_default("latitude") == 48.2
    assert profile_default("longitude") == 11.0
    assert thermal_rc_default("setpoint_c") == 36.5
    assert heat_storage_default("setpoint_c") == 45.0
    assert ev_schedule_default("charging_efficiency") == 0.95


def test_type_specific_default_wins_over_plain_default():
    assert consumer_default("min_on_quarterhours") == 1
    assert consumer_default("min_on_quarterhours", consumer_type="thermal_annual") == 1
    assert consumer_default("min_on_quarterhours", consumer_type="thermal_rc") == 8


def test_field_without_default_fails_loud():
    with pytest.raises(KeyError, match="hat keinen"):
        house_thermal_default("hwb_kwh_m2")


def test_unknown_field_fails_loud():
    with pytest.raises(KeyError, match="fehlt"):
        schema_default("consumer", "no_such_field")


def test_house_thermal_missing_keys_use_schema_defaults():
    from house_config.house_thermal import normalize_house_thermal

    thermal = normalize_house_thermal({}, label="p")
    assert thermal["absent_temp_reduction_c"] == 2.5
    assert thermal["absent_mode_enabled"] is False
    assert "hwb_kwh_m2" not in thermal
    assert thermal["living_area_m2"] == 120.0
    assert thermal["target_temp_c"] == 21.5
    assert thermal["building_mass"] == "mittel"
    assert thermal["house_tolerance_c"] == 0.5


def test_house_thermal_explicit_zero_area_is_kept():
    from house_config.house_thermal import normalize_house_thermal

    assert normalize_house_thermal({"living_area_m2": 0}, label="p")["living_area_m2"] == 0.0


def test_saved_absent_reduction_is_kept():
    from house_config.house_thermal import normalize_house_thermal

    block = normalize_house_thermal({"absent_temp_reduction_c": 6.5}, label="p")
    assert block["absent_temp_reduction_c"] == 6.5


def test_absent_override_without_reduction_uses_schema_default():
    from optimizer.absent_mode import apply_thermal_absent_override

    out = apply_thermal_absent_override({"thermal": {"target_temp_c": 21.0}})
    assert out["thermal"]["target_temp_c"] == pytest.approx(18.5)


def test_profile_missing_geo_uses_schema_defaults():
    from house_config.profiles_store import _profile_geo_and_csv_fields

    fields = _profile_geo_and_csv_fields(
        {"id": "p", "netznutzung": {"area_id": "user_no_grid_fee"}}
    )
    assert (fields["latitude"], fields["longitude"]) == (48.2, 11.0)
    assert (fields["default_pv_tilt"], fields["default_pv_azimuth"]) == (25.0, 0.0)


def test_heat_storage_missing_keys_use_schema_defaults():
    from optimizer.thermal_coupled import normalize_heat_storage

    assert normalize_heat_storage({"volume_liters": 300}) == {
        "volume_liters": 300.0,
        "heat_loss_kw_per_k": 0.02,
        "setpoint_c": 45.0,
        "tolerance_c": 5.0,
    }

"""Fail-loud when Σ Verbraucher exceeds the Jahresverbrauch (baseload over-allocation)."""
from __future__ import annotations

import pytest

from house_config.baseload import (
    BASELOAD_MIN_FRACTION,
    TYPICAL_BASELOAD_KWH,
    BaseloadOverAllocatedError,
    allocation_diagnostics,
    baseload_allocation_message,
    compute_baseload_kwh,
    ensure_baseload_not_over_allocated,
)


def _generic(kwh: float) -> dict:
    return {"annual_kwh": kwh, "type": "generic"}


def test_ok_allocation_has_no_flags_or_suggestions():
    result = compute_baseload_kwh(13000, [_generic(11000)])
    assert result["over_allocated"] is False
    assert result["baseload_floored"] is False
    assert result["shortfall_kwh"] == 0.0
    assert result["suggested_annual_kwh"] is None
    assert result["suggested_consumer_reduction_kwh"] is None
    assert baseload_allocation_message(13000, result["consumer_kwh"]) is None


def test_over_allocated_when_consumers_exceed_annual():
    result = compute_baseload_kwh(4000, [_generic(3000), _generic(1500)])
    assert result["over_allocated"] is True
    assert result["shortfall_kwh"] == pytest.approx(500.0)
    # existing clamp semantics stay (baseload = floor) but are now flagged
    assert result["baseload_kwh"] == pytest.approx(4000 * BASELOAD_MIN_FRACTION)
    assert result["suggested_annual_kwh"] >= 4500 + TYPICAL_BASELOAD_KWH
    assert result["suggested_consumer_reduction_kwh"] == pytest.approx(
        4500 - (4000 - TYPICAL_BASELOAD_KWH)
    )


def test_boundary_sum_equals_annual_is_floored_not_over_allocated():
    diag = allocation_diagnostics(4000, 4000)
    assert diag["over_allocated"] is False
    assert diag["baseload_floored"] is True


def test_floor_boundary_exactly_at_minimum_is_ok():
    diag = allocation_diagnostics(4000, 4000 * (1 - BASELOAD_MIN_FRACTION))
    assert diag["over_allocated"] is False
    assert diag["baseload_floored"] is False


def test_floored_case_is_warning_not_error():
    profile = {
        "annual_kwh": 4000.0,
        "consumer_kwh": 3950.0,
        "baseload_kwh": 80.0,
        "baseload_min_kwh": 80.0,
        "id": "p",
    }
    ensure_baseload_not_over_allocated(profile)  # must not raise
    message = baseload_allocation_message(4000, 3950)
    assert message is not None and "Mindest-Grundlast" in message


def test_suggestion_makes_allocation_valid():
    diag = allocation_diagnostics(8000, 9000)
    assert diag["over_allocated"] is True
    fixed = allocation_diagnostics(diag["suggested_annual_kwh"], 9000)
    assert fixed["over_allocated"] is False
    assert fixed["baseload_floored"] is False


def test_message_names_both_remedies_and_a_suggestion():
    message = baseload_allocation_message(8000, 9000, profile_label="Haus A")
    assert message is not None
    assert "Haus A" in message
    assert "reduzieren" in message
    assert "erhöhen" in message
    assert "Vorschlag" in message
    assert f"{allocation_diagnostics(8000, 9000)['suggested_annual_kwh']:.0f}" in message


def test_ensure_raises_with_context_and_suggestion():
    profile = {
        "annual_kwh": 8000.0,
        "consumer_kwh": 9000.0,
        "baseload_kwh": 160.0,
        "baseload_min_kwh": 160.0,
        "label": "Haus A",
        "id": "a",
    }
    with pytest.raises(BaseloadOverAllocatedError, match="cons_data-Generierung") as err:
        ensure_baseload_not_over_allocated(profile, context="cons_data-Generierung")
    assert "Vorschlag" in str(err.value)
    assert isinstance(err.value, ValueError)


def test_ensure_rejects_unnormalized_profile():
    with pytest.raises(ValueError, match="annual_kwh/consumers"):
        ensure_baseload_not_over_allocated({"annual_kwh": 8000.0})


def _bind_house_paths(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "EARNIE_HOUSE_PROFILES_PATH", str(config_dir / "house_profiles.json")
    )
    return config_dir / "house_profiles.json"


def _profile(annual_kwh: float) -> dict:
    """One schedule-driven consumer: 1 kW × 10 h × 7 runs/week ≈ 3 650 kWh/a."""
    return {
        "id": "home",
        "label": "Home",
        "annual_kwh": annual_kwh,
        "consumers": [
            {
                "id": "pool",
                "label": "Pool",
                "type": "generic",
                "nominal_power_kw": 1.0,
                "schedule": {
                    "runs_per_week": 7,
                    "duration_h": 10.0,
                    "start_hour": 8,
                    "start_shift_h": 0.0,
                },
            }
        ],
    }


def test_configurator_save_blocks_over_allocation(tmp_path, monkeypatch):
    from ui.house_config_io import upsert_house_profile

    path = _bind_house_paths(tmp_path, monkeypatch)
    with pytest.raises(BaseloadOverAllocatedError, match="Vorschlag"):
        upsert_house_profile(_profile(annual_kwh=3000.0))
    assert not path.exists()


def test_configurator_save_accepts_valid_allocation(tmp_path, monkeypatch):
    from ui.house_config_io import upsert_house_profile

    path = _bind_house_paths(tmp_path, monkeypatch)
    upsert_house_profile(_profile(annual_kwh=8000.0))
    assert path.exists()


# --- context independence (Weg 1 + lazy): same profile -> same baseload / fingerprint ---


def _thermal_profile_raw() -> dict:
    return {
        "id": "home",
        "label": "Home",
        "annual_kwh": 9000.0,
        "latitude": 47.4,
        "longitude": 9.7,
        "timezone_name": "Europe/Vienna",
        "consumers": [
            {
                "id": "waermepumpe",
                "label": "Waermepumpe",
                "type": "thermal_annual",
                "nominal_power_kw": 1.9,
                "living_area_m2": 150.0,
                "building_class": 2,
                "heat_pump_type": "erde",
                "persons": 2,
                "hwb_kwh_m2": 40.0,
            },
            {
                "id": "swimspa",
                "label": "SwimSpa",
                "type": "thermal_rc",
                "nominal_power_kw": 2.8,
                "thermal_rc": {
                    "water_volume_liters": 5900.0,
                    "setpoint_c": 35.0,
                    "tolerance_c": 1.5,
                    "heat_loss_kw_per_k": 0.02,
                    "heating_efficiency": 0.99,
                },
            },
        ],
    }


def test_normalization_does_not_derive_baseload_or_touch_weather(monkeypatch):
    """Config.__init__ only normalizes: no Open-Meteo access, no baseload fields."""
    from house_config import baseload
    from house_config.profiles_store import normalize_house_profiles_document

    def _boom(*_args, **_kwargs):
        raise AssertionError("weather accessed during normalization")

    monkeypatch.setattr(baseload, "consumer_annual_kwh", _boom)
    profile = normalize_house_profiles_document({"profiles": [_thermal_profile_raw()]})[
        "profiles"
    ]["home"]
    for key in ("baseload_kwh", "consumer_kwh", "baseload_min_kwh"):
        assert key not in profile


def test_baseload_resolves_lazily_and_is_idempotent(monkeypatch):
    from house_config.baseload import profile_baseload_kwh, profile_consumer_kwh
    from house_config.profiles_store import normalize_house_profiles_document
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)
    profile = normalize_house_profiles_document({"profiles": [_thermal_profile_raw()]})[
        "profiles"
    ]["home"]
    first = profile_baseload_kwh(profile)
    consumers = profile_consumer_kwh(profile)
    assert first == pytest.approx(
        max(9000.0 - consumers, 9000.0 * BASELOAD_MIN_FRACTION)
    )
    assert profile_baseload_kwh(profile) == first


def test_weather_consumer_before_config_ready_fails_loud(monkeypatch):
    """No silent flat/legacy estimate when Config does not exist yet."""
    import sys

    from house_config.baseload import consumer_annual_kwh

    fake_config = type(sys)("config")
    fake_config.CONFIG = None
    monkeypatch.setitem(sys.modules, "config", fake_config)
    consumer = {
        "id": "waermepumpe",
        "type": "thermal_annual",
        "nominal_power_kw": 1.9,
        "latitude": 47.4,
        "longitude": 9.7,
        "living_area_m2": 150.0,
        "building_class": 2,
    }
    with pytest.raises(RuntimeError, match="vor dem Config-Aufbau"):
        consumer_annual_kwh(consumer)
    rc = {
        "id": "swimspa",
        "type": "thermal_rc",
        "thermal_rc": {"latitude": 47.4, "longitude": 9.7},
    }
    with pytest.raises(RuntimeError, match="vor dem Config-Aufbau"):
        consumer_annual_kwh(rc)


def test_fingerprint_ignores_derived_baseload_fields():
    from data.cons_data_house_profile import house_profile_cons_data_fingerprint

    base = {
        "id": "home",
        "annual_kwh": 9000.0,
        "consumers": [{"id": "x", "type": "generic", "annual_kwh": 100.0}],
    }
    with_derived = {
        **base,
        "baseload_kwh": 1.0,
        "consumer_kwh": 2.0,
        "baseload_min_kwh": 3.0,
    }
    assert house_profile_cons_data_fingerprint(
        base, pv_kwp=5.0
    ) == house_profile_cons_data_fingerprint(with_derived, pv_kwp=5.0)


def test_fingerprint_changes_with_inputs_and_climate_reference_year(monkeypatch):
    from data import open_meteo_solar_archive as archive
    from data.cons_data_house_profile import house_profile_cons_data_fingerprint

    profile = {"id": "home", "annual_kwh": 9000.0, "consumers": []}
    monkeypatch.setattr(archive, "last_full_archive_year", lambda **_kw: 2025)
    fp_2025 = house_profile_cons_data_fingerprint(profile, pv_kwp=5.0)
    assert fp_2025 != house_profile_cons_data_fingerprint(
        {**profile, "annual_kwh": 9100.0}, pv_kwp=5.0
    )
    monkeypatch.setattr(archive, "last_full_archive_year", lambda **_kw: 2026)
    assert fp_2025 != house_profile_cons_data_fingerprint(profile, pv_kwp=5.0)


def test_fingerprint_changes_with_synthesis_version(monkeypatch):
    from data import cons_data_house_profile as module

    profile = {"id": "home", "annual_kwh": 9000.0, "consumers": []}
    before = module.house_profile_cons_data_fingerprint(profile, pv_kwp=5.0)
    monkeypatch.setattr(module, "CONS_DATA_SYNTHESIS_VERSION", module.CONS_DATA_SYNTHESIS_VERSION + 1)
    assert module.house_profile_cons_data_fingerprint(profile, pv_kwp=5.0) != before

"""SUSI P2: solar and internal gains in the house RC, H re-calibration, HWB area basis."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from house_config.house_gains import (
    GROSS_TO_LIVING_AREA_FACTOR,
    hwb_reference_area_m2,
    internal_gain_descriptor,
    normalize_consumer_gain_factor,
    normalize_solar_gains,
    suggested_window_areas_m2,
)
from optimizer.thermal_house import (
    annual_space_heat_target_kwh,
    calibrate_house_heat_loss_with_gains,
    house_year_result,
    ideal_space_heat_kwh,
)


def _hourly_year(year: int = 2025) -> pd.Series:
    """Synthetic hourly temperature: seasonal sine plus a daily swing."""
    index = pd.date_range(f"{year}-01-01", periods=8760, freq="h")
    values = [
        8.0
        - 10.0 * math.cos(2 * math.pi * (i / 24.0 - 15) / 365.0)
        + 3.0 * math.sin(2 * math.pi * ((i % 24) - 9) / 24.0)
        for i in range(8760)
    ]
    return pd.Series(values, index=index)


def _solar_gain(index: pd.DatetimeIndex, peak_kw: float) -> pd.Series:
    values = [peak_kw * max(0.0, math.sin(math.pi * ((ts.hour - 6) / 12.0))) for ts in index]
    return pd.Series(values, index=index)


_BASE = dict(
    living_area_m2=140.0,
    building_class=3,
    heat_efficiency=3.5,
    heat_electric=True,
    persons=2,
    latitude=47.4,
    longitude=9.7,
    target_temp_c=21.0,
    heating_limit_c=15.0,
    hp_electric_kw=3.0,
    hwb_kwh_m2=60.0,
)


def test_hwb_refers_to_gross_floor_area():
    assert hwb_reference_area_m2({"living_area_m2": 100.0}) == pytest.approx(125.0)
    assert hwb_reference_area_m2({"living_area_m2": 100.0, "gross_floor_area_m2": 140.0}) == 140.0
    assert annual_space_heat_target_kwh(
        living_area_m2=100.0, building_class=3, hwb_kwh_m2=50.0
    ) == pytest.approx(100.0 * GROSS_TO_LIVING_AREA_FACTOR * 50.0)


def test_window_suggestion_follows_the_susi_cuboid():
    windows = suggested_window_areas_m2(140.0)
    # BGF 175 m², 2 storeys: footprint 87.5 m², sides 7.64 / 11.46 m, façade height 5.2 m.
    assert windows["s"] == pytest.approx(12.0, abs=0.5)
    assert windows["n"] == pytest.approx(3.5, abs=0.5)
    assert windows["e"] == windows["w"] == pytest.approx(4.0, abs=0.5)
    assert windows["s"] > windows["e"] > windows["n"]


def test_solar_block_defaults_and_validation():
    block = normalize_solar_gains(None, label="t")
    assert block == {
        "enabled": False,
        "window_area_m2": {"s": 0.0, "e": 0.0, "w": 0.0, "n": 0.0},
        "g_value": 0.6,
        "frame_shading_factor": 0.5,
    }
    with pytest.raises(ValueError, match="unbekannte Richtung"):
        normalize_solar_gains({"window_area_m2": {"sw": 3.0}}, label="t")
    with pytest.raises(ValueError, match="g_value"):
        normalize_solar_gains({"g_value": 1.5}, label="t")


def test_consumer_gain_factor_defaults_and_heating_guard():
    assert normalize_consumer_gain_factor(None, consumer_type="generic", label="t") == 0.8
    assert normalize_consumer_gain_factor(None, consumer_type="ev", label="t") == 0.0
    assert (
        normalize_consumer_gain_factor(
            None, consumer_type="generic", label="t", consumer_id="pool_filter"
        )
        == 0.0
    )
    with pytest.raises(ValueError, match="Heizungs-Verbraucher"):
        normalize_consumer_gain_factor(0.5, consumer_type="thermal_annual", label="t")
    with pytest.raises(ValueError, match="zwischen 0 und 1"):
        normalize_consumer_gain_factor(1.2, consumer_type="generic", label="t")


def test_calibration_with_gains_hits_the_hwb_and_raises_h():
    ambient = list(_hourly_year())
    target = 9000.0
    no_gain = calibrate_house_heat_loss_with_gains(
        target, ambient, [0.0] * 8760, capacity_kwh_per_k=12.6, target_temp_c=21.0, start_h=0.1
    )
    gains = [0.4] * 8760
    with_gain = calibrate_house_heat_loss_with_gains(
        target, ambient, gains, capacity_kwh_per_k=12.6, target_temp_c=21.0, start_h=0.1
    )
    heat = ideal_space_heat_kwh(
        with_gain, ambient, gains, capacity_kwh_per_k=12.6, target_temp_c=21.0
    )
    assert heat == pytest.approx(target, rel=0.005)
    # The HWB is net of gains: the envelope must lose more to need the same heat.
    assert with_gain > no_gain * 1.1


def test_year_sim_keeps_annual_heat_and_reports_calibrated_h():
    temps = _hourly_year()
    plain = house_year_result(**_BASE, hourly_temperature_c=temps)
    gains = internal_gain_descriptor(annual_kwh=5000.0, baseload_factor=0.8, consumers=[])
    with_gains = house_year_result(**_BASE, hourly_temperature_c=temps, internal_gains=gains)
    assert with_gains.house_heat_loss_kw_per_k > plain.house_heat_loss_kw_per_k
    # Both runs deliver about HWB × BGF of space heat (bang-bang overshoot aside).
    target = annual_space_heat_target_kwh(
        living_area_m2=140.0, building_class=3, hwb_kwh_m2=60.0
    )
    for result in (plain, with_gains):
        assert result.annual_space_heat_kwh == pytest.approx(target, rel=0.1)


def test_solar_gains_shift_heat_out_of_sunny_hours():
    temps = _hourly_year()
    solar_block = {
        "enabled": True,
        "window_area_m2": {"s": 12.0, "e": 4.0, "w": 4.0, "n": 3.5},
        "g_value": 0.6,
        "frame_shading_factor": 0.5,
    }
    plain = house_year_result(**_BASE, hourly_temperature_c=temps)
    sunny = house_year_result(
        **_BASE,
        hourly_temperature_c=temps,
        solar_gains=solar_block,
        hourly_solar_gain_kw=_solar_gain(temps.index, 1.5),
    )
    assert sunny.house_heat_loss_kw_per_k > plain.house_heat_loss_kw_per_k
    # Winter needs more heat with the steeper H, the sunny transition season and summer less.
    winter_plain = sum(plain.daily_electric_kwh[:59])
    winter_sunny = sum(sunny.daily_electric_kwh[:59])
    summer_plain = sum(plain.daily_electric_kwh[120:270])
    summer_sunny = sum(sunny.daily_electric_kwh[120:270])
    assert winter_sunny > winter_plain
    assert summer_sunny < summer_plain


def test_solar_gains_without_window_irradiance_fail_loud():
    with pytest.raises(ValueError, match="Fenster-Einstrahlung"):
        house_year_result(
            **_BASE,
            hourly_temperature_c=_hourly_year(),
            solar_gains={
                "enabled": True,
                "window_area_m2": {"s": 10.0, "e": 0.0, "w": 0.0, "n": 0.0},
                "g_value": 0.6,
                "frame_shading_factor": 0.5,
            },
        )


def test_grundlast_gain_solves_the_fixed_point_with_the_own_draw():
    temps = _hourly_year()
    small = internal_gain_descriptor(annual_kwh=4000.0, baseload_factor=0.8, consumers=[])
    large = internal_gain_descriptor(annual_kwh=9000.0, baseload_factor=0.8, consumers=[])
    a = house_year_result(**_BASE, hourly_temperature_c=temps, internal_gains=small)
    b = house_year_result(**_BASE, hourly_temperature_c=temps, internal_gains=large)
    # More household electricity → more internal gains → a steeper calibrated H.
    assert b.house_heat_loss_kw_per_k > a.house_heat_loss_kw_per_k


def test_variant_uses_the_grundlast_of_the_installed_system():
    temps = _hourly_year()
    gains = internal_gain_descriptor(annual_kwh=6000.0, baseload_factor=0.8, consumers=[])
    gas_kwargs = {**_BASE, "heat_efficiency": 0.9, "heat_electric": False}
    own = house_year_result(**gas_kwargs, hourly_temperature_c=temps, internal_gains=gains)
    pinned = house_year_result(
        **gas_kwargs,
        hourly_temperature_c=temps,
        internal_gains={
            **gains,
            "reference_heating": {
                "heat_efficiency": 3.5,
                "heat_electric": True,
                "heat_storage": None,
                "hp_electric_kw": 3.0,
            },
        },
    )
    # A gas house on its own counts the whole Jahresverbrauch as Grundlast; pinned to the
    # installed heat pump, the pump's draw is not household heat → fewer gains, flatter H.
    assert pinned.house_heat_loss_kw_per_k < own.house_heat_loss_kw_per_k


def test_live_house_plan_heats_less_with_gains(monkeypatch):
    import optimizer.thermal_parameters as tp
    from optimizer.thermal_live_house import plan_live_house_horizon
    from optimizer.thermal_parameters import SOURCE_OVERRIDE, ThermalParameters

    monkeypatch.setattr(
        tp,
        "house_thermal_parameters",
        lambda *_a, **_k: ThermalParameters(2025, 3000.0, 0.2, SOURCE_OVERRIDE),
    )

    consumer = {
        "id": "wp",
        "type": "thermal_annual",
        "nominal_power_kw": 3.0,
        "thermal": {
            "living_area_m2": 140.0,
            "building_class": 3,
            "hwb_kwh_m2": 60.0,
            "target_temp_c": 21.0,
            "heating_limit_c": 15.0,
            "house_heat_loss_kw_per_k": 0.2,
            "persons": 2,
            "latitude": 47.4,
            "longitude": 9.7,
            "heat_source": {"type": "heat_pump", "heat_pump_type": "luft"},
        },
    }
    ambient = [0.0] * 24
    profile = {"latitude": 47.4, "longitude": 9.7, "timezone_name": "Europe/Vienna"}
    plain = plan_live_house_horizon(consumer, house_profile=profile, ambient_forecast_c=ambient)
    warm = plan_live_house_horizon(
        consumer,
        house_profile=profile,
        ambient_forecast_c=ambient,
        gain_kw_by_hour=[1.5] * 24,
    )
    assert sum(warm.electric_by_hour) < sum(plain.electric_by_hour)


def test_loader_attaches_gain_inputs_and_round_trips_the_new_fields():
    from house_config.heating_systems import heating_systems_by_id
    from house_config.profiles_store import _serialize_profile, normalize_house_profiles_document

    catalog = heating_systems_by_id(
        {
            "heating_systems": [
                {
                    "id": "heating_home",
                    "heat_source": {"type": "heat_pump", "heat_pump_type": "luft"},
                    "heating_power_kw": 7.0,
                }
            ]
        }
    )
    raw = {
        "profiles": [
            {
                "id": "home",
                "label": "Home",
                "annual_kwh": 9000.0,
                "latitude": 47.4,
                "longitude": 9.7,
                "netznutzung": {"area_id": "user_no_grid_fee"},
                "heating_enabled": True,
                "baseload_internal_gain_factor": 0.7,
                "thermal": {
                    "living_area_m2": 140.0,
                    "gross_floor_area_m2": 180.0,
                    "solar_gains": {"enabled": True, "window_area_m2": {"s": 10.0}},
                },
                "consumers": [
                    {"id": "herd", "type": "generic", "annual_kwh": 500.0},
                    {"id": "pool_filter", "type": "generic", "annual_kwh": 300.0},
                    {"id": "wp", "type": "thermal_annual", "heating_system_id": "heating_home"},
                ],
            }
        ]
    }
    doc = normalize_house_profiles_document(raw, heating_systems=catalog)
    profile = doc["profiles"]["home"]
    wp = next(c for c in profile["consumers"] if c["id"] == "wp")
    gains = wp["thermal"]["internal_gains"]
    assert gains["annual_kwh"] == 9000.0 and gains["baseload_factor"] == 0.7
    assert [c["id"] for c in gains["consumers"]] == ["herd", "pool_filter"]
    assert [c["internal_gain_factor"] for c in gains["consumers"]] == [0.8, 0.0]
    assert wp["thermal"]["gross_floor_area_m2"] == 180.0
    assert wp["thermal"]["solar_gains"]["window_area_m2"] == {"s": 10.0, "e": 0.0, "w": 0.0, "n": 0.0}
    out = _serialize_profile(profile)
    assert out["baseload_internal_gain_factor"] == 0.7
    assert out["thermal"]["gross_floor_area_m2"] == 180.0
    assert out["thermal"]["solar_gains"]["enabled"] is True
    assert "internal_gains" not in next(c for c in out["consumers"] if c["id"] == "wp")
    assert normalize_house_profiles_document({"profiles": [out]}, heating_systems=catalog)[
        "profiles"
    ]["home"] == profile


def test_migration_step_writes_explicit_defaults_and_keeps_stored_values():
    from runtime_store.migration.steps.house_gains import STEP

    docs = {
        "house_profiles.json": {
            "profiles": [
                {
                    "id": "a",
                    "thermal": {"living_area_m2": 140.0},
                    "consumers": [
                        {"id": "herd", "type": "generic"},
                        {"id": "pool_filter", "type": "generic"},
                        {"id": "ev", "type": "ev"},
                        {"id": "kuehl", "type": "generic", "internal_gain_factor": 0.3},
                    ],
                },
                {"id": "b", "baseload_internal_gain_factor": 0.5, "consumers": []},
            ]
        },
        "components.json": {
            "heating_systems": [
                {"id": "h", "parts": [{"id": "heating_rod", "type": "heating_rod"}]}
            ]
        },
    }
    assert STEP.detect(docs)
    result = STEP.apply(docs, {})
    a, b = result.docs["house_profiles.json"]["profiles"]
    assert a["baseload_internal_gain_factor"] == 0.8 and b["baseload_internal_gain_factor"] == 0.5
    assert [c["internal_gain_factor"] for c in a["consumers"]] == [0.8, 0.0, 0.0, 0.3]
    solar = a["thermal"]["solar_gains"]
    assert solar["enabled"] is False
    assert solar["window_area_m2"] == suggested_window_areas_m2(140.0)
    assert "solar_gains" not in b.get("thermal", {})
    part = result.docs["components.json"]["heating_systems"][0]["parts"][0]
    assert part["internal_gain_factor"] == 0.0
    assert set(result.changed_files) == {"house_profiles.json", "components.json"}
    assert not STEP.detect(result.docs)
    assert "internal_gain_factor" not in docs["house_profiles.json"]["profiles"][0]["consumers"][0]

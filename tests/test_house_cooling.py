"""Air conditioning as inverse heat source of the house RC (``cooling`` on thermal_annual)."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from house_config.house_cooling import cooling_consumer, normalize_cooling
from optimizer.thermal_house import cool_house_temp, house_year_result


def _hot_year(year: int = 2025) -> pd.Series:
    """Synthetic hourly temperature with hot summer afternoons (peak ~33 °C)."""
    index = pd.date_range(f"{year}-01-01", periods=8760, freq="h")
    values = [
        12.0
        - 12.0 * math.cos(2 * math.pi * (i / 24.0 - 15) / 365.0)
        + 6.0 * math.sin(2 * math.pi * ((i % 24) - 9) / 24.0)
        for i in range(8760)
    ]
    return pd.Series(values, index=index)


def _sun(index: pd.DatetimeIndex, peak_kw: float = 4.0) -> pd.Series:
    """Window gain: half-sine over the day, stronger in summer."""
    values = [
        peak_kw
        * (0.5 - 0.5 * math.cos(2 * math.pi * (ts.day_of_year - 15) / 365.0))
        * max(0.0, math.sin(math.pi * ((ts.hour - 6) / 12.0)))
        for ts in index
    ]
    return pd.Series(values, index=index)


_SOLAR = {"enabled": True, "window_area_m2": {"s": 10.0}, "g_value": 0.6, "frame_shading_factor": 0.5}


def _sunny(temps: pd.Series) -> dict:
    return {"hourly_temperature_c": temps, "solar_gains": _SOLAR, "hourly_solar_gain_kw": _sun(temps.index)}


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
_SPLIT = {"type": "split", "seer": 5.0, "cooling_power_kw": 3.5, "setpoint_c": 25.0}


def test_cooling_block_defaults_per_type_and_guards():
    split = normalize_cooling({"type": "split"}, label="t", heat_source=None)
    assert split == {"type": "split", "seer": 5.0, "cooling_power_kw": 3.5, "setpoint_c": 26.0}
    reversible = normalize_cooling(
        {"type": "heat_pump"}, label="t", heat_source={"type": "heat_pump"}
    )
    assert reversible["seer"] == 4.0
    with pytest.raises(ValueError, match="Wärmequelle ist aber 'gas'"):
        normalize_cooling({"type": "heat_pump"}, label="t", heat_source={"type": "gas"})
    with pytest.raises(ValueError, match="unbekannte Felder eer"):
        normalize_cooling({"type": "split", "eer": 3.0}, label="t", heat_source=None)
    with pytest.raises(ValueError, match="cooling.type 'fan' unbekannt"):
        normalize_cooling({"type": "fan"}, label="t", heat_source=None)
    with pytest.raises(ValueError, match="cooling_power_kw muss > 0"):
        normalize_cooling({"type": "split", "cooling_power_kw": 0}, label="t", heat_source=None)


def test_cool_house_temp_holds_the_setpoint_within_capacity():
    assert cool_house_temp(24.0, setpoint_c=26.0, cooling_power_kw=3.0, capacity_kwh_per_k=10.0) == (
        24.0,
        0.0,
    )
    temp, cold = cool_house_temp(27.0, setpoint_c=26.0, cooling_power_kw=30.0, capacity_kwh_per_k=10.0)
    assert (temp, cold) == pytest.approx((26.0, 10.0))
    # Undersized device: the house stays warmer than the setpoint.
    temp, cold = cool_house_temp(28.0, setpoint_c=26.0, cooling_power_kw=5.0, capacity_kwh_per_k=10.0)
    assert (temp, cold) == pytest.approx((27.5, 5.0))


def test_year_model_books_cooling_apart_from_the_heating():
    temps = _hot_year()
    plain = house_year_result(**_BASE, **_sunny(temps))
    cooled = house_year_result(**_BASE, **_sunny(temps), cooling=_SPLIT)
    assert plain.hourly_cooling_electric_kw == []
    assert len(cooled.hourly_cooling_electric_kw) == 8760
    cooling_kwh = sum(cooled.hourly_cooling_electric_kw)
    assert cooling_kwh > 10.0
    assert cooled.annual_cooling_kwh == pytest.approx(cooling_kwh * _SPLIT["seer"], rel=1e-6)
    # Cooling only in summer: January has none; the heating stays (almost) the same.
    assert sum(cooled.hourly_cooling_electric_kw[: 31 * 24]) == 0.0
    assert sum(cooled.daily_electric_kwh) == pytest.approx(sum(plain.daily_electric_kwh), rel=0.02)
    # Only hours above the setpoint are cooled; the house never exceeds it by much.
    assert max(cooled.hourly_house_temp_c) < max(plain.hourly_house_temp_c)


def test_cooling_only_run_books_no_heating():
    temps = _hot_year()
    cooled = house_year_result(**_BASE, **_sunny(temps), cooling=_SPLIT)
    only = house_year_result(**_BASE, **_sunny(temps), cooling=_SPLIT, heating_booked=False)
    assert sum(only.daily_electric_kwh) == 0.0 and sum(only.daily_fuel_kwh) == 0.0
    assert sum(only.hourly_cooling_electric_kw) == pytest.approx(
        sum(cooled.hourly_cooling_electric_kw), rel=1e-6
    )


def _catalog(source_type: str = "heat_pump"):
    from house_config.heating_systems import heating_systems_by_id

    source = {"type": source_type}
    if source_type == "heat_pump":
        source["heat_pump_type"] = "luft"
    return heating_systems_by_id(
        {"heating_systems": [{"id": "heating_home", "heat_source": source, "heating_power_kw": 7.0}]}
    )


def _raw_profile(*, cooling_enabled: bool, heating_enabled: bool = True, cooling=None) -> dict:
    wp = {"id": "wp", "type": "thermal_annual", "heating_system_id": "heating_home"}
    if cooling is not None:
        wp["cooling"] = cooling
    return {
        "id": "home",
        "label": "Home",
        "annual_kwh": 9000.0,
        "latitude": 47.4,
        "longitude": 9.7,
        "netznutzung": {"area_id": "user_no_grid_fee"},
        "heating_enabled": heating_enabled,
        "cooling_enabled": cooling_enabled,
        "thermal": {"living_area_m2": 140.0},
        "consumers": [wp],
    }


def test_loader_round_trips_cooling_and_finds_the_carrier_with_heating_off():
    from house_config.profiles_store import _serialize_profile, normalize_house_profiles_document

    raw = _raw_profile(cooling_enabled=True, heating_enabled=False, cooling={"type": "split"})
    profile = normalize_house_profiles_document({"profiles": [raw]}, heating_systems=_catalog())[
        "profiles"
    ]["home"]
    assert profile["cooling_enabled"] is True
    assert profile["consumers"] == []
    carrier = cooling_consumer(profile)
    assert carrier["id"] == "wp" and carrier["cooling"]["seer"] == 5.0
    # The parked heating consumer carries the gain inputs for the cooling run too.
    assert carrier["thermal"]["internal_gains"]["annual_kwh"] == 9000.0
    out = _serialize_profile(profile)
    assert out["cooling_enabled"] is True
    assert out["consumers"][0]["cooling"] == {
        "type": "split",
        "seer": 5.0,
        "cooling_power_kw": 3.5,
        "setpoint_c": 26.0,
    }
    again = normalize_house_profiles_document({"profiles": [out]}, heating_systems=_catalog())
    assert again["profiles"]["home"] == profile


def test_loader_fails_loud_on_inconsistent_cooling():
    from house_config.profiles_store import normalize_house_profiles_document

    with pytest.raises(ValueError, match="cooling_enabled ist true.*keine Klimaanlage"):
        normalize_house_profiles_document(
            {"profiles": [_raw_profile(cooling_enabled=True)]}, heating_systems=_catalog()
        )
    with pytest.raises(ValueError, match="Wärmequelle ist aber 'gas'"):
        normalize_house_profiles_document(
            {
                "profiles": [
                    _raw_profile(cooling_enabled=True, cooling={"type": "heat_pump"})
                ]
            },
            heating_systems=_catalog("gas"),
        )
    raw = _raw_profile(cooling_enabled=False)
    raw["consumers"].append({"id": "herd", "type": "generic", "cooling": {"type": "split"}})
    with pytest.raises(ValueError, match="cooling gehört an den Haus-Wärme-Verbraucher"):
        normalize_house_profiles_document({"profiles": [raw]}, heating_systems=_catalog())
    # Switch off: a stored device is kept and not used.
    off = normalize_house_profiles_document(
        {"profiles": [_raw_profile(cooling_enabled=False, cooling={"type": "split"})]},
        heating_systems=_catalog(),
    )["profiles"]["home"]
    assert cooling_consumer(off) is None


def test_baseload_takes_the_cooling_out():
    from house_config.baseload import compute_baseload_kwh

    result = compute_baseload_kwh(5000.0, [], cooling_kwh=400.0)
    assert result["consumer_kwh"] == 400.0
    assert result["baseload_kwh"] == 4600.0


def test_household_reference_excludes_the_cooling():
    from house_config.household_reference import household_comparison

    result = household_comparison(4000.0, 2, [], cooling_kwh=300.0)
    assert result["household_kwh"] == 3700.0
    assert result["excluded_labels"] == ["Klimaanlage"]


def test_overlay_adds_cooling_even_for_a_milp_heating(monkeypatch):
    from datetime import datetime

    from house_config.planning_flex_overlays import thermal_hourly_overlay

    profile = {
        "cooling_enabled": True,
        "heating_enabled": True,
        "consumers": [{"id": "wp", "type": "thermal_annual", "cooling": dict(_SPLIT)}],
    }
    year = [0.0] * 8760
    year[5000] = 1.25
    monkeypatch.setattr(
        "optimizer.house_cooling._reference_year_hourly_kw", lambda _c, _p: list(year)
    )
    monkeypatch.setattr(
        "data.consumption_profiles._modeled_hour_index", lambda slot: slot.hour + 4992
    )
    slots = [datetime(2026, 7, 28, h) for h in range(24)]
    overlay = thermal_hourly_overlay(profile, slots, milp_flex_thermal_ids={"wp"})
    assert overlay[8] == 1.25 and sum(overlay) == 1.25


def test_migration_step_removes_appliance_kind_and_lists_a_todo():
    from runtime_store.migration.steps.house_cooling import STEP

    docs = {
        "house_profiles.json": {
            "profiles": [
                {
                    "id": "a",
                    "consumers": [
                        {"id": "klima", "label": "Klima", "type": "generic",
                         "appliance_kind": "air_conditioner"},
                        {"id": "herd", "type": "generic"},
                    ],
                },
                {"id": "b", "cooling_enabled": False, "consumers": []},
            ]
        }
    }
    assert STEP.detect(docs)
    result = STEP.apply(docs, {})
    profiles = result.docs["house_profiles.json"]["profiles"]
    assert profiles[0]["cooling_enabled"] is False
    assert "appliance_kind" not in profiles[0]["consumers"][0]
    assert [t.step_id for t in result.manual_todos] == ["dm5.house_cooling"]
    assert "Klima" in result.manual_todos[0].text_de
    assert not STEP.detect(result.docs)
    assert result.changed_files == ("house_profiles.json",)

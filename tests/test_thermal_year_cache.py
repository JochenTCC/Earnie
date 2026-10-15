"""Year-model memo: hits equal fresh simulations, keys cover all inputs, copies are isolated."""
from __future__ import annotations

import pandas as pd
import pytest

from house_config.thermal_rc_profile import (
    _simulate_thermal_rc_year,
    thermal_rc_hourly_kw_and_temp_from_ambient,
)
from optimizer.thermal_house import _simulate_house_year, house_year_result
from optimizer.thermal_year_cache import (
    HOUSE_YEAR_CACHE,
    THERMAL_RC_YEAR_CACHE,
    YearModelCache,
    fingerprint_series,
)


def _house_kwargs(**overrides) -> dict:
    kwargs = {
        "living_area_m2": 100.0,
        "building_class": 3,
        "heat_pump_type": "luft",
        "persons": 2,
        "latitude": 48.2,
        "longitude": 11.0,
        "target_temp_c": 21.0,
        "heating_limit_c": 15.0,
        "hp_electric_kw": 3.0,
        "heat_storage": {
            "volume_liters": 800.0,
            "heat_loss_kw_per_k": 0.02,
            "setpoint_c": 45.0,
            "tolerance_c": 5.0,
        },
        "daily_temps": [2.0, 5.0, -1.0, 8.0],
        "daily_radiation_mj": [3.0, 6.0, 1.0, 9.0],
        "house_heat_loss_kw_per_k": 0.12,
    }
    kwargs.update(overrides)
    return kwargs


def _hourly_temps(start: str = "2025-01-01", offset_c: float = 0.0) -> pd.Series:
    index = pd.date_range(start, periods=72, freq="h", tz="Europe/Vienna")
    values = [float(h % 24) / 4.0 - 2.0 + offset_c for h in range(72)]
    return pd.Series(values, index=index)


def _rc_consumer(**overrides) -> dict:
    consumer = {
        "id": "pool",
        "type": "thermal_rc",
        "nominal_power_kw": 3.0,
        "thermal_rc": {
            "setpoint_c": 36.0,
            "tolerance_c": 1.0,
            "water_volume_liters": 1500.0,
            "heat_loss_kw_per_k": 0.05,
            "heating_efficiency": 1.0,
        },
    }
    consumer.update(overrides)
    return consumer


def test_house_hit_equals_fresh_simulation():
    first = house_year_result(**_house_kwargs())
    second = house_year_result(**_house_kwargs())

    assert second == first
    assert second == _simulate_house_year(**_house_kwargs())
    assert HOUSE_YEAR_CACHE.stats() == {"hits": 1, "misses": 1, "size": 1}


def test_house_hit_returns_isolated_copies():
    first = house_year_result(**_house_kwargs())
    expected = list(first.daily_electric_kwh)
    first.daily_electric_kwh[0] = -999.0
    first.hourly_house_temp_c.clear()

    second = house_year_result(**_house_kwargs())

    assert second.daily_electric_kwh == expected
    assert second.hourly_house_temp_c


@pytest.mark.parametrize(
    "overrides",
    [
        {"hp_electric_kw": 4.0},
        {"daily_temps": [2.0, 5.0, -1.0, 8.5]},
        {"heat_storage": None},
        {
            "heat_storage": {
                "volume_liters": 800.0,
                "heat_loss_kw_per_k": 0.02,
                "setpoint_c": 50.0,
                "tolerance_c": 5.0,
            }
        },
        {"start_house_temp_c": 20.0},
    ],
)
def test_house_changed_input_misses(overrides):
    house_year_result(**_house_kwargs())
    changed = house_year_result(**_house_kwargs(**overrides))

    assert HOUSE_YEAR_CACHE.stats()["misses"] == 2
    assert changed == _simulate_house_year(**_house_kwargs(**overrides))


def test_house_hourly_series_same_values_other_index_misses():
    base = _house_kwargs(daily_temps=None, daily_radiation_mj=None)
    house_year_result(**base, hourly_temperature_c=_hourly_temps("2025-01-01"))
    shifted = house_year_result(**base, hourly_temperature_c=_hourly_temps("2025-03-01"))

    assert HOUSE_YEAR_CACHE.stats()["misses"] == 2
    assert shifted == _simulate_house_year(
        **base, hourly_temperature_c=_hourly_temps("2025-03-01")
    )


def test_house_hourly_series_equal_content_hits():
    base = _house_kwargs(daily_temps=None, daily_radiation_mj=None)
    house_year_result(**base, hourly_temperature_c=_hourly_temps())
    house_year_result(**base, hourly_temperature_c=_hourly_temps())

    assert HOUSE_YEAR_CACHE.stats()["hits"] == 1


def test_thermal_rc_hit_equals_fresh_and_copies_are_isolated():
    ambient = [5.0, 4.0, 3.0, 10.0] * 6
    first_kw, first_temp = thermal_rc_hourly_kw_and_temp_from_ambient(_rc_consumer(), ambient)
    first_kw[0] = -1.0
    second = thermal_rc_hourly_kw_and_temp_from_ambient(_rc_consumer(), ambient)

    assert second == _simulate_thermal_rc_year(_rc_consumer(), ambient, start_temp_c=None)
    assert second[1] == first_temp
    assert THERMAL_RC_YEAR_CACHE.stats()["hits"] == 1


@pytest.mark.parametrize(
    "consumer_overrides, ambient_delta, start_temp_c",
    [
        ({"nominal_power_kw": 4.0}, 0.0, None),
        (
            {
                "thermal_rc": {
                    "setpoint_c": 37.0,
                    "tolerance_c": 1.0,
                    "water_volume_liters": 1500.0,
                    "heat_loss_kw_per_k": 0.05,
                    "heating_efficiency": 1.0,
                }
            },
            0.0,
            None,
        ),
        ({}, 0.5, None),
        ({}, 0.0, 35.0),
    ],
)
def test_thermal_rc_changed_input_misses(consumer_overrides, ambient_delta, start_temp_c):
    ambient = [5.0, 4.0, 3.0, 10.0] * 6
    thermal_rc_hourly_kw_and_temp_from_ambient(_rc_consumer(), ambient)
    changed_ambient = [a + ambient_delta for a in ambient]
    changed = thermal_rc_hourly_kw_and_temp_from_ambient(
        _rc_consumer(**consumer_overrides), changed_ambient, start_temp_c=start_temp_c
    )

    assert THERMAL_RC_YEAR_CACHE.stats()["misses"] == 2
    assert changed == _simulate_thermal_rc_year(
        _rc_consumer(**consumer_overrides), changed_ambient, start_temp_c=start_temp_c
    )


def test_lru_evicts_oldest_entry():
    cache = YearModelCache("test", maxsize=2)
    for key in ("a", "b", "c"):
        cache.get_or_compute(key, lambda k=key: [k], list)
    cache.get_or_compute("a", lambda: ["a-new"], list)

    assert len(cache) == 2
    assert cache.stats()["misses"] == 4


def test_fingerprint_rejects_unknown_type():
    with pytest.raises(TypeError):
        fingerprint_series({"not": "a series"})

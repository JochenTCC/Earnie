"""Regression: saving the house profile must keep the optional thermal_annual flex fields.

Port of the release-relevant part of main 9f325194 (the heating-rod ``parts`` exist on main only).
"""
from __future__ import annotations

from house_config.profiles_store import _normalize_consumer, _serialize_consumer


def _thermal_annual(**extra) -> dict:
    return {
        "id": "wp",
        "label": "Wärmepumpe",
        "type": "thermal_annual",
        "nominal_power_kw": 1.9,
        "thermal": {
            "target_temp_c": 21.5,
            "persons": 2,
            "heating_limit_c": 15.0,
        },
        **extra,
    }


def test_profile_save_keeps_thermal_flex_fields():
    raw = _thermal_annual(
        optimizer_flex=True,
        max_on_quarterhours=12,
        max_pulses_per_day=3,
        thermal_flex_window={"start_hour": 10, "end_hour": 16},
    )
    spec = _normalize_consumer(raw, 0, "home")
    out = _serialize_consumer(spec)
    assert out["optimizer_flex"] is True
    assert out["max_on_quarterhours"] == 12
    assert out["max_pulses_per_day"] == 3
    assert out["thermal_flex_window"] == {"start_hour": 10, "end_hour": 16}
    again = _normalize_consumer(out, 0, "home")
    for key in ("optimizer_flex", "max_on_quarterhours", "max_pulses_per_day", "thermal_flex_window"):
        assert again[key] == spec[key]
    assert again["thermal"] == spec["thermal"]


def test_profile_save_without_flex_fields_writes_none():
    out = _serialize_consumer(_normalize_consumer(_thermal_annual(), 0, "home"))
    for key in ("optimizer_flex", "max_on_quarterhours", "max_pulses_per_day", "thermal_flex_window"):
        assert key not in out

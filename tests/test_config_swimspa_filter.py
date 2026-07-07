"""Tests für swimspa_filter in config.json-Normalisierung."""
from __future__ import annotations

import config


def test_normalize_swimspa_filter_consumer():
    raw = {
        "id": "swimspa_filter",
        "name": "SwimSpa Filter",
        "chart_color_index": 1,
        "nominal_power_kw": 0.18,
        "daily_target_source": "loxone_remaining_hours",
        "loxone_target_hours_name": "Ernie_Swimspa_Filter_Sollstunden",
        "signal_type": "binary",
        "filter_schedule": {
            "enabled": True,
            "loxone": {
                "native_start_hour_name": "homie_bwa_spa_filter1hour",
                "native_duration_hours_name": "homie_bwa_spa_filter1durationhours",
            },
            "config_fallback": {
                "native_start_hour": 10,
                "native_duration_hours": 4.0,
            },
        },
    }
    consumer = config.Config._normalize_consumer(raw)
    assert consumer["daily_target_source"] == "loxone_remaining_hours"
    assert consumer["loxone_target_hours_name"] == "Ernie_Swimspa_Filter_Sollstunden"
    assert consumer["filter_schedule"]["enabled"] is True
    assert consumer["filter_schedule"]["loxone"]["native_start_hour_name"]

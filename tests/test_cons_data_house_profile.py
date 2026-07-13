# tests/test_cons_data_house_profile.py
"""Tests für Hausprofil-basierte cons_data-Synthese."""
from __future__ import annotations

from datetime import date, datetime

from data.cons_data_house_profile import (
    build_synthetic_dataframe_from_house_profile,
    consumer_labels_for_ids,
    hourly_kw_by_consumer_for_timestamps,
    hourly_total_kw_for_timestamps,
    total_kw_at_datetime,
)
import pytest


def _sample_profile() -> dict:
    return {
        "id": "test_home",
        "annual_kwh": 5000.0,
        "baseload_kwh": 3000.0,
        "consumers": [
            {
                "id": "swimspa",
                "label": "Swimspa",
                "type": "generic",
                "nominal_power_kw": 2.0,
                "annual_kwh": 500.0,
                "schedule": {
                    "runs_per_week": 5,
                    "duration_h": 2.0,
                    "start_hour": 12,
                    "start_shift_h": 0.0,
                },
            },
        ],
    }


def test_hourly_kw_by_consumer_for_timestamps_includes_baseload_and_consumer():
    profile = _sample_profile()
    timestamps = ["2025-03-01 12:00:00"]
    by_consumer = hourly_kw_by_consumer_for_timestamps(profile, timestamps)
    assert "swimspa" in by_consumer
    assert "baseload" in by_consumer
    assert by_consumer["swimspa"][0] > 0.0
    assert by_consumer["baseload"][0] > 0.0


def test_total_kw_at_datetime_sums_baseload_and_consumer():
    profile = _sample_profile()
    value = total_kw_at_datetime(profile, datetime(2025, 3, 1, 12, 0, 0))
    assert value > float(profile["baseload_kwh"]) / 8760.0


def test_hourly_total_kw_for_timestamps_aligns_with_synthetic_df():
    profile = _sample_profile()
    timestamps = ["2025-03-01 00:00:00", "2025-03-01 12:00:00"]
    values = hourly_total_kw_for_timestamps(profile, timestamps)
    df = build_synthetic_dataframe_from_house_profile(
        profile,
        start=date(2025, 3, 1),
        end=date(2025, 3, 1),
        kwp=5.0,
        source="synthetic",
        pv_kw_at_datetime=lambda _slot: 0.0,
    )
    assert values[0] == pytest.approx(float(df.iloc[0]["total_kw"]), abs=0.01)
    assert values[1] == pytest.approx(float(df.iloc[12]["total_kw"]), abs=0.01)


def test_build_synthetic_dataframe_from_house_profile_has_consumer_columns():
    df = build_synthetic_dataframe_from_house_profile(
        _sample_profile(),
        start=date(2025, 3, 1),
        end=date(2025, 3, 2),
        kwp=5.0,
        source="synthetic",
        pv_kw_at_datetime=lambda _slot: 0.0,
    )
    assert "swimspa_kw" in df.columns
    assert float(df["swimspa_kw"].sum()) > 0.0
    assert float(df["baseload_kw"].sum()) > 0.0


def test_consumer_labels_for_ids_uses_profile_labels(monkeypatch):
    monkeypatch.setattr(
        "data.cons_data_house_profile.resolve_runtime_house_profile",
        lambda: _sample_profile(),
    )
    monkeypatch.setattr(
        "data.cons_data_house_profile.config.get_flexible_consumers",
        lambda: [],
    )
    labels = consumer_labels_for_ids(["swimspa"])
    assert labels["swimspa"] == "Swimspa"

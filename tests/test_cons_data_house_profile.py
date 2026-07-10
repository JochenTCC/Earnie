# tests/test_cons_data_house_profile.py
"""Tests für Hausprofil-basierte cons_data-Synthese."""
from __future__ import annotations

from datetime import date

from data.cons_data_house_profile import (
    build_synthetic_dataframe_from_house_profile,
    consumer_labels_for_ids,
)


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


def test_build_synthetic_dataframe_from_house_profile_has_consumer_columns():
    df = build_synthetic_dataframe_from_house_profile(
        _sample_profile(),
        start=date(2025, 3, 1),
        end=date(2025, 3, 2),
        kwp=5.0,
        source="synthetic",
        pv_kw_for_hour=lambda hour, month, kwp: 0.0,
    )
    assert "swimspa_kw" in df.columns
    assert float(df["swimspa_kw"].sum()) > 0.0
    assert float(df["baseload_kw"].sum()) > 0.0


def test_consumer_labels_for_ids_uses_profile_labels(monkeypatch):
    monkeypatch.setattr(
        "data.cons_data_house_profile.resolve_runtime_house_profile",
        lambda: _sample_profile(),
    )
    labels = consumer_labels_for_ids(["swimspa"])
    assert labels["swimspa"] == "Swimspa"

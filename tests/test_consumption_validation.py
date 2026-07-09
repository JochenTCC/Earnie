# tests/test_consumption_validation.py
"""Tests für Ist-vs-Modell-Verbrauchsvergleich."""
from __future__ import annotations

from ui.consumption_validation_charts import csv_series_to_monthly_kwh, modeled_monthly_kwh


def test_csv_series_to_monthly_kwh():
    series = [
        ("2023-01-01 00:00:00", 1.0),
        ("2023-01-01 01:00:00", 2.0),
        ("2023-02-01 00:00:00", 3.0),
    ]
    monthly = csv_series_to_monthly_kwh(series)
    assert monthly["2023-01"] == 3.0
    assert monthly["2023-02"] == 3.0


def test_modeled_monthly_kwh_from_baseload():
    profile = {
        "annual_kwh": 48.0,
        "baseload_kwh": 48.0,
        "consumers": [],
    }
    monthly = modeled_monthly_kwh(profile, hours=48)
    assert sum(monthly.values()) == 48.0

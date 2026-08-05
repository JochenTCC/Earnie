"""Tests für kanonische CSV-Spalten in _load_flexible_consumer_hourly_profiles."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd

from data import profile_manager as pm


def _write_profile_csv(csv_path, column: str) -> None:
    pd.DataFrame(
        {
            "Month": [7],
            "Weekday": [1],
            "Hour": [10],
            column: [0.55],
        }
    ).to_csv(csv_path, sep=";", index=False)


def test_load_flex_profiles_reads_canonical_csv_column(tmp_path):
    csv_path = tmp_path / "flexible_consumer_profiles.csv"
    _write_profile_csv(csv_path, "ev")
    consumer = {"id": "ev", "name": "Smart"}
    target = datetime(2026, 7, 14, 10, 0)

    with patch.object(pm.config, "get_flexible_consumers", return_value=[consumer]):
        with patch.object(pm, "flexible_consumer_profiles_file", return_value=str(csv_path)):
            profiles = pm._load_flexible_consumer_hourly_profiles([target])

    assert profiles["ev"] == [0.55]


def test_load_flex_profiles_ignores_legacy_csv_column(tmp_path):
    csv_path = tmp_path / "flexible_consumer_profiles.csv"
    _write_profile_csv(csv_path, "eauto")
    consumer = {"id": "ev", "name": "Smart"}
    target = datetime(2026, 7, 14, 10, 0)

    with patch.object(pm.config, "get_flexible_consumers", return_value=[consumer]):
        with patch.object(pm, "flexible_consumer_profiles_file", return_value=str(csv_path)):
            profiles = pm._load_flexible_consumer_hourly_profiles([target])

    assert profiles["ev"] == [0.0]

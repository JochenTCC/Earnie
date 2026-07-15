"""Tests für legacy CSV-Spalten in _load_flexible_consumer_hourly_profiles."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd

from data import profile_manager as pm


def test_load_flex_profiles_reads_legacy_csv_column(tmp_path):
    csv_path = tmp_path / "flexible_consumer_profiles.csv"
    df = pd.DataFrame(
        {
            "Month": [7],
            "Weekday": [1],
            "Hour": [10],
            "eauto": [0.55],
        }
    )
    df.to_csv(csv_path, sep=";", index=False)

    consumer = {
        "id": "ev",
        "legacy_id": "eauto",
        "name": "Smart",
    }
    target = datetime(2026, 7, 14, 10, 0)

    with patch.object(pm.config, "get_flexible_consumers", return_value=[consumer]):
        with patch.object(pm, "flexible_consumer_profiles_file", return_value=str(csv_path)):
            profiles = pm._load_flexible_consumer_hourly_profiles([target])

    assert profiles["ev"] == [0.55]

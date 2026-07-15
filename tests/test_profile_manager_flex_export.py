"""Tests für flexible_consumer_profiles.csv-Export aus cons_data."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd

from data import profile_manager as pm


def test_flex_profile_export_uses_cons_data_labels_and_legacy_csv_columns():
    profile_df = pd.DataFrame(
        {
            "Total": [1.0],
            "BaseLoad": [0.5],
            "Smart": [0.55],
            "Month": [7],
            "Weekday": [1],
            "Hour": [10],
        }
    )
    consumers = [
        {"id": "ev", "legacy_id": "eauto", "name": "Smart"},
        {"id": "swimspa_filter", "name": "SwimSpa Filter", "optimizer_enabled": True},
    ]

    with patch(
        "data.cons_data_house_profile.expected_cons_data_consumer_ids",
        return_value=["ev"],
    ):
        with patch(
            "data.cons_data_house_profile.consumer_labels_for_ids",
            return_value={"ev": "Smart"},
        ):
            with patch.object(pm.config, "get_flexible_consumers", return_value=consumers):
                label_cols, rename = pm._flex_profile_export_spec(profile_df)

    assert label_cols == ["Smart"]
    assert rename == {"Smart": "eauto"}


def test_generate_consumption_profile_writes_legacy_flex_columns(tmp_path, monkeypatch):
    flex_path = tmp_path / "flexible_consumer_profiles.csv"
    cons_path = tmp_path / "consumption_profiles.csv"
    total_path = tmp_path / "total_consumption_profiles.csv"

    index = pd.date_range("2026-07-14 18:00:00", periods=3, freq="1h")
    cons_df = pd.DataFrame(
        {
            "total_kw": [1.0, 1.2, 0.9],
            "baseload_kw": [0.5, 0.6, 0.4],
            "pv_kw": [0.0, 0.0, 0.0],
            "ev_kw": [0.5, 0.6, 0.5],
        },
        index=index,
    )
    consumers = [
        {"id": "ev", "legacy_id": "eauto", "name": "Smart"},
        {"id": "swimspa_filter", "name": "SwimSpa Filter", "optimizer_enabled": True},
    ]

    monkeypatch.setattr(
        pm,
        "_load_profile_source_dataframe",
        lambda: pm._cons_data_to_profile_dataframe(cons_df),
    )
    monkeypatch.setattr(pm, "consumption_profiles_file", lambda: str(cons_path))
    monkeypatch.setattr(pm, "total_consumption_profiles_file", lambda: str(total_path))
    monkeypatch.setattr(pm, "flexible_consumer_profiles_file", lambda: str(flex_path))
    monkeypatch.setattr(pm.config, "get_flexible_consumers", lambda: consumers)
    monkeypatch.setattr(
        "data.cons_data_house_profile.expected_cons_data_consumer_ids",
        lambda: ["ev"],
    )

    assert pm.generate_consumption_profile() is True
    flex_df = pd.read_csv(flex_path, sep=";")
    assert "eauto" in flex_df.columns
    assert flex_df["eauto"].iloc[0] == 0.5

    profiles = pm._load_flexible_consumer_hourly_profiles(
        [datetime(2026, 7, 14, 18, 0)]
    )
    assert profiles["ev"] == [0.5]

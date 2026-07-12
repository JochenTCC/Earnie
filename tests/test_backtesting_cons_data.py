# tests/test_backtesting_cons_data.py
"""Tests für cons_data-Validierung und Backtesting-UI-Hilfen."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from data import cons_data_store
from ui.backtesting_cons_data import cons_data_ready
from ui.consumption_validation_charts import cons_data_monthly_kwh, cons_dataframe_to_series


def _sample_df() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=3, freq="h", name="timestamp")
    return pd.DataFrame(
        {
            "total_kw": [1.0, 2.0, 3.0],
            "baseload_kw": [1.0, 2.0, 3.0],
            "pv_kw": [0.0, 0.0, 0.0],
        },
        index=idx,
    )


def test_is_cons_data_populated_false_when_missing(tmp_path):
    path = tmp_path / "cons_data_hourly.csv"
    assert cons_data_store.is_cons_data_populated(str(path)) is False


def test_is_cons_data_populated_false_when_header_only(tmp_path):
    path = tmp_path / "cons_data_hourly.csv"
    path.write_text("timestamp;total_kw;baseload_kw;pv_kw;source\n", encoding="utf-8")
    assert cons_data_store.is_cons_data_populated(str(path)) is False


def _patch_config_flex_ids(monkeypatch, ids: list[str]) -> None:
    import config

    monkeypatch.setattr(
        config.CONFIG,
        "_raw_config",
        {"flexible_consumers": [{"id": consumer_id} for consumer_id in ids]},
    )


def test_is_cons_data_populated_true_with_rows(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    _patch_config_flex_ids(monkeypatch, [])
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    assert cons_data_store.is_cons_data_populated(str(path)) is True


def test_load_cons_data_meta_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    _patch_config_flex_ids(monkeypatch, ["swimspa"])
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    meta = cons_data_store.load_cons_data_meta(str(path))
    assert meta is not None
    assert meta["consumer_ids"] == ["swimspa"]


def test_cons_data_consumer_match_reason_matching(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    _patch_config_flex_ids(monkeypatch, ["eauto", "swimspa"])
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    assert cons_data_store.cons_data_consumer_match_reason(str(path)) is None


def test_cons_data_consumer_match_reason_mismatch(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    _patch_config_flex_ids(monkeypatch, ["eauto"])
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    _patch_config_flex_ids(monkeypatch, ["eauto", "swimspa"])
    assert cons_data_store.cons_data_consumer_match_reason(str(path)) == "id_mismatch"


def test_cons_data_consumer_match_reason_missing_meta(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    _patch_config_flex_ids(monkeypatch, [])
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    os.remove(str(path).replace(".csv", ".meta.json"))
    assert cons_data_store.cons_data_consumer_match_reason(str(path)) == "missing_meta"


def test_expected_ids_match_house_profile_synthesis(tmp_path, monkeypatch):
    """Greenfield: planning-flex subset must not shrink cons_data ID set."""
    from data.cons_data_house_profile import (
        build_synthetic_dataframe_from_house_profile,
        expected_cons_data_consumer_ids,
    )
    from datetime import date

    profile = {
        "id": "efh",
        "annual_kwh": 11000.0,
        "latitude": 47.4,
        "longitude": 9.7,
        "consumers": [
            {"id": "wp_heating", "type": "thermal_annual", "nominal_power_kw": 1.6},
            {"id": "ev", "type": "ev", "nominal_power_kw": 3.5},
            {
                "id": "herd_kochen",
                "type": "generic",
                "nominal_power_kw": 1.5,
                "schedule": {
                    "runs_per_week": 7,
                    "duration_h": 1.0,
                    "start_hour": 20,
                    "start_shift_h": 1.0,
                },
            },
        ],
    }
    import config

    monkeypatch.setattr(
        config.CONFIG,
        "_raw_config",
        {"flexible_consumers": []},
    )
    monkeypatch.setattr(
        "data.cons_data_house_profile.resolve_runtime_house_profile",
        lambda: profile,
    )

    expected = sorted(expected_cons_data_consumer_ids())
    assert expected == sorted(["ev", "herd_kochen", "wp_heating"])

    df = build_synthetic_dataframe_from_house_profile(
        profile,
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
        kwp=6.0,
        source="synthetic",
        pv_kw_for_hour=lambda _hour, _month, _kwp: 0.0,
    )
    path = tmp_path / "cons_data_hourly.csv"
    cons_data_store.save_cons_data(df, str(path), apply_retention=False)
    assert cons_data_store.cons_data_consumer_match_reason(str(path)) is None


def test_cons_dataframe_to_series():
    series = cons_dataframe_to_series(_sample_df())
    assert len(series) == 3
    assert series[0][1] == 1.0
    assert series[1][0].startswith("2024-01-01")


def test_cons_data_monthly_kwh():
    monthly = cons_data_monthly_kwh(_sample_df())
    assert monthly["2024-01"] == pytest.approx(6.0)


def test_cons_data_ready_delegates(monkeypatch):
    monkeypatch.setattr(
        "ui.backtesting_cons_data.cons_data_store.is_cons_data_populated",
        lambda: True,
    )
    assert cons_data_ready() is True

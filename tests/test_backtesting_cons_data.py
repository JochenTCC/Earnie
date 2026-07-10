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


def test_is_cons_data_populated_true_with_rows(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    monkeypatch.setattr(cons_data_store.config, "get_flexible_consumers", lambda: [])
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    assert cons_data_store.is_cons_data_populated(str(path)) is True


def test_load_cons_data_meta_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    monkeypatch.setattr(
        cons_data_store.config,
        "get_flexible_consumers",
        lambda: [{"id": "swimspa"}],
    )
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    meta = cons_data_store.load_cons_data_meta(str(path))
    assert meta is not None
    assert meta["consumer_ids"] == ["swimspa"]


def test_cons_data_consumer_match_reason_matching(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    monkeypatch.setattr(
        cons_data_store.config,
        "get_flexible_consumers",
        lambda: [{"id": "eauto"}, {"id": "swimspa"}],
    )
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    assert cons_data_store.cons_data_consumer_match_reason(str(path)) is None


def test_cons_data_consumer_match_reason_mismatch(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    monkeypatch.setattr(
        cons_data_store.config,
        "get_flexible_consumers",
        lambda: [{"id": "eauto"}],
    )
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    monkeypatch.setattr(
        cons_data_store.config,
        "get_flexible_consumers",
        lambda: [{"id": "eauto"}, {"id": "swimspa"}],
    )
    assert cons_data_store.cons_data_consumer_match_reason(str(path)) == "id_mismatch"


def test_cons_data_consumer_match_reason_missing_meta(tmp_path, monkeypatch):
    path = tmp_path / "cons_data_hourly.csv"
    monkeypatch.setattr(cons_data_store.config, "get_flexible_consumers", lambda: [])
    cons_data_store.save_cons_data(_sample_df(), str(path), apply_retention=False)
    os.remove(str(path).replace(".csv", ".meta.json"))
    assert cons_data_store.cons_data_consumer_match_reason(str(path)) == "missing_meta"


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

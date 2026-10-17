"""Coverage for cons_data_store retention, append, and live pending flush."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from data import cons_data_store as store


def _sample_df(days: int = 40) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=days * 24, freq="h", name="timestamp")
    return pd.DataFrame(
        {
            "total_kw": [1.0] * len(idx),
            "baseload_kw": [1.0] * len(idx),
            "pv_kw": [0.0] * len(idx),
            "source": [store.SOURCE_SYNTHETIC] * len(idx),
        },
        index=idx,
    )


def test_get_retention_months_invalid_falls_back(monkeypatch):
    monkeypatch.setattr(
        store.config,
        "get_scenario_explorer_conf",
        lambda: {"cons_data_retention_months": "nope"},
    )
    assert store.get_retention_months() == 24


def test_get_write_mode_daily(monkeypatch):
    monkeypatch.setattr(
        store.config,
        "get_scenario_explorer_conf",
        lambda: {"cons_data_write_mode": "daily"},
    )
    assert store.get_write_mode() == "daily"


def test_get_write_mode_unknown_defaults_hourly(monkeypatch):
    monkeypatch.setattr(
        store.config,
        "get_scenario_explorer_conf",
        lambda: {"cons_data_write_mode": "weekly"},
    )
    assert store.get_write_mode() == "hourly"


def test_trim_retention_keeps_last_months():
    df = _sample_df(40)
    trimmed = store.trim_retention(df, months=1)
    assert trimmed.index.min() >= df.index.max() - pd.DateOffset(months=1)
    assert len(trimmed) < len(df)


def test_trim_retention_unlimited():
    df = _sample_df(3)
    assert len(store.trim_retention(df, months=0)) == len(df)


def test_normalize_infers_baseload_when_zero(monkeypatch):
    monkeypatch.setattr(store, "_consumer_column_ids", lambda: ["ev"])
    idx = pd.date_range("2024-01-01", periods=1, freq="h", name="timestamp")
    raw = pd.DataFrame(
        {"total_kw": [3.0], "baseload_kw": [0.0], "pv_kw": [0.0], "ev_kw": [1.5]},
        index=idx,
    )
    out = store._normalize_cons_dataframe(raw)
    assert float(out.iloc[0]["baseload_kw"]) == pytest.approx(1.5)


def test_append_measured_hours_merges(tmp_path, monkeypatch):
    path = tmp_path / "cons_data.csv"
    monkeypatch.setattr(store, "_consumer_column_ids", lambda: [])
    store.save_cons_data(_sample_df(1).iloc[:2], str(path), apply_retention=False)
    row = store.build_hour_row_from_measurements(
        datetime(2024, 1, 1, 2), total_kw=2.5, pv_kw=0.1
    )
    merged = store.append_measured_hours([row], str(path))
    assert len(merged) == 3
    assert float(merged.loc[pd.Timestamp("2024-01-01 02:00:00"), "total_kw"]) == pytest.approx(
        2.5
    )


def test_append_measured_hours_requires_timestamp(tmp_path, monkeypatch):
    path = tmp_path / "cons_data.csv"
    monkeypatch.setattr(store, "_consumer_column_ids", lambda: [])
    with pytest.raises(ValueError, match="timestamp"):
        store.append_measured_hours(pd.DataFrame({"total_kw": [1.0]}), str(path))


def test_invalidate_cons_data_meta(tmp_path, monkeypatch):
    path = tmp_path / "cons_data.csv"
    monkeypatch.setattr(store, "_consumer_column_ids", lambda: [])
    store.save_cons_data(_sample_df(1).iloc[:1], str(path), apply_retention=False)
    assert store.invalidate_cons_data_meta(str(path)) is True
    assert store.load_cons_data_meta(str(path)) is None
    assert store.invalidate_cons_data_meta(str(path)) is False


def test_record_and_flush_hourly(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    cons = tmp_path / "cons_data.csv"
    monkeypatch.setattr(store, "PENDING_STATE_FILE", str(pending))
    monkeypatch.setattr(store, "get_output_path", lambda: str(cons))
    monkeypatch.setattr(store, "get_write_mode", lambda: "hourly")
    monkeypatch.setattr(store, "_consumer_column_ids", lambda: ["ev"])

    t0 = datetime(2024, 6, 1, 10, 5)
    t1 = datetime(2024, 6, 1, 10, 35)
    now = datetime(2024, 6, 1, 11, 5)
    store.record_live_sample(
        total_kw=2.0, pv_kwh_interval=0.1, flex_kw={"ev": 0.5}, sample_time=t0
    )
    store.record_live_sample(
        total_kw=4.0, pv_kwh_interval=0.2, flex_kw={"ev": 1.5}, sample_time=t1
    )
    written = store.flush_pending_samples(now)
    assert written == 1
    loaded = store.load_cons_data(str(cons))
    assert len(loaded) == 1
    assert float(loaded.iloc[0]["total_kw"]) == pytest.approx(3.0)
    assert float(loaded.iloc[0]["pv_kw"]) == pytest.approx(0.3)
    assert float(loaded.iloc[0]["ev_kw"]) == pytest.approx(1.0)


def test_record_live_sample_skips_none(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    monkeypatch.setattr(store, "PENDING_STATE_FILE", str(pending))
    store.record_live_sample(total_kw=None, pv_kwh_interval=0.1)
    assert store._load_pending_state()["samples"] == []


def test_flush_daily_skips_same_day(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    monkeypatch.setattr(store, "PENDING_STATE_FILE", str(pending))
    monkeypatch.setattr(store, "get_write_mode", lambda: "daily")
    monkeypatch.setattr(store, "_consumer_column_ids", lambda: [])
    store._save_pending_state(
        {
            "samples": [
                {
                    "ts": "2024-06-01T10:00",
                    "total_kw": 1.0,
                    "pv_kwh": 0.0,
                    "flex_kw": {},
                }
            ],
            "last_daily_flush": "2024-06-02",
        }
    )
    assert store.flush_pending_samples(datetime(2024, 6, 2, 12)) == 0

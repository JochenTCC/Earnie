"""Appending measured hours must not re-stamp synthetic rows with the current house profile.

Bug: every hourly flush wrote the current synthesis fingerprint into the meta, so synthetic
rows generated from an older house profile (dryer 2.5 kW instead of 1.0 kW) were never
reported as ``profile_mismatch`` and kept feeding the flex profiles.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from data import cons_data_house_profile as house_profile
from data import cons_data_store as store


def _synthetic_df(hours: int = 3) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=hours, freq="h", name="timestamp")
    return pd.DataFrame(
        {
            "total_kw": [1.0] * hours,
            "baseload_kw": [1.0] * hours,
            "pv_kw": [0.0] * hours,
            "source": [store.SOURCE_SYNTHETIC] * hours,
        },
        index=idx,
    )


@pytest.fixture
def fingerprint(monkeypatch):
    current = {"value": "fp-old"}
    monkeypatch.setattr(store, "_consumer_column_ids", lambda: [])
    monkeypatch.setattr(house_profile, "expected_cons_data_consumer_ids", lambda: [])
    monkeypatch.setattr(
        house_profile, "current_cons_data_synthesis_fingerprint", lambda: current["value"]
    )
    return current


def _measured_row(hour: int) -> dict:
    return store.build_hour_row_from_measurements(
        datetime(2024, 1, 1, hour), total_kw=2.0, pv_kw=0.0
    )


def test_measured_append_keeps_the_fingerprint_of_the_synthetic_rows(tmp_path, fingerprint):
    path = str(tmp_path / "cons_data.csv")
    store.save_cons_data(_synthetic_df(), path, apply_retention=False)
    fingerprint["value"] = "fp-new"

    store.append_measured_hours([_measured_row(3)], path)

    assert store.load_cons_data_meta(path)["house_profile_fingerprint"] == "fp-old"
    assert store.cons_data_consumer_match_reason(path) == "profile_mismatch"


def test_measured_only_data_takes_the_current_fingerprint(tmp_path, fingerprint):
    path = str(tmp_path / "cons_data.csv")
    store.append_measured_hours([_measured_row(0)], path)
    fingerprint["value"] = "fp-new"

    store.append_measured_hours([_measured_row(1)], path)

    assert store.load_cons_data_meta(path)["house_profile_fingerprint"] == "fp-new"
    assert store.cons_data_consumer_match_reason(path) is None


def test_synthetic_rows_without_meta_count_as_stale(tmp_path, fingerprint):
    path = str(tmp_path / "cons_data.csv")
    store.save_cons_data(_synthetic_df(), path, apply_retention=False)
    store.invalidate_cons_data_meta(path)

    store.append_measured_hours([_measured_row(3)], path)

    assert store.load_cons_data_meta(path)["house_profile_fingerprint"] is None
    assert store.cons_data_consumer_match_reason(path) == "profile_mismatch"

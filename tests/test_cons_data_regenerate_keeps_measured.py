"""Regenerating the consumption baseline rewrites synthetic hours and keeps measured ones."""
from __future__ import annotations

import pandas as pd
import pytest

from data import cons_data_house_profile as house_profile
from data import cons_data_store as store


def _frame(start: str, hours: int, *, total: float, source: str) -> pd.DataFrame:
    idx = pd.date_range(start, periods=hours, freq="h", name="timestamp")
    return pd.DataFrame(
        {
            "total_kw": [total] * hours,
            "baseload_kw": [total] * hours,
            "pv_kw": [0.0] * hours,
            "source": [source] * hours,
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
    monkeypatch.setattr(store, "get_retention_months", lambda: 0)
    return current


def _old_file(path: str) -> None:
    old = pd.concat(
        [
            _frame("2024-01-01 00:00", 4, total=2.5, source=store.SOURCE_SYNTHETIC),
            _frame("2024-01-01 04:00", 2, total=0.7, source=store.SOURCE_MEASURED),
        ]
    )
    store.save_cons_data(old, path, apply_retention=False)


def test_keep_measured_rows_prefers_measured_hours():
    synthetic = _frame("2024-01-01 00:00", 6, total=1.0, source=store.SOURCE_SYNTHETIC)
    existing = pd.concat(
        [
            _frame("2024-01-01 00:00", 4, total=2.5, source=store.SOURCE_SYNTHETIC),
            _frame("2024-01-01 04:00", 3, total=0.7, source=store.SOURCE_MEASURED),
        ]
    )
    merged = store.keep_measured_rows(synthetic, existing)
    assert len(merged) == 7
    assert list(merged["total_kw"].iloc[:4]) == [1.0] * 4
    assert list(merged["total_kw"].iloc[4:]) == [0.7] * 3
    assert set(merged["source"].iloc[4:]) == {store.SOURCE_MEASURED}


def test_generate_keeps_measured_hours_and_stamps_the_current_profile(
    tmp_path, monkeypatch, fingerprint
):
    from scripts import generate_cons_data as gcd

    path = str(tmp_path / "cons_data.csv")
    _old_file(path)
    fingerprint["value"] = "fp-new"
    assert store.cons_data_consumer_match_reason(path) == "profile_mismatch"
    monkeypatch.setattr(
        gcd,
        "build_synthetic",
        lambda *_a, **_k: _frame("2024-01-01 00:00", 6, total=1.0, source=store.SOURCE_SYNTHETIC),
    )

    gcd.generate(source="synthetic", output=path)

    stored = store.load_cons_data(path)
    assert list(stored["total_kw"].iloc[:4]) == [1.0] * 4
    assert list(stored["total_kw"].iloc[4:]) == [0.7] * 2
    assert list(stored["source"].iloc[4:]) == [store.SOURCE_MEASURED] * 2
    assert store.cons_data_consumer_match_reason(path) is None


def test_stale_baseline_reason_follows_the_house_profile(tmp_path, monkeypatch, fingerprint):
    from ui import cons_data_refresh

    path = str(tmp_path / "cons_data.csv")
    monkeypatch.setattr(store, "get_output_path", lambda: path)
    assert cons_data_refresh.stale_baseline_reason() is None  # no data yet
    _old_file(path)
    assert cons_data_refresh.stale_baseline_reason() is None
    fingerprint["value"] = "fp-new"
    assert cons_data_refresh.stale_baseline_reason() == "profile_mismatch"


def test_regenerate_baseline_also_rebuilds_the_profiles(monkeypatch):
    from data import profile_manager
    from scripts import generate_cons_data as gcd
    from ui import cons_data_refresh

    calls: list[str] = []
    monkeypatch.setattr(gcd, "generate", lambda **kw: calls.append(f"generate:{kw['source']}"))
    monkeypatch.setattr(
        profile_manager, "generate_consumption_profile", lambda: calls.append("profiles")
    )
    cons_data_refresh.regenerate_consumption_baseline()
    assert calls == ["generate:synthetic", "profiles"]

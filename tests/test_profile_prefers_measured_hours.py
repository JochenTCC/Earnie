"""The consumption profiles take measured hours over synthetic ones of the same slot.

Bug: ``generate_consumption_profile`` averaged measured and synthetic hours of the same
month/weekday/hour. After a baseline regeneration with a near-zero synthetic base load the
live base-load profile dropped to a mix (0.25 kW) far below the measured 0.6 kW.
"""
from __future__ import annotations

import pandas as pd
import pytest

from data import cons_data_store as store
from data import profile_manager as pm


def _rows(start: str, hours: int, *, base: float, source: str) -> pd.DataFrame:
    idx = pd.date_range(start, periods=hours, freq="h", name="timestamp")
    return pd.DataFrame(
        {
            "total_kw": [base + 1.0] * hours,
            "baseload_kw": [base] * hours,
            "pv_kw": [0.0] * hours,
            "source": [source] * hours,
        },
        index=idx,
    )


@pytest.fixture
def profile_files(tmp_path, monkeypatch):
    paths = {
        "base": tmp_path / "consumption_profiles.csv",
        "total": tmp_path / "total_consumption_profiles.csv",
    }
    monkeypatch.setattr(pm, "consumption_profiles_file", lambda: str(paths["base"]))
    monkeypatch.setattr(pm, "total_consumption_profiles_file", lambda: str(paths["total"]))
    monkeypatch.setattr(
        "data.cons_data_house_profile.expected_cons_data_consumer_ids", lambda: []
    )
    monkeypatch.setattr(pm, "_flex_profile_export_spec", lambda _df: ([], {}))
    return paths


def _profile(path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";").set_index(["Month", "Weekday", "Hour"])


def test_measured_hours_replace_synthetic_ones_of_the_same_slot(profile_files, monkeypatch):
    # Monday 2025-11-03 synthetic, Monday 2026-11-02 measured; Tuesday only synthetic.
    cons = pd.concat(
        [
            _rows("2025-11-03 00:00", 48, base=0.03, source=store.SOURCE_SYNTHETIC),
            _rows("2026-11-02 00:00", 24, base=0.6, source=store.SOURCE_MEASURED),
        ]
    )
    monkeypatch.setattr(store, "load_cons_data", lambda *_a, **_k: cons)

    pm.generate_consumption_profile()

    base = _profile(profile_files["base"])["Consumption"]
    assert base.loc[(11, 0, 10)] == pytest.approx(0.6)  # measured Monday wins
    assert base.loc[(11, 1, 10)] == pytest.approx(0.03)  # Tuesday: synthetic only
    total = _profile(profile_files["total"])["Consumption"]
    assert total.loc[(11, 0, 10)] == pytest.approx(1.6)


def test_several_measured_hours_of_a_slot_are_averaged(profile_files, monkeypatch):
    cons = pd.concat(
        [
            _rows("2026-11-02 00:00", 24, base=0.4, source=store.SOURCE_MEASURED),
            _rows("2026-11-09 00:00", 24, base=0.8, source=store.SOURCE_LOXONE),
            _rows("2025-11-10 00:00", 24, base=0.03, source=store.SOURCE_SYNTHETIC),
        ]
    )
    monkeypatch.setattr(store, "load_cons_data", lambda *_a, **_k: cons)

    pm.generate_consumption_profile()

    base = _profile(profile_files["base"])["Consumption"]
    assert base.loc[(11, 0, 5)] == pytest.approx(0.6)


FIXED_KW = 0.2  # known consumers without own meter (cooking, TV, ...) as the live overlay adds them


@pytest.fixture
def fixed_overlay(monkeypatch):
    """Live house profile with fixed consumers worth FIXED_KW in every hour."""
    from house_config import planning_flex_bridge

    profile = {"consumers": []}
    monkeypatch.setattr(
        pm.config, "get_resolved_runtime_settings", lambda: {"_house_profile": profile}
    )
    monkeypatch.setattr(
        planning_flex_bridge,
        "fixed_generic_hourly_overlay",
        lambda _profile, slots, **_k: [FIXED_KW] * len(slots),
    )
    monkeypatch.setattr(
        planning_flex_bridge, "thermal_hourly_overlay", lambda _p, slots, **_k: [0.0] * len(slots)
    )
    monkeypatch.setattr(planning_flex_bridge, "milp_flex_thermal_annual_ids", lambda _c: set())
    monkeypatch.setattr(pm.config, "get_flexible_consumers", lambda: [])
    monkeypatch.setattr(
        "optimizer.absent_mode.resolve_live_absent_skip_ids", lambda _profile: set()
    )
    return profile


def test_measured_base_load_drops_the_fixed_consumers_the_live_plan_adds(
    profile_files, fixed_overlay, monkeypatch
):
    """Measured base load holds the unmetered fixed consumers; the plan must count them once."""
    cons = pd.concat(
        [
            _rows("2025-11-04 00:00", 24, base=0.03, source=store.SOURCE_SYNTHETIC),
            _rows("2026-11-02 00:00", 24, base=0.6, source=store.SOURCE_MEASURED),
        ]
    )
    monkeypatch.setattr(store, "load_cons_data", lambda *_a, **_k: cons)

    pm.generate_consumption_profile()

    base = _profile(profile_files["base"])["Consumption"]
    assert base.loc[(11, 0, 10)] == pytest.approx(0.4)  # measured 0.6 minus fixed 0.2
    assert base.loc[(11, 1, 10)] == pytest.approx(0.03)  # synthetic rows hold no fixed load
    total = _profile(profile_files["total"])["Consumption"]
    assert total.loc[(11, 0, 10)] == pytest.approx(1.6)  # total stays as measured

    from datetime import datetime

    planned = pm._load_consumption_profile([datetime(2026, 11, 23, 10)])  # a Monday
    assert planned == [pytest.approx(0.6)]  # profile + live overlay = measured load


def test_peeling_never_makes_the_base_load_negative(profile_files, fixed_overlay, monkeypatch):
    cons = _rows("2026-11-02 00:00", 24, base=0.15, source=store.SOURCE_MEASURED)
    monkeypatch.setattr(store, "load_cons_data", lambda *_a, **_k: cons)

    pm.generate_consumption_profile()

    base = _profile(profile_files["base"])["Consumption"]
    assert base.loc[(11, 0, 10)] == pytest.approx(0.0)

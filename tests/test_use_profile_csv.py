"""Tests for use_profile_csv residual baseload behavior."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from data.consumption_profiles import build_modeled_hourly_kw_by_consumer
from house_config.consumption_csv import write_canonical_hourly_csv


def _hourly_csv(path: Path, hours: int, power: float) -> None:
    start = datetime(2023, 1, 1)
    rows = [
        ((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), power)
        for i in range(hours)
    ]
    write_canonical_hourly_csv(str(path), rows)


def test_meter_residual_holds_hourly_csv_on_qh_slots(tmp_path: Path) -> None:
    """Issue #24: hourly Gesamt-CSV must ZOH onto 15-min slots (not exact-ts miss)."""
    from house_config.planning_flex_overlays import meter_residual_baseload_kw

    total = tmp_path / "total.csv"
    day = datetime(2025, 3, 1)
    write_canonical_hourly_csv(
        str(total),
        [
            ((day + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S"), 1.0)
            for h in range(24)
        ],
    )
    slots = [day + timedelta(minutes=15 * i) for i in range(96)]
    residual, clipped = meter_residual_baseload_kw(
        {"total_profile_csv": str(total), "consumers": []},
        slots,
    )
    assert clipped == 0
    assert residual[:4] == [1.0, 1.0, 1.0, 1.0]
    assert sum(residual) * 0.25 == pytest.approx(24.0)


def test_residual_baseload_subtracts_instrumented_csv(tmp_path: Path) -> None:
    total = tmp_path / "total.csv"
    cons = tmp_path / "cons.csv"
    hours = 48
    _hourly_csv(total, hours, 5.0)
    _hourly_csv(cons, hours, 2.0)
    profile = {
        "baseload_kwh": 0.0,
        "total_profile_csv": str(total),
        "consumers": [
            {
                "id": "flex_a",
                "type": "generic",
                "nominal_power_kw": 1.0,
                "annual_kwh": 0.0,
                "profile_csv": str(cons),
                "use_profile_csv": True,
            },
            {
                "id": "synth_b",
                "type": "generic",
                "nominal_power_kw": 1.0,
                "annual_kwh": float(hours),
            },
        ],
    }
    by_c = build_modeled_hourly_kw_by_consumer(profile, hours=hours)
    assert by_c["flex_a"][0] == 2.0
    assert by_c["synth_b"][0] == pytest.approx(float(hours) / 8760.0)
    # Residual must subtract CSV + synthetic so the stack matches the meter.
    assert by_c["baseload"][0] == pytest.approx(5.0 - 2.0 - float(hours) / 8760.0)


def test_se_baseload_matches_hk_modell_metric(tmp_path: Path) -> None:
    """SE/cons_data Basislast = HK Modell metric (baseload_kwh/8760), not meter residual."""
    from data.cons_data_house_profile import hourly_kw_by_consumer_for_timestamps
    from ui.consumption_display.adapters import bundle_from_modeled_profile

    total = tmp_path / "total.csv"
    cons = tmp_path / "cons.csv"
    hours = 48
    _hourly_csv(total, hours, 5.0)
    _hourly_csv(cons, hours, 2.0)
    profile = {
        "id": "align_test",
        "baseload_kwh": 876.0,
        "total_profile_csv": str(total),
        "consumers": [
            {
                "id": "flex_a",
                "type": "generic",
                "nominal_power_kw": 1.0,
                "annual_kwh": 0.0,
                "profile_csv": str(cons),
                "use_profile_csv": True,
            },
            {
                "id": "synth_b",
                "type": "generic",
                "nominal_power_kw": 1.0,
                "annual_kwh": float(hours),
            },
        ],
    }
    hk_bundle = bundle_from_modeled_profile(profile, hours=8760)
    timestamps = [
        (datetime(2023, 1, 1) + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(hours)
    ]
    se = hourly_kw_by_consumer_for_timestamps(profile, timestamps)
    expected = 876.0 / 8760.0
    assert hk_bundle.baseload[0] == pytest.approx(expected)
    assert se["baseload"][0] == pytest.approx(expected)
    assert se["baseload"][0] == pytest.approx(hk_bundle.baseload[0])


def test_residual_aligns_consumer_csv_by_timestamp(tmp_path: Path) -> None:
    """Consumer CSV may start earlier; residual must match calendar hours."""
    total = tmp_path / "total.csv"
    cons = tmp_path / "cons.csv"
    # Total: 2023-06-01 .. 48h at 5 kW
    start_total = datetime(2023, 6, 1)
    write_canonical_hourly_csv(
        str(total),
        [
            ((start_total + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), 5.0)
            for i in range(48)
        ],
    )
    # Consumer: starts 30 days earlier; only overlapping hours are 2 kW
    start_cons = datetime(2023, 5, 1)
    cons_rows = []
    for i in range(24 * 60):
        ts = start_cons + timedelta(hours=i)
        kw = 2.0 if ts >= start_total else 9.0
        cons_rows.append((ts.strftime("%Y-%m-%d %H:%M:%S"), kw))
    write_canonical_hourly_csv(str(cons), cons_rows)
    from data.consumption_profiles import _csv_kw_lookup

    _csv_kw_lookup.cache_clear()
    profile = {
        "baseload_kwh": 0.0,
        "total_profile_csv": str(total),
        "consumers": [
            {
                "id": "flex_a",
                "type": "generic",
                "nominal_power_kw": 1.0,
                "annual_kwh": 0.0,
                "profile_csv": str(cons),
                "use_profile_csv": True,
            },
        ],
    }
    by_c = build_modeled_hourly_kw_by_consumer(profile, hours=48)
    assert by_c["flex_a"][0] == 2.0  # not 9.0 from early rows
    assert by_c["baseload"][0] == 3.0

    cons = tmp_path / "cons.csv"
    hours = 24
    _hourly_csv(cons, hours, 9.0)
    profile = {
        "baseload_kwh": float(hours),
        "consumers": [
            {
                "id": "flex_a",
                "type": "generic",
                "nominal_power_kw": 1.0,
                "annual_kwh": float(hours),
                "profile_csv": str(cons),
                "use_profile_csv": False,
            },
        ],
    }
    by_c = build_modeled_hourly_kw_by_consumer(profile, hours=hours)
    assert by_c["flex_a"][0] == 1.0  # synthetic annual, not CSV 9.0


def _fake_modeled_kw(consumer, _slot_dt, climate=None):
    del climate
    return {"wp": 1.0, "car": 0.5, "pool": 0.25, "herd": 0.125}[consumer["id"]]


def _residual_profile(total: Path) -> dict:
    day = datetime(2025, 1, 6)
    write_canonical_hourly_csv(
        str(total),
        [((day + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S"), 3.0) for h in range(24)],
    )
    return {
        "baseload_kwh": 0.0,
        "total_profile_csv": str(total),
        "consumers": [
            {"id": "wp", "type": "thermal_annual"},
            {"id": "car", "type": "ev"},
            {"id": "pool", "type": "thermal_rc"},
            {"id": "herd", "type": "generic", "annual_kwh": 1095.0},
        ],
    }


def test_meter_residual_peels_modeled_consumers_that_are_re_added(
    tmp_path: Path, monkeypatch
) -> None:
    """Path B: a modeled heat pump / MILP-flex EV without CSV leave the residual (no double count)."""
    from data import consumption_profiles
    from house_config.planning_flex_overlays import meter_residual_baseload_kw

    monkeypatch.setattr(consumption_profiles, "modeled_consumer_kw_at_datetime", _fake_modeled_kw)
    profile = _residual_profile(tmp_path / "total.csv")
    slots = [datetime(2025, 1, 6) + timedelta(hours=h) for h in range(24)]
    residual, clipped = meter_residual_baseload_kw(profile, slots, milp_flex_ids={"car"})
    # Non-flex thermal_rc and fixed generic without CSV are not stacked again: they stay inside.
    assert clipped == 0
    assert residual == [1.5] * 24


def test_profile_spec_path_b_keeps_meter_energy_with_modeled_heat_pump(
    tmp_path: Path, monkeypatch
) -> None:
    from data import consumption_profiles
    from house_config.profile_csv_policy import se_uses_meter_residual_baseload
    from simulation.matrix_builder import _profile_spec_baseload_kw

    monkeypatch.setattr(consumption_profiles, "modeled_consumer_kw_at_datetime", _fake_modeled_kw)
    profile = _residual_profile(tmp_path / "total.csv")
    profile["consumers"] = profile["consumers"][:1]
    assert se_uses_meter_residual_baseload(profile)
    slots = [datetime(2025, 1, 6) + timedelta(hours=h) for h in range(24)]
    baseload_kw, _clipped = _profile_spec_baseload_kw(profile, slots, None, None)
    # Residual 2.0 + heat pump overlay 1.0 = meter 3.0 (before: 3.0 + 1.0).
    assert baseload_kw == [3.0] * 24

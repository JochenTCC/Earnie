"""Tests for QH power-interval sampler and closed_interval means."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from runtime_store import power_interval_sampler as sampler
from runtime_store.slot_ist_powers import (
    IST_SOURCE_DECISION,
    IST_SOURCE_MEAN,
    closed_interval_usable,
    index_closed_intervals_by_start,
    resolve_ist_snapshot,
)


def _plant(pv=1.0, house=2.0, grid=0.5, battery=-0.5):
    return {"pv": pv, "house": house, "grid": grid, "battery": battery}


def test_tick_accumulate_and_finalize_mean(tmp_path: Path):
    state = tmp_path / "sampler.json"
    start = datetime(2026, 9, 14, 13, 0, 0)
    samples = [
        (start + timedelta(seconds=30), _plant(pv=2.0, battery=1.0)),
        (start + timedelta(seconds=60), _plant(pv=4.0, battery=-1.0)),
        (start + timedelta(seconds=90), _plant(pv=6.0, battery=-1.0)),
    ]
    for moment, plant in samples:
        assert sampler.tick(
            now=moment,
            force=True,
            state_path=str(state),
            read_plant=lambda p=plant: p,
            read_soc=lambda: 42.0,
            read_flex_chart=lambda: {"ev": 1.5},
        )

    closed = sampler.finalize_closed_interval(start, state_path=str(state))
    assert closed is not None
    assert closed["sample_count"] == 3
    assert closed["pv_kw"] == pytest.approx(4.0)
    assert closed["battery_kw"] == pytest.approx(-0.333, abs=0.001)
    assert closed["flex_kw"]["ev"] == pytest.approx(1.5)
    assert closed["pv_energy_kwh"] == pytest.approx(1.0)
    assert closed_interval_usable(closed)

    again = sampler.finalize_closed_interval(start, state_path=str(state))
    assert again is None


def test_note_decision_sample_counts(tmp_path: Path):
    state = tmp_path / "sampler.json"
    start = datetime(2026, 9, 14, 12, 45, 0)
    snap = {
        "pv_kw": 3.0,
        "grid_kw": 1.0,
        "battery_kw": -2.0,
        "house_kw": 2.0,
        "baseload_kw": 2.0,
        "flex_sum_kw": 0.0,
        "flex_kw": {},
    }
    sampler.note_decision_sample(
        snap, soc_percent=40.0, now=start + timedelta(seconds=5), state_path=str(state)
    )
    sampler.note_decision_sample(
        snap, soc_percent=41.0, now=start + timedelta(seconds=35), state_path=str(state)
    )
    sampler.note_decision_sample(
        snap, soc_percent=42.0, now=start + timedelta(seconds=65), state_path=str(state)
    )
    closed = sampler.finalize_closed_interval(start, state_path=str(state))
    assert closed is not None
    assert closed["sample_count"] == 3
    assert closed["soc_start_percent"] == 40.0
    assert closed["soc_end_percent"] == 42.0


def test_low_sample_count_not_usable():
    assert not closed_interval_usable({"sample_count": 2, "pv_kw": 1.0})
    assert closed_interval_usable({"sample_count": 3, "pv_kw": 1.0})


def test_resolve_ist_prefers_closed_interval():
    slot = datetime(2026, 9, 14, 13, 0, 0)
    plan = {
        "consumption_snapshot": {
            "pv_kw": 9.0,
            "grid_kw": 0.0,
            "battery_kw": 2.5,
            "house_kw": 1.0,
            "baseload_kw": 1.0,
            "flex_kw": {},
        }
    }
    closed = {
        "interval_start": "2026-09-14T13:00:00",
        "sample_count": 5,
        "pv_kw": 1.2,
        "grid_kw": 0.3,
        "battery_kw": -0.8,
        "house_kw": 2.0,
        "baseload_kw": 2.0,
        "flex_sum_kw": 0.0,
        "flex_kw": {},
    }
    indexed = index_closed_intervals_by_start([{"closed_interval": closed}])
    snap, source = resolve_ist_snapshot(slot, plan, indexed)
    assert source == IST_SOURCE_MEAN
    assert snap["battery_kw"] == pytest.approx(-0.8)
    assert snap["pv_kw"] == pytest.approx(1.2)


def test_resolve_ist_falls_back_to_decision_when_low_samples():
    slot = datetime(2026, 9, 14, 13, 0, 0)
    plan = {
        "consumption_snapshot": {
            "pv_kw": 9.0,
            "grid_kw": 0.0,
            "battery_kw": 2.5,
            "house_kw": 1.0,
            "baseload_kw": 1.0,
            "flex_kw": {},
            "flex_sum_kw": 0.0,
        }
    }
    closed = {
        "interval_start": "2026-09-14T13:00:00",
        "sample_count": 1,
        "pv_kw": 1.2,
        "battery_kw": -0.8,
        "grid_kw": 0.0,
        "house_kw": 1.0,
        "baseload_kw": 1.0,
        "flex_kw": {},
    }
    indexed = index_closed_intervals_by_start([{"closed_interval": closed}])
    snap, source = resolve_ist_snapshot(slot, plan, indexed)
    assert source == IST_SOURCE_DECISION
    assert snap["battery_kw"] == pytest.approx(2.5)


def test_finalize_overlays_counter_delta_when_anchored(tmp_path: Path):
    state = tmp_path / "sampler.json"
    start = datetime(2026, 9, 14, 14, 0, 0)
    readings = {
        "open": {
            "pv": {"total": 10.0},
            "grid": {"total": 100.0, "total_neg": 20.0},
        },
        "close": {
            "pv": {"total": 10.5},
            "grid": {"total": 100.25, "total_neg": 20.05},
        },
    }
    phase = {"n": 0}

    def read_energy():
        phase["n"] += 1
        return readings["open"] if phase["n"] == 1 else readings["close"]

    for offset in (30, 60, 90):
        assert sampler.tick(
            now=start + timedelta(seconds=offset),
            force=True,
            state_path=str(state),
            read_plant=lambda: _plant(pv=9.0, grid=9.0),
            read_soc=lambda: 50.0,
            read_flex_chart=lambda: {},
            read_energy=read_energy,
        )
    closed = sampler.finalize_closed_interval(
        start, state_path=str(state), read_energy=read_energy
    )
    assert closed is not None
    assert closed["ist_power_source"]["pv"] == "counter"
    assert closed["ist_power_source"]["grid"] == "counter"
    assert closed["ist_power_source"]["battery"] == "mean"
    assert closed["pv_kw"] == pytest.approx(2.0)
    assert closed["pv_energy_kwh"] == pytest.approx(0.5)
    # Δimport 0.25 − Δexport 0.05 = 0.20 kWh → 0.8 kW
    assert closed["grid_kw"] == pytest.approx(0.8)
    assert closed["battery_kw"] == pytest.approx(-0.5)


def _sample_grid(state: Path, start: datetime, grids, read_energy=None) -> None:
    for offset, grid in zip(range(30, 30 * (len(grids) + 1), 30), grids):
        assert sampler.tick(
            now=start + timedelta(seconds=offset),
            force=True,
            state_path=str(state),
            read_plant=lambda g=grid: _plant(grid=g),
            read_soc=lambda: 50.0,
            read_flex_chart=lambda: {},
            read_energy=read_energy,
        )


def _energy(open_grid: dict, close_grid: dict):
    calls = {"n": 0}

    def read_energy():
        calls["n"] += 1
        return {"grid": open_grid if calls["n"] == 1 else close_grid}

    return read_energy


def test_import_mean_is_not_offset_by_export_in_the_same_slot(tmp_path: Path):
    state = tmp_path / "sampler.json"
    start = datetime(2026, 11, 7, 18, 0, 0)
    _sample_grid(state, start, [3.0, -3.0, 3.0])
    closed = sampler.finalize_closed_interval(start, state_path=str(state))
    assert closed["grid_kw"] == pytest.approx(1.0)
    assert closed["grid_import_kw"] == pytest.approx(2.0)
    assert closed["grid_import_source"] == sampler.GRID_IMPORT_SOURCE_MEAN
    assert (closed["grid_import_start"], closed["grid_import_end"]) == (
        "2026-11-07T18:00:30",
        "2026-11-07T18:01:30",
    )


def test_import_counter_divides_by_the_real_window(tmp_path: Path):
    state = tmp_path / "sampler.json"
    start = datetime(2026, 11, 7, 18, 0, 0)
    read_energy = _energy({"total": 100.0, "total_neg": 5.0}, {"total": 100.29, "total_neg": 5.2})
    _sample_grid(state, start, [9.0, 9.0, 9.0], read_energy)
    closed = sampler.finalize_closed_interval(
        start, state_path=str(state), read_energy=read_energy, now=start + timedelta(minutes=15)
    )
    # 0.29 kWh imported over 870 s (first read 30 s into the slot), export counter left out
    assert closed["grid_import_kw"] == pytest.approx(1.2)
    assert closed["grid_import_source"] == sampler.GRID_IMPORT_SOURCE_COUNTER
    assert (closed["grid_import_start"], closed["grid_import_end"]) == (
        "2026-11-07T18:00:30",
        "2026-11-07T18:15:00",
    )
    # the net counter value keeps its fixed 0.25 h, as before
    assert closed["grid_kw"] == pytest.approx(0.36)


@pytest.mark.parametrize(
    ("close_total", "closed_after"),
    [(99.0, timedelta(minutes=15)), (100.29, timedelta(minutes=4))],
    ids=["counter reset", "window too short"],
)
def test_import_stays_on_the_mean_without_a_usable_counter_window(
    tmp_path: Path, close_total, closed_after
):
    state = tmp_path / "sampler.json"
    start = datetime(2026, 11, 7, 18, 0, 0)
    read_energy = _energy({"total": 100.0}, {"total": close_total})
    _sample_grid(state, start, [2.0, 2.0, 2.0], read_energy)
    closed = sampler.finalize_closed_interval(
        start, state_path=str(state), read_energy=read_energy, now=start + closed_after
    )
    assert closed["grid_import_source"] == sampler.GRID_IMPORT_SOURCE_MEAN
    assert closed["grid_import_kw"] == pytest.approx(2.0)


def test_finalize_overlays_flex_counter_when_anchored(tmp_path: Path):
    state = tmp_path / "sampler.json"
    start = datetime(2026, 9, 14, 14, 0, 0)
    readings = {
        "open": {
            "flex": {"ev": {"total": 10.0}},
        },
        "close": {
            "flex": {"ev": {"total": 10.5}},
        },
    }
    phase = {"n": 0}

    def read_energy():
        phase["n"] += 1
        return readings["open"] if phase["n"] == 1 else readings["close"]

    for offset in (30, 60, 90):
        assert sampler.tick(
            now=start + timedelta(seconds=offset),
            force=True,
            state_path=str(state),
            read_plant=lambda: _plant(pv=1.0, grid=0.0),
            read_soc=lambda: 50.0,
            read_flex_chart=lambda: {"ev": 1.0, "merker_only": 0.5},
            read_energy=read_energy,
        )
    closed = sampler.finalize_closed_interval(
        start, state_path=str(state), read_energy=read_energy
    )
    assert closed is not None
    assert closed["flex_kw"]["ev"] == pytest.approx(2.0)
    assert closed["flex_energy_kwh"]["ev"] == pytest.approx(0.5)
    assert closed["flex_kw"]["merker_only"] == pytest.approx(0.5)
    assert closed["ist_power_source"]["flex"]["ev"] == "counter"
    assert closed["ist_power_source"]["flex"]["merker_only"] == "mean"

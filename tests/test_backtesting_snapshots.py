"""Tests für Backtesting-Fenster-Snapshots (1.25.f)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import pytest

from simulation.backtesting_snapshots import (
    BACKTESTING_WINDOW_SNAPSHOTS_JSONL,
    build_window_snapshot,
    load_window_snapshot,
    normalize_window_anchor_key,
    remove_window_snapshots_jsonl,
    snapshot_supports_sunset_view,
    write_window_snapshots_jsonl,
)
from simulation.horizon_mode import FIXED_24H, SUNSET_WINDOW

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")


def _sample_rows(count: int = 24, start: datetime | None = None) -> tuple[list[dict], list[dict]]:
    anchor = start or datetime(2026, 6, 23, 7, 0)
    window_start = anchor - timedelta(hours=count)
    matrix: list[dict] = []
    chart_rows: list[dict] = []
    for index in range(count):
        slot = window_start + timedelta(hours=index)
        matrix.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "expected_p_pv": 1.0,
                "expected_p_act": 0.5,
                "k_act": 12.0,
                "consumption_mode": "logged_day",
            }
        )
        chart_rows.append(
            {
                "slot_datetime": slot,
                "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
                "PV-Prognose (kW)": 1.0,
                "Verbrauch-Prognose (kW)": 0.5,
                "Geplante Batterie-Aktion (kW)": 0.0,
                "Netzbezug (kW)": 0.0,
                "Simulierter SoC (%)": 50.0,
                "Steuerbefehl": "Automatik",
            }
        )
    return chart_rows, matrix


def test_normalize_window_anchor_key_strips_timezone():
    assert normalize_window_anchor_key("2026-06-23T07:00:00+02:00") == "2026-06-23T07:00:00"


def test_build_window_snapshot_fixed_24h_has_no_full_rows():
    chart_rows, matrix = _sample_rows()
    snapshot = build_window_snapshot(
        window_anchor=datetime(2026, 6, 23, 7, 0),
        scenario_id="live",
        horizon_mode=FIXED_24H,
        kind="consumption_tolerance",
        initial_soc=50.0,
        meta={"window_end": datetime(2026, 6, 23, 7, 0), "historical_total_kwh": 10.0},
        chart_rows_24h=chart_rows,
        matrix_24h=matrix,
    )
    assert "chart_rows_full" not in snapshot
    assert len(snapshot["chart_rows_24h"]) == 24
    assert snapshot_supports_sunset_view(snapshot) is False


def test_build_window_snapshot_sunset_includes_full_rows():
    chart_rows, matrix = _sample_rows()
    full_rows, full_matrix = _sample_rows(count=40)
    snapshot = build_window_snapshot(
        window_anchor=datetime(2026, 6, 23, 7, 0),
        scenario_id="live",
        horizon_mode=SUNSET_WINDOW,
        kind="consumption_tolerance",
        initial_soc=50.0,
        meta={"window_end": datetime(2026, 6, 23, 7, 0), "historical_total_kwh": 10.0},
        chart_rows_24h=chart_rows,
        matrix_24h=matrix,
        chart_rows_full=full_rows,
        matrix_full=full_matrix,
        sunrise_soc_min_index=2,
        scenario_params={
            "latitude": 47.404,
            "longitude": 9.743,
        },
    )
    assert len(snapshot["chart_rows_full"]) == 40
    assert snapshot["geo"]["latitude"] == pytest.approx(47.404)
    assert snapshot_supports_sunset_view(snapshot) is True


def test_build_window_snapshot_includes_battery_params():
    chart_rows, matrix = _sample_rows()
    battery_params = {
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 95.0,
        "max_power_kw": 5.0,
        "efficiency": 0.95,
    }
    snapshot = build_window_snapshot(
        window_anchor=datetime(2026, 6, 23, 7, 0),
        scenario_id="live",
        horizon_mode=FIXED_24H,
        kind="consumption_tolerance",
        initial_soc=50.0,
        meta={"window_end": datetime(2026, 6, 23, 7, 0), "historical_total_kwh": 10.0},
        chart_rows_24h=chart_rows,
        matrix_24h=matrix,
        battery_params=battery_params,
    )
    assert snapshot["battery_params"]["battery_capacity_kwh"] == 10.0


def test_write_and_load_window_snapshot_roundtrip(tmp_path):
    chart_rows, matrix = _sample_rows()
    snapshot = build_window_snapshot(
        window_anchor=datetime(2026, 6, 23, 7, 0),
        scenario_id="live",
        horizon_mode=FIXED_24H,
        kind="consumption_tolerance",
        initial_soc=50.0,
        meta={"window_end": datetime(2026, 6, 23, 7, 0), "historical_total_kwh": 10.0},
        chart_rows_24h=chart_rows,
        matrix_24h=matrix,
    )
    path = write_window_snapshots_jsonl(str(tmp_path), [snapshot])
    assert path is not None
    assert (tmp_path / BACKTESTING_WINDOW_SNAPSHOTS_JSONL).is_file()

    loaded = load_window_snapshot(
        str(tmp_path),
        "2026-06-23T07:00:00",
        "live",
    )
    assert loaded is not None
    assert loaded["scenario_id"] == "live"
    assert json.loads(json.dumps(loaded))["window_anchor"] == snapshot["window_anchor"]


def test_remove_window_snapshots_jsonl_deletes_stale_file(tmp_path):
    stale = tmp_path / BACKTESTING_WINDOW_SNAPSHOTS_JSONL
    stale.write_text("{}\n", encoding="utf-8")
    remove_window_snapshots_jsonl(str(tmp_path))
    assert not stale.is_file()


def test_save_backtesting_log_removes_stale_snapshots_without_new_ones(tmp_path):
    import pandas as pd

    from simulation.backtesting_log import save_backtesting_log
    from simulation.engine import HISTORICAL_REFERENCE_ID, PlausibilityReport

    stale = tmp_path / BACKTESTING_WINDOW_SNAPSHOTS_JSONL
    stale.write_text('{"horizon_mode": "fixed_24h"}\n', encoding="utf-8")
    index = pd.date_range("2025-06-01", periods=2, freq="h")
    results = {
        HISTORICAL_REFERENCE_ID: pd.DataFrame({"sim_cost": [1.0, 2.0]}, index=index),
    }
    empty_report = PlausibilityReport()
    save_backtesting_log(
        results,
        {HISTORICAL_REFERENCE_ID: "Ref"},
        {HISTORICAL_REFERENCE_ID: empty_report},
        {"start": "2025-06-01", "end": "2025-06-01", "horizon_mode": SUNSET_WINDOW},
        log_dir=str(tmp_path),
        window_snapshots=[],
    )
    assert not stale.is_file()

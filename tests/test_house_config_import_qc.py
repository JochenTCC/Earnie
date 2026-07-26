"""Tests for post-import QC span helpers and figure construction."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from house_config.consumption_csv import (
    write_canonical_hourly_csv,
)
from ui.house_config_import_qc import (
    _march_in_window,
    _se_window_from_data_max,
    balance_gesamt_for_chart,
    import_power_qc_figure,
    load_balance_gesamt_series,
)


def _rows(hours: int, *, start: datetime | None = None) -> list[tuple[str, float]]:
    start = start or datetime(2024, 1, 1)
    return [
        ((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), 1.0)
        for i in range(hours)
    ]


def test_import_power_qc_figure_has_traces() -> None:
    fig = import_power_qc_figure(_rows(24), _rows(24, start=datetime(2024, 1, 1, 12)))
    assert len(fig.data) == 2
    assert [t.name for t in fig.data] == [
        "PV-Erzeugungsprofil [kW]",
        "Lastprofil [kW] (Gesamt)",
    ]
    assert fig.layout.legend.y is not None
    assert fig.layout.legend.y < 0
    assert all(getattr(t.line, "shape", None) == "hv" for t in fig.data)


def test_import_power_qc_figure_balance_components() -> None:
    fig = import_power_qc_figure(
        _rows(24),
        _rows(24),
        battery_rows=_rows(24),
        grid_rows=_rows(24),
    )
    assert [t.name for t in fig.data] == [
        "PV-Erzeugungsprofil [kW]",
        "Batterie",
        "Netz",
        "Lastprofil [kW] (Gesamt)",
    ]
    assert all(getattr(t.line, "shape", None) == "hv" for t in fig.data)


def test_balance_gesamt_for_chart_derives_when_complete() -> None:
    pv = [("2024-01-01 00:00:00", 2.0), ("2024-01-01 01:00:00", 3.0)]
    batt = [("2024-01-01 00:00:00", 1.0), ("2024-01-01 01:00:00", -1.0)]
    grid = [("2024-01-01 00:00:00", 0.5), ("2024-01-01 01:00:00", 2.0)]
    total, clipped = balance_gesamt_for_chart(pv, batt, grid)
    assert clipped == 0
    assert total == [
        ("2024-01-01 00:00:00", 3.5),
        ("2024-01-01 01:00:00", 4.0),
    ]
    fig = import_power_qc_figure(total, pv, battery_rows=batt, grid_rows=grid)
    assert len(fig.data) == 4
    assert fig.data[-1].name == "Lastprofil [kW] (Gesamt)"


def test_balance_gesamt_for_chart_skips_incomplete() -> None:
    total, clipped = balance_gesamt_for_chart(_rows(3), _rows(3), None)
    assert total is None
    assert clipped == 0


def test_load_balance_gesamt_series_from_files(tmp_path: Path) -> None:
    pv = tmp_path / "pv.csv"
    batt = tmp_path / "batt.csv"
    grid = tmp_path / "grid.csv"
    write_canonical_hourly_csv(
        str(pv),
        [("2024-01-01 00:00:00", 2.0), ("2024-01-01 01:00:00", 1.0)],
    )
    write_canonical_hourly_csv(
        str(batt),
        [("2024-01-01 00:00:00", 0.5), ("2024-01-01 01:00:00", -0.5)],
    )
    write_canonical_hourly_csv(
        str(grid),
        [("2024-01-01 00:00:00", 1.0), ("2024-01-01 01:00:00", 2.0)],
    )
    total, clipped = load_balance_gesamt_series(str(pv), str(batt), str(grid))
    assert clipped == 0
    assert total == [
        ("2024-01-01 00:00:00", 3.5),
        ("2024-01-01 01:00:00", 2.5),
    ]


def test_march_in_window_prefers_march() -> None:
    assert _march_in_window(pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")) == 3
    assert _march_in_window(pd.Timestamp("2025-04-01"), pd.Timestamp("2026-02-28")) == 4


def test_se_window_from_data_max_month_aligned() -> None:
    start, end = _se_window_from_data_max(pd.Timestamp("2026-06-15"))
    assert end == pd.Timestamp("2026-05-31")
    assert start == pd.Timestamp("2025-06-01")


def test_write_short_canonical_ok(tmp_path: Path) -> None:
    path = tmp_path / "short.csv"
    write_canonical_hourly_csv(str(path), _rows(48))
    text = path.read_text(encoding="utf-8")
    assert "timestamp" in text
    assert text.count("\n") >= 48

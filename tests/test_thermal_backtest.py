"""Tests für thermischen Historien-Backtest."""
from __future__ import annotations

from pathlib import Path

import pytest

from data.thermal_backtest import backtest_heat_loss_kw_per_k, load_merged_history

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "thermal"


def _history_logs() -> dict[str, str]:
    actual = next(FIXTURE_DIR.glob("*currenttemperature*"), None)
    ambient = next(FIXTURE_DIR.glob("*Einfahrt*"), None)
    power = next(FIXTURE_DIR.glob("*Verbrauchsz*"), None)
    if not actual or not ambient or not power:
        pytest.skip("Thermische CSV-Fixtures fehlen")
    return {
        "actual_temp_csv": str(actual),
        "ambient_temp_csv": str(ambient),
        "power_csv": str(power),
    }


def test_backtest_runs_on_fixtures():
    merged = load_merged_history(_history_logs())
    result = backtest_heat_loss_kw_per_k(
        merged,
        water_volume_liters=6000,
        heating_power_threshold_kw=2.0,
        heat_loss_kw_per_k=0.12,
        heating_efficiency=0.95,
    )
    assert result["hours"] > 0
    assert result["mae_c"] >= 0.0

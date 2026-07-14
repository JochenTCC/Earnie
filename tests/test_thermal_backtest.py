"""Tests für thermischen Historien-Backtest."""
from __future__ import annotations

import pytest

from data.thermal_backtest import backtest_heat_loss_kw_per_k, load_merged_history
from tests.fixtures.thermal_rc_reference import swimspa_history_logs


@pytest.fixture(scope="module")
def swimspa_logs() -> dict[str, str]:
    try:
        return swimspa_history_logs()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


def test_backtest_runs_on_fixtures(swimspa_logs):
    merged = load_merged_history(swimspa_logs)
    result = backtest_heat_loss_kw_per_k(
        merged,
        water_volume_liters=6000,
        heating_power_threshold_kw=2.0,
        heat_loss_kw_per_k=0.12,
        heating_efficiency=0.95,
    )
    assert result["hours"] > 0
    assert result["mae_c"] >= 0.0

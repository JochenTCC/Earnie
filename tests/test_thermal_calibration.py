"""Tests für thermische U-Kalibrierung aus CSV-Fixtures."""
from __future__ import annotations

import pytest

from data.thermal_calibration import estimate_heat_loss_kw_per_k
from tests.fixtures.thermal_rc_reference import swimspa_history_logs


@pytest.fixture(scope="module")
def swimspa_logs() -> dict[str, str]:
    try:
        return swimspa_history_logs()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


def test_estimate_u_from_fixtures(swimspa_logs):
    u_value, detail = estimate_heat_loss_kw_per_k(
        swimspa_logs,
        water_volume_liters=6000,
        heating_power_threshold_kw=2.0,
        min_flat_hours=12,
        min_samples=1,
    )
    assert 0.001 < u_value < 0.5
    assert detail["samples"] >= 1

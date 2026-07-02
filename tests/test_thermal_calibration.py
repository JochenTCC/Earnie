"""Tests für thermische U-Kalibrierung aus CSV-Fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from data.thermal_calibration import estimate_heat_loss_kw_per_k

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "thermal"


def _fixture_paths() -> dict[str, str]:
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


def test_estimate_u_from_fixtures():
    history_logs = _fixture_paths()
    u_value, detail = estimate_heat_loss_kw_per_k(
        history_logs,
        water_volume_liters=6000,
        heating_power_threshold_kw=2.0,
        min_flat_hours=12,
        min_samples=1,
    )
    assert 0.001 < u_value < 0.5
    assert detail["samples"] >= 1

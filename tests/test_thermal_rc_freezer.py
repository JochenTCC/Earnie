"""Tests für Freezer-Referenzmodell (zweites thermal_rc-Fixture)."""
from __future__ import annotations

import pytest

from data.thermal_backtest import backtest_heat_loss_kw_per_k, load_merged_history
from data.thermal_calibration import estimate_heat_loss_kw_per_k
from house_config.planning_flex_bridge import planning_thermal_rc_to_milp
from tests.fixtures.thermal_rc_reference import (
    FREEZER_HEATING_THRESHOLD_KW,
    FREEZER_THERMAL_RC_CONSUMER,
    FREEZER_U_KW_PER_K,
    FREEZER_VOLUME_L,
    freezer_history_logs,
)


@pytest.fixture(scope="module")
def freezer_logs() -> dict[str, str]:
    try:
        return freezer_history_logs()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


def test_freezer_u_calibration_from_fixtures(freezer_logs):
    u_value, detail = estimate_heat_loss_kw_per_k(
        freezer_logs,
        water_volume_liters=FREEZER_VOLUME_L,
        heating_power_threshold_kw=FREEZER_HEATING_THRESHOLD_KW,
        min_flat_hours=6,
        min_samples=5,
    )
    assert detail.get("warming_events", 0) >= 1
    assert u_value == pytest.approx(FREEZER_U_KW_PER_K, rel=0.35)


def test_freezer_backtest_known_u(freezer_logs):
    merged = load_merged_history(
        freezer_logs,
        heating_threshold_kw=FREEZER_HEATING_THRESHOLD_KW,
    )
    result = backtest_heat_loss_kw_per_k(
        merged,
        water_volume_liters=FREEZER_VOLUME_L,
        heating_power_threshold_kw=FREEZER_HEATING_THRESHOLD_KW,
        heat_loss_kw_per_k=FREEZER_U_KW_PER_K,
        heating_efficiency=0.85,
    )
    assert result["hours"] > 24
    assert result["mae_c"] < 1.5


def test_freezer_thermal_rc_bridge():
    milp = planning_thermal_rc_to_milp(FREEZER_THERMAL_RC_CONSUMER)
    assert milp["daily_target_source"] == "thermal"
    assert milp["thermal_control"]["setpoint_c"] == pytest.approx(-18.0)
    assert milp["id"] == "freezer_ref"
    assert "legacy_id" not in milp

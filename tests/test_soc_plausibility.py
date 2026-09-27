"""Unit tests for SOC plausibility helpers."""
from __future__ import annotations

import pytest

from runtime_store.soc_plausibility import (
    closed_interval_confirms_reported,
    count_consecutive_reported_soc,
    integrate_soc_step,
    max_soc_delta_per_slot,
    sanitize_soc_reading,
)

_PARAMS = {
    "battery_capacity_kwh": 5.0,
    "max_power_kw": 2.5,
    "efficiency": 0.92,
    "min_soc": 10.0,
    "max_soc": 100.0,
}


def test_max_soc_delta_per_slot_5kwh_battery():
    assert max_soc_delta_per_slot(_PARAMS) == pytest.approx(15.1, abs=0.5)


def test_sanitize_rejects_midnight_spike():
    soc, corrected = sanitize_soc_reading(19.0, 51.2, 0.2, _PARAMS)
    assert corrected is True
    assert soc == pytest.approx(integrate_soc_step(19.0, 0.2, _PARAMS), abs=0.1)


def test_sanitize_keeps_plausible_reading():
    soc, corrected = sanitize_soc_reading(19.0, 20.0, 0.2, _PARAMS)
    assert corrected is False
    assert soc == 20.0


def test_sanitize_accepts_repeated_ess_plateau_after_spike():
    """ESS latched at 55 % while chain still held 81 % (debug_dump_20260820_093415)."""
    soc, corrected = sanitize_soc_reading(
        81.0,
        55.0,
        0.0,
        _PARAMS,
        consecutive_same_reported=2,
    )
    assert corrected is True
    assert soc == 55.0


def test_sanitize_accepts_contradictory_drop_while_charging():
    """Chain too high; ESS reports low SoC while integration would charge further."""
    soc, corrected = sanitize_soc_reading(49.2, 19.0, 0.2, _PARAMS)
    assert corrected is True
    assert soc == 19.0


def test_sanitize_rejects_plant_drop_without_recovery_hint():
    """debug_dump_20260927_083552: idle battery, chain 98.7, plant 6 — without hint."""
    soc, corrected = sanitize_soc_reading(98.7, 6.0, -0.02, _PARAMS)
    assert corrected is True
    assert soc == pytest.approx(integrate_soc_step(98.7, -0.02, _PARAMS), abs=0.1)


def test_closed_interval_jump_confirms_plant_soc():
    """Sampler saw 98.7→6 in the closed quarter-hour; trust plant 6 %."""
    closed = {
        "soc_start_percent": 98.7,
        "soc_end_percent": 6.0,
        "sample_count": 8,
    }
    assert closed_interval_confirms_reported(closed, 6.0, 98.7, _PARAMS) is True
    soc, corrected = sanitize_soc_reading(
        98.7,
        6.0,
        -0.02,
        _PARAMS,
        consecutive_same_reported=2,
    )
    assert soc == 6.0
    assert corrected is True


def test_closed_interval_settled_confirms_plant_soc():
    """Whole interval already at plant SoC while history chain is stale."""
    closed = {
        "soc_start_percent": 6.0,
        "soc_end_percent": 6.0,
        "sample_count": 8,
    }
    assert closed_interval_confirms_reported(closed, 6.0, 98.6, _PARAMS) is True


def test_closed_interval_does_not_confirm_opt_time_spike():
    """Live spike at decision time while sampler still tracks the real SoC."""
    closed = {
        "soc_start_percent": 19.0,
        "soc_end_percent": 19.2,
        "sample_count": 8,
    }
    assert closed_interval_confirms_reported(closed, 51.2, 19.0, _PARAMS) is False


def test_count_consecutive_reported_soc():
    rows = [
        {"soc_percent": 98.0},
        {"reported_soc_percent": 6.0},
        {"reported_soc_percent": 6.0},
    ]
    assert count_consecutive_reported_soc(rows, 6.0) == 3
    assert count_consecutive_reported_soc([{"soc_percent": 98.0}], 6.0) == 1

"""Unit tests for SOC plausibility helpers."""
from __future__ import annotations

import pytest

from runtime_store.soc_plausibility import (
    integrate_soc_step,
    max_soc_delta_per_slot,
    sanitize_soc_reading,
)


def test_max_soc_delta_per_slot_5kwh_battery():
    params = {
        "battery_capacity_kwh": 5.0,
        "max_power_kw": 2.5,
        "efficiency": 0.92,
        "min_soc": 10.0,
        "max_soc": 100.0,
    }
    assert max_soc_delta_per_slot(params) == pytest.approx(15.1, abs=0.5)


def test_sanitize_rejects_midnight_spike():
    params = {
        "battery_capacity_kwh": 5.0,
        "max_power_kw": 2.5,
        "efficiency": 0.92,
        "min_soc": 10.0,
        "max_soc": 100.0,
    }
    soc, corrected = sanitize_soc_reading(19.0, 51.2, 0.2, params)
    assert corrected is True
    assert soc == pytest.approx(integrate_soc_step(19.0, 0.2, params), abs=0.1)


def test_sanitize_keeps_plausible_reading():
    params = {
        "battery_capacity_kwh": 5.0,
        "max_power_kw": 2.5,
        "efficiency": 0.92,
        "min_soc": 10.0,
        "max_soc": 100.0,
    }
    soc, corrected = sanitize_soc_reading(19.0, 20.0, 0.2, params)
    assert corrected is False
    assert soc == 20.0

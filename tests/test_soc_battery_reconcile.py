"""Unit tests for SoC↔Ist battery reconciliation helpers."""
from __future__ import annotations

import pytest

from runtime_store.history_chart_rows import (
    CHART_IST_BATTERY_KW_COLUMN,
    SLOT_PRESENT,
    _reconcile_history_battery_with_soc,
)
from runtime_store.soc_plausibility import (
    battery_kw_from_soc_delta,
    ist_contradicts_soc_delta,
)


_PARAMS = {
    "battery_capacity_kwh": 5.0,
    "max_power_kw": 2.5,
    "efficiency": 0.92,
    "min_soc": 10.0,
    "max_soc": 100.0,
}


def test_ist_contradicts_soc_delta_detects_discharge_while_rising():
    assert ist_contradicts_soc_delta(-2.5, 8.0) is True
    assert ist_contradicts_soc_delta(2.5, 8.0) is False
    assert ist_contradicts_soc_delta(-2.5, -4.0) is False


def test_battery_kw_from_soc_delta_matches_charge_direction():
    implied = battery_kw_from_soc_delta(42.0, 50.0, _PARAMS)
    assert implied > 0.0
    assert implied == pytest.approx(1.739, abs=0.05)


def test_reconcile_replaces_discharge_bar_when_soc_rises(monkeypatch):
    monkeypatch.setattr(
        "runtime_store.history_chart_rows.config.get_battery_params",
        lambda: dict(_PARAMS),
    )
    rows = [
        {
            "Uhrzeit": "13:00",
            "Simulierter SoC (%)": 42.0,
            CHART_IST_BATTERY_KW_COLUMN: -2.5,
        },
        {
            "Uhrzeit": "13:15",
            "Simulierter SoC (%)": 50.0,
            CHART_IST_BATTERY_KW_COLUMN: 2.5,
        },
    ]
    out = _reconcile_history_battery_with_soc(rows, [SLOT_PRESENT, SLOT_PRESENT])
    assert out[0][CHART_IST_BATTERY_KW_COLUMN] > 0.0
    assert out[0][CHART_IST_BATTERY_KW_COLUMN] == pytest.approx(1.739, abs=0.05)
    assert out[1][CHART_IST_BATTERY_KW_COLUMN] == 2.5


def test_reconcile_keeps_ist_when_signs_agree(monkeypatch):
    monkeypatch.setattr(
        "runtime_store.history_chart_rows.config.get_battery_params",
        lambda: dict(_PARAMS),
    )
    rows = [
        {
            "Uhrzeit": "12:00",
            "Simulierter SoC (%)": 50.0,
            CHART_IST_BATTERY_KW_COLUMN: -0.29,
        },
        {
            "Uhrzeit": "12:15",
            "Simulierter SoC (%)": 48.0,
            CHART_IST_BATTERY_KW_COLUMN: -0.72,
        },
    ]
    out = _reconcile_history_battery_with_soc(rows, [SLOT_PRESENT, SLOT_PRESENT])
    assert out[0][CHART_IST_BATTERY_KW_COLUMN] == pytest.approx(-0.29)

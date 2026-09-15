"""Chart / Kosten / deviation use closed_interval means; reconcile gated."""
from __future__ import annotations

from datetime import datetime

import pytest

from optimizer.deviation_facts import build_slot_deviation_facts
from runtime_store.history_chart_rows import (
    CHART_IST_BATTERY_KW_COLUMN,
    SLOT_PRESENT,
    _reconcile_history_battery_with_soc,
    entry_to_chart_row,
)
from runtime_store.slot_ist_powers import index_closed_intervals_by_start, resolve_ist_snapshot
from ui.consumer_cost_analysis_data import slot_from_replay_entry


def _decision_snap(*, battery_kw: float) -> dict:
    return {
        "pv_kw": 1.0,
        "grid_kw": 0.5,
        "battery_kw": battery_kw,
        "house_kw": 2.0,
        "baseload_kw": 2.0,
        "flex_sum_kw": 0.0,
        "flex_kw": {},
    }


def test_entry_to_chart_row_uses_closed_interval_ist():
    slot = datetime(2026, 9, 14, 13, 0, 0)
    plan = {
        "mode": 0,
        "target_power_kw": 0.0,
        "soc_percent": 42.0,
        "forecast_pv_kw": 5.0,
        "forecast_consumption_kw": 2.0,
        "battery_plan_kw": 0.0,
        "consumption_snapshot": _decision_snap(battery_kw=2.5),
        "market_price_cent": 10.0,
    }
    closed = {
        "interval_start": "2026-09-14T13:00:00",
        "sample_count": 4,
        "pv_kw": 3.0,
        "grid_kw": 0.2,
        "battery_kw": -0.5,
        "house_kw": 1.5,
        "baseload_kw": 1.5,
        "flex_sum_kw": 0.0,
        "flex_kw": {},
    }
    ist, _ = resolve_ist_snapshot(
        slot, plan, index_closed_intervals_by_start([{"closed_interval": closed}])
    )
    row = entry_to_chart_row(plan, slot, ist_snapshot=ist)
    assert row[CHART_IST_BATTERY_KW_COLUMN] == pytest.approx(0.5)
    assert row["PV-Ist (kW)"] == pytest.approx(3.0)
    assert row["Netzbezug (kW)"] == pytest.approx(0.2)


def test_reconcile_skipped_when_mean_usable(monkeypatch):
    monkeypatch.setattr(
        "runtime_store.history_chart_rows.config.get_battery_params",
        lambda: {
            "battery_capacity_kwh": 5.0,
            "max_power_kw": 2.5,
            "efficiency": 0.92,
            "min_soc": 10.0,
            "max_soc": 100.0,
        },
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
    out = _reconcile_history_battery_with_soc(
        rows, [SLOT_PRESENT, SLOT_PRESENT], mean_usable=[True, False]
    )
    assert out[0][CHART_IST_BATTERY_KW_COLUMN] == pytest.approx(-2.5)


def test_deviation_facts_use_closed_interval_battery():
    slot = datetime(2026, 9, 14, 13, 0, 0)
    entry = {
        "mode": 3,
        "target_power_kw": 2.0,
        "battery_plan_kw": -2.0,
        "consumer_powers_kw": {},
        "consumption_snapshot": _decision_snap(battery_kw=2.5),
    }
    closed = {
        "interval_start": "2026-09-14T13:00:00",
        "sample_count": 4,
        "pv_kw": 1.0,
        "grid_kw": 0.0,
        "battery_kw": -0.4,
        "house_kw": 1.0,
        "baseload_kw": 1.0,
        "flex_kw": {},
    }
    facts = build_slot_deviation_facts(
        entry,
        slot_start=slot,
        closed_by_interval=index_closed_intervals_by_start(
            [{"closed_interval": closed}]
        ),
    )
    assert facts.battery.ist_power_kw == pytest.approx(-0.4)


def test_cost_slot_uses_closed_interval_mean(monkeypatch):
    monkeypatch.setattr(
        "ui.consumer_cost_analysis_data.cost_analysis_consumers",
        lambda: [],
    )
    slot = datetime(2026, 9, 14, 13, 0, 0)
    entry = {
        "mode": 0,
        "market_price_cent": 20.0,
        "forecast_pv_kw": 0.0,
        "forecast_consumption_kw": 1.0,
        "battery_plan_kw": 0.0,
        "consumption_snapshot": _decision_snap(battery_kw=2.5),
    }
    closed = {
        "interval_start": "2026-09-14T13:00:00",
        "sample_count": 4,
        "pv_kw": 4.0,
        "grid_kw": 0.0,
        "battery_kw": -1.0,
        "house_kw": 1.0,
        "baseload_kw": 1.0,
        "flex_sum_kw": 0.0,
        "flex_kw": {},
    }
    cost_slot = slot_from_replay_entry(
        entry,
        slot,
        consumers=[],
        closed_by_interval=index_closed_intervals_by_start(
            [{"closed_interval": closed}]
        ),
    )
    assert cost_slot.pv_kw == pytest.approx(4.0)
    assert cost_slot.battery_charge_kwh == pytest.approx(0.25)

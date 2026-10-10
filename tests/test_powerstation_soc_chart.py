"""Chart1 SoC helpers for virtual/physical powerstations."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from optimizer.powerstation_soc_chart import (
    chart_soc_entities,
    initial_virtual_sim_entries,
    simulate_virtual_reserve_soc_after_slot,
    virtual_soc_by_id_from_states,
    virtual_soc_percent,
)
from optimizer.sim_chart_rows import COL_SOC, attach_ess_soc_columns, ess_soc_column_name
from runtime_store.history_chart_rows import entry_to_chart_row
from runtime_store.powerstation_reserves import STATE_CHARGING, STATE_STANDBY

_TZ = ZoneInfo("Europe/Vienna")


def test_virtual_soc_percent_clamps_and_scales():
    assert virtual_soc_percent(1.0, 2.0) == 50.0
    assert virtual_soc_percent(3.0, 2.0) == 100.0
    assert virtual_soc_percent(-1.0, 2.0) == 0.0
    assert virtual_soc_percent(1.0, 0.0) == 0.0


def test_chart_soc_entities_orders_house_then_powerstations():
    entities = chart_soc_entities(
        [{"id": "house", "label": "Haus", "battery_capacity_kwh": 10.0}],
        [
            {
                "id": "phys",
                "label": "Garage",
                "type": "powerstation",
                "backing": "physical",
                "battery_capacity_kwh": 5.0,
            },
            {
                "id": "virt",
                "label": "WM",
                "type": "powerstation",
                "backing": "virtual",
                "battery_capacity_kwh": 2.0,
            },
        ],
    )
    assert [e["id"] for e in entities] == ["house", "phys", "virt"]
    assert entities[1]["virtual"] is False
    assert entities[2]["virtual"] is True


def test_virtual_soc_by_id_from_states():
    ps = [
        {
            "id": "virt",
            "type": "powerstation",
            "backing": "virtual",
            "battery_capacity_kwh": 2.0,
        }
    ]
    assert virtual_soc_by_id_from_states(
        ps, {"virt": {"stored_kwh": 0.5, "target_kwh": 1.0}}
    ) == {"virt": 25.0}


def test_simulate_virtual_reserve_charge_raises_soc():
    entries = initial_virtual_sim_entries(
        powerstations=[
            {
                "id": "virt",
                "type": "powerstation",
                "backing": "virtual",
                "battery_capacity_kwh": 2.0,
            }
        ],
        reserve_states={
            "virt": {
                "state": STATE_CHARGING,
                "stored_kwh": 0.0,
                "target_kwh": 1.0,
                "trigger_active": False,
            }
        },
    )
    # 2 kW charge × 0.25 h = 0.5 kWh → 25% of 2 kWh capacity
    after = simulate_virtual_reserve_soc_after_slot(
        battery_plan_kw=2.0,
        dt_h=0.25,
        virtual_entries=entries,
    )
    assert after["virt"] == 25.0
    assert entries[0]["state"] == STATE_CHARGING
    assert entries[0]["stored_kwh"] == 0.5


def test_simulate_virtual_reserve_reaches_standby():
    entries = initial_virtual_sim_entries(
        powerstations=[
            {
                "id": "virt",
                "type": "powerstation",
                "backing": "virtual",
                "battery_capacity_kwh": 2.0,
            }
        ],
        reserve_states={
            "virt": {
                "state": STATE_CHARGING,
                "stored_kwh": 0.8,
                "target_kwh": 1.0,
                "trigger_active": False,
            }
        },
    )
    after = simulate_virtual_reserve_soc_after_slot(
        battery_plan_kw=4.0,
        dt_h=0.25,
        virtual_entries=entries,
    )
    assert after["virt"] == 50.0  # target 1.0 / capacity 2.0
    assert entries[0]["state"] == STATE_STANDBY
    assert entries[0]["stored_kwh"] == 1.0


def test_attach_ess_soc_columns_with_house_and_virtual():
    entities = chart_soc_entities(
        [{"id": "house", "label": "Haus"}],
        [
            {
                "id": "virt",
                "label": "WM",
                "type": "powerstation",
                "backing": "virtual",
            }
        ],
    )
    row: dict = {COL_SOC: 40.0}
    attach_ess_soc_columns(
        row,
        {"house": 40.0, "virt": 12.5},
        entities,
    )
    assert row[ess_soc_column_name("Haus")] == 40.0
    assert row[ess_soc_column_name("WM")] == 12.5


def test_history_entry_maps_virtual_soc_column(monkeypatch):
    entities = chart_soc_entities(
        [{"id": "house", "label": "Haus", "battery_capacity_kwh": 10.0}],
        [
            {
                "id": "virt",
                "label": "WM",
                "type": "powerstation",
                "backing": "virtual",
                "battery_capacity_kwh": 2.0,
            }
        ],
    )
    monkeypatch.setattr(
        "optimizer.powerstation_soc_chart.load_chart_soc_entities",
        lambda: entities,
    )
    entry = {
        "mode": 0,
        "target_power_kw": 0.0,
        "soc_percent": 55.0,
        "soc_percent_by_ess": {"house": 55.0, "virt": 30.0},
        "market_price_cent": 12.0,
        "forecast_pv_kw": 1.0,
        "forecast_consumption_kw": 0.5,
        "battery_plan_kw": 0.0,
    }
    row = entry_to_chart_row(
        entry, datetime(2026, 6, 1, 12, 0, tzinfo=_TZ)
    )
    assert row[ess_soc_column_name("Haus")] == 55.0
    assert row[ess_soc_column_name("WM")] == 30.0

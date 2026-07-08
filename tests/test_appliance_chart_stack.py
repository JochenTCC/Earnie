"""Manuelle Geräte als eigene Spuren im Chart-1-Flex-Stack."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import config
from optimizer.appliance_schedule import (
    appliance_as_chart_consumer,
    appliance_column_name,
    apply_appliance_schedules_to_chart_rows,
)
from ui.chart_colors import COLOR_MANUAL_APPLIANCE, flex_bar_chart_color
from ui.charts import clear_consumer_stack_order_cache, ordered_active_consumers_for_stack

_TZ = ZoneInfo("Europe/Vienna")

_APPLIANCES = (
    {
        "id": "waschmaschine",
        "name": "Waschmaschine",
        "power_source": "manual",
        "default_power_kw": 2.0,
        "default_runtime_h": 2.0,
    },
    {
        "id": "trockner",
        "name": "Trockner",
        "power_source": "manual",
        "default_power_kw": 1.5,
        "default_runtime_h": 1.0,
    },
)


def _patch_appliances(monkeypatch):
    monkeypatch.setattr(config, "get_appliances", lambda: list(_APPLIANCES))
    monkeypatch.setattr(config, "get_flexible_consumers", lambda optimizer_only=False: [])


def test_chart_rows_split_appliance_from_baseload(monkeypatch):
    _patch_appliances(monkeypatch)
    start = datetime(2026, 7, 8, 18, 0, tzinfo=_TZ)
    chart_rows = [
        {
            "slot_datetime": start,
            "Verbrauch-Prognose (kW)": 3.0,
            "PV-Prognose (kW)": 0.0,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 3.0,
        },
        {
            "slot_datetime": start + timedelta(hours=1),
            "Verbrauch-Prognose (kW)": 3.0,
            "PV-Prognose (kW)": 0.0,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 3.0,
        },
    ]
    schedules = {
        "waschmaschine": {
            "start_at": start.isoformat(timespec="seconds"),
            "power_kw": 2.0,
            "runtime_h": 2.0,
            "expires_at": (start + timedelta(hours=2)).isoformat(timespec="seconds"),
        }
    }
    apply_appliance_schedules_to_chart_rows(chart_rows, schedules)

    assert chart_rows[0]["Verbrauch-Prognose (kW)"] == 1.0
    assert chart_rows[0]["Waschmaschine (kW)"] == 2.0
    assert chart_rows[0]["Netzbezug (kW)"] == 3.0
    assert chart_rows[1]["Verbrauch-Prognose (kW)"] == 1.0
    assert chart_rows[1]["Waschmaschine (kW)"] == 2.0


def test_manual_appliances_share_chart_color(monkeypatch):
    _patch_appliances(monkeypatch)
    washer = appliance_as_chart_consumer(_APPLIANCES[0])
    dryer = appliance_as_chart_consumer(_APPLIANCES[1])
    assert flex_bar_chart_color(washer) == COLOR_MANUAL_APPLIANCE
    assert flex_bar_chart_color(dryer) == COLOR_MANUAL_APPLIANCE
    assert washer["name"] != dryer["name"]


def test_ordered_stack_includes_named_appliances(monkeypatch):
    _patch_appliances(monkeypatch)
    clear_consumer_stack_order_cache()
    start = datetime(2026, 7, 8, 18, 0, tzinfo=_TZ)
    df = pd.DataFrame(
        {
            "slot_datetime": [start, start + timedelta(hours=1)],
            "Waschmaschine (kW)": [2.0, 2.0],
            "Trockner (kW)": [0.0, 1.5],
        }
    )
    active = ordered_active_consumers_for_stack(df)
    names = [consumer["name"] for consumer, _ in active]
    assert names == ["Waschmaschine", "Trockner"]
    columns = [column for _, column in active]
    assert columns == [
        appliance_column_name(_APPLIANCES[0]),
        appliance_column_name(_APPLIANCES[1]),
    ]


def test_devices_callback_calls_invalidate(monkeypatch):
    from ui.pages import page_devices
    from optimizer.appliance_recommendation import ApplianceRecommendation, StartOption

    invalidated = {"count": 0}
    monkeypatch.setattr(
        page_devices,
        "invalidate_live_optimization_cache",
        lambda: invalidated.__setitem__("count", invalidated["count"] + 1),
    )
    monkeypatch.setattr(
        page_devices.appliance_schedules,
        "save_schedule",
        lambda *args, **kwargs: {},
    )
    start = datetime(2026, 7, 8, 18, 0, tzinfo=_TZ)
    option = StartOption(
        start_datetime=start,
        cost_eur=1.0,
        stars=3,
        savings_vs_now_eur=0.0,
    )
    rec = ApplianceRecommendation(
        options=[option],
        cheapest=option,
        immediate=option,
        skipped_start_slots=0,
    )
    key = page_devices._plan_checkbox_key("waschmaschine", 0)
    page_devices.st.session_state[key] = True
    page_devices._on_plan_checkbox_change(
        "waschmaschine",
        0,
        rec,
        power_kw=2.0,
        runtime_h=2.0,
    )
    assert invalidated["count"] == 1

"""Chart-1 peel for earnie_role=known generics."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from house_config.known_chart_display import (
    apply_known_generic_to_chart_rows,
    apply_known_generic_to_dataframe,
    chart_known_generics,
)
from ui.chart_consumer_stack import (
    chart_flex_consumers_context,
    clear_consumer_stack_order_cache,
    ordered_active_consumers_for_stack,
)

_TZ = ZoneInfo("Europe/Vienna")

_PROFILE = {
    "baseload_kwh": 4500.0,
    "consumers": [
        {
            "id": "kochen",
            "label": "Kochen",
            "type": "generic",
            "nominal_power_kw": 2.0,
            "schedule": {
                "runs_per_week": 7,
                "duration_h": 1.0,
                "start_hour": 19,
                "start_shift_h": 0.0,
            },
            "earnie_role": "known",
        },
        {
            "id": "fernsehen",
            "label": "Fernsehen",
            "type": "generic",
            "nominal_power_kw": 0.2,
            "schedule": {
                "runs_per_week": 7,
                "duration_h": 6.0,
                "start_hour": 18,
                "start_shift_h": 0.0,
            },
            "earnie_role": "known",
        },
    ],
}


def test_chart_rows_split_known_from_baseload():
    slot_19 = datetime(2026, 7, 16, 19, 0, tzinfo=_TZ)
    chart_rows = [
        {
            "slot_datetime": slot_19,
            "Verbrauch-Prognose (kW)": 2.717,
            "PV-Prognose (kW)": 0.0,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 2.717,
        }
    ]
    apply_known_generic_to_chart_rows(chart_rows, house_profile=_PROFILE)
    assert chart_rows[0]["Kochen (kW)"] == 2.0
    assert chart_rows[0]["Fernsehen (kW)"] == 0.2
    assert chart_rows[0]["Verbrauch-Prognose (kW)"] == 0.517
    # Idempotent
    apply_known_generic_to_chart_rows(chart_rows, house_profile=_PROFILE)
    assert chart_rows[0]["Verbrauch-Prognose (kW)"] == 0.517


def test_ordered_stack_includes_known_after_peel(monkeypatch):
    clear_consumer_stack_order_cache()
    monkeypatch.setattr(
        "config.get_resolved_runtime_settings",
        lambda: {"_house_profile": _PROFILE},
    )
    slot = datetime(2026, 7, 16, 19, 0, tzinfo=_TZ)
    df = pd.DataFrame(
        [
            {
                "slot_datetime": slot,
                "Verbrauch-Prognose (kW)": 2.717,
                "PV-Prognose (kW)": 0.0,
                "Geplante Batterie-Aktion (kW)": 0.0,
                "Netzbezug (kW)": 2.717,
            }
        ]
    )
    df = apply_known_generic_to_dataframe(df, house_profile=_PROFILE)
    with chart_flex_consumers_context([]):
        active = ordered_active_consumers_for_stack(df)
    names = [consumer["name"] for consumer, _ in active]
    assert "Kochen" in names
    assert "Fernsehen" in names


def test_chart_known_generics_allocate_colors():
    consumers = chart_known_generics(_PROFILE, used_color_indices={0, 1})
    assert {c["id"] for c in consumers} == {"kochen", "fernsehen"}
    assert all(c["chart_color_index"] is not None for c in consumers)

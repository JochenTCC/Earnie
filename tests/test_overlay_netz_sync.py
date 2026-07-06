"""Netzbezug-Sync nach Live-Overlay (neutraler MILP-Bereich)."""
from __future__ import annotations

import optimizer
from optimizer.simulation import sync_chart_row_netzbezug


def test_sync_chart_row_netzbezug_from_power_balance() -> None:
    row = {
        "PV-Prognose (kW)": 5.0,
        "Verbrauch-Prognose (kW)": 1.0,
        "Geplante Batterie-Aktion (kW)": 2.0,
    }
    sync_chart_row_netzbezug(row)
    assert row["Netzbezug (kW)"] == -2.0


def test_overlay_main_run_recalculates_netzbezug() -> None:
    rows = [
        {
            "PV-Prognose (kW)": 5.0,
            "Verbrauch-Prognose (kW)": 1.0,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Netzbezug (kW)": 99.0,
            "Steuerbefehl": "Automatik",
        }
    ]
    updated = optimizer.overlay_main_run_on_rows(
        rows,
        {
            "success": True,
            "mode": 0,
            "target_power_kw": 0.0,
            "battery_plan_kw": 2.0,
            "consumer_powers_kw": {},
        },
    )
    assert updated[0]["Netzbezug (kW)"] == -2.0

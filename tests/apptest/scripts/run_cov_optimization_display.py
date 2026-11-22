"""Optimization result display (Chart 1, Chart 2, table, energy comparison) from synthetic rows.

Mode from ``st.session_state["cov_mode"]`` (set by the test before the first run):
``results`` -> ``render_optimization_results`` (live chart context, S-2 nav buttons),
``snapshot`` -> bundle from a persisted main.py snapshot + Chart 1 + data-basis expander,
``empty_snapshot`` -> snapshot without simulation rows (no bundle).
No MILP runs: the rows are fixed numbers.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from ui.chart_context import build_live_chart_context
from ui.simulation_results import (
    build_optimization_display_bundle_from_snapshot,
    render_live_display_data_basis_expander,
    render_optimization_chart1,
    render_optimization_results,
)

NOW = datetime(2026, 7, 5, 10, 30, tzinfo=ZoneInfo("Europe/Vienna"))
SEGMENT = 1  # SA1->SA2: only MILP rows, independent of the production log


def _rows(ctx) -> list[dict]:
    start = ctx.chart_window.start.replace(minute=0, second=0, microsecond=0)
    rows = []
    slot = start
    index = 0
    while slot < ctx.chart_window.end:
        rows.append(
            {
                "slot_datetime": slot.isoformat(),
                "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
                "PV-Prognose (kW)": 2.0 if 8 <= slot.hour <= 18 else 0.0,
                "Verbrauch-Prognose (kW)": 0.5,
                "Geplante Batterie-Aktion (kW)": 1.0 if index % 2 == 0 else -0.8,
                "Netzbezug (kW)": 0.3,
                "Simulierter SoC (%)": 40.0 + (index % 10),
                "Strompreis (Cent/kWh)": 20.0 + index % 5,
                "Einspeisevergütung (Cent/kWh)": 8.0,
                "Steuerbefehl": "Automatikbetrieb",
                "Preis extrapoliert": False,
            }
        )
        slot += timedelta(hours=1)
        index += 1
    return rows


ENERGY_COMPARISON = [
    {
        "name": "Pool",
        "baseline_kwh": 4.25,
        "matched_baseline_kwh": 3.5,
        "profile_fallback_kwh": 0.0,
        "optimization_kwh": 3.5,
        "optimization_source": "Tagesziel",
    },
    {"name": "Heizstab", "baseline_kwh": 1.0, "optimization_kwh": 2.0},
]

mode = st.session_state.get("cov_mode", "results")
ctx = build_live_chart_context(0, SEGMENT, now=NOW)
rows = _rows(ctx)
st.session_state["cov_row_count"] = len(rows)
st.session_state["cov_chart_slot_count"] = len(ctx.chart_window.slot_datetimes)
n = len(rows)
savings_info = {
    "optimized_cost_euro": 1.0,
    "matched_baseline_cost_euro": 1.4,
    "baseline_cost_euro": 1.5,
    "savings_matched_euro": 0.4,
    "optimized_rows": rows,
    "baseline_rows": rows,
    "hourly_optimized_cost_euro": [0.05] * n,
    "hourly_matched_baseline_cost_euro": [0.07] * n,
    "hourly_optimized_consumption_kwh": [0.5] * n,
    "hourly_matched_baseline_consumption_kwh": [0.6] * n,
    "energy_comparison": ENERGY_COMPARISON,
}

if mode == "results":
    render_optimization_results(
        savings_info,
        pd.DataFrame(rows),
        pd.DataFrame(rows),
        chart_context=ctx,
        optimization_matrix=rows,
    )
else:
    snapshot = {
        "completed_at": NOW.isoformat(),
        "savings": {
            "optimized_cost_euro": 1.0,
            "matched_baseline_cost_euro": 1.4,
            "baseline_cost_euro": 1.5,
        },
        "simulation_rows": [] if mode == "empty_snapshot" else rows,
        "baseline_rows": rows,
        "matched_baseline_rows": rows,
        "energy_comparison": ENERGY_COMPARISON,
    }
    bundle = build_optimization_display_bundle_from_snapshot(
        snapshot, cycle_offset=0, segment_index=SEGMENT, now=NOW
    )
    st.session_state["cov_bundle_none"] = bundle is None
    if bundle is not None:
        st.session_state["cov_bundle_rows"] = len(bundle.display_df)
        st.session_state["cov_bundle_matched"] = bundle.display_matched is not None
        render_optimization_chart1(bundle, chart_key="cov_chart1")
        render_live_display_data_basis_expander()

"""Historische Tages-Optimierung."""
from __future__ import annotations

from datetime import date

import streamlit as st
import pandas as pd

import config
import optimizer
from data import profile_manager
from ui.runtime_config import get_runtime_settings
from ui.simulation_results import (
    persist_simulation_debug,
    render_applied_targets,
    render_savings_metrics,
    render_simulation_details,
)
from ui.charts import render_optimization_chart


def render_historical_inputs() -> tuple[date, float]:
    min_date, max_date = profile_manager.get_historical_date_picker_bounds(months_back=12)
    default_date = max_date
    settings = get_runtime_settings()
    soc_min = float(settings["BATTERY_MIN_SOC"])
    soc_max = float(settings["BATTERY_MAX_SOC"])

    selected_date = st.sidebar.date_input(
        "Simulations-Tag",
        value=default_date,
        min_value=min_date,
        max_value=max_date,
        help=f"Wählbar: {min_date.strftime('%d.%m.%Y')} bis {max_date.strftime('%d.%m.%Y')}",
    )
    initial_soc = st.sidebar.slider(
        "Start-SoC für die Simulation (%)",
        min_value=soc_min,
        max_value=soc_max,
        value=soc_min,
        step=1.0,
        help=f"Erlaubter Bereich laut config.json: {soc_min:.0f}–{soc_max:.0f} %",
    )
    return selected_date, initial_soc


@st.cache_data(ttl=3600, show_spinner="Lade historische Tagesdaten...")
def load_historical_matrix(target_date: date):
    return profile_manager.build_historical_optimization_matrix(target_date)


def render_historical_day_info(meta: dict) -> None:
    totals = meta["historical_totals"]
    target_date = meta["target_date"]
    date_label = target_date.strftime("%d.%m.%Y") if hasattr(target_date, "strftime") else str(target_date)

    st.subheader(f"📅 Historische Tagesdaten: {date_label}")
    cols = st.columns(3 + len(totals))
    cols[0].metric("Gesamtverbrauch (real)", f"{meta.get('total_kwh', meta['baseload_kwh']):.1f} kWh")
    cols[1].metric("Grundlast", f"{meta['baseload_kwh']:.1f} kWh")
    cols[2].metric("PV-Ertrag (real)", f"{meta['pv_kwh']:.1f} kWh")
    for idx, consumer in enumerate(config.get_flexible_consumers(), start=3):
        kwh = totals.get(consumer["id"], 0.0)
        cols[idx].metric(f"{consumer['name']} (real)", f"{kwh:.1f} kWh")
    st.caption(
        "Baseline-Kosten nutzen den geloggten Gesamtverbrauch. "
        "Die Optimierung plant Grundlast plus steuerbare Verbraucher zu den **geloggten** Tageszielen "
        "(unabhängig von daily_target_source in config.json)."
    )


def render_historical_optimization_block(selected_date: date, initial_soc: float) -> None:
    try:
        matrix, meta = load_historical_matrix(selected_date)
    except Exception as e:
        st.error(f"🚨 Historische Daten konnten nicht geladen werden: {e}")
        return

    if not matrix or sum(row.get("expected_p_act", 0) for row in matrix) == 0:
        st.warning(
            f"⚠️ Für den {selected_date.strftime('%d.%m.%Y')} wurden keine Daten in "
            "cons_data_hourly.csv gefunden."
        )
        return

    render_historical_day_info(meta)

    with st.spinner("Berechne Optimierung für den historischen Tag..."):
        savings_info = optimizer.calculate_optimization_savings(
            matrix,
            initial_soc,
            consumer_daily_targets_kwh=meta.get("consumer_daily_targets_kwh"),
        )

    optimized_df = pd.DataFrame(savings_info["optimized_rows"])
    baseline_df = pd.DataFrame(savings_info["baseline_rows"])
    matched_baseline_df = pd.DataFrame(savings_info.get("matched_baseline_rows", []))

    planned_lines = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = f"{consumer['name']} (kW)"
        if col in optimized_df.columns:
            planned = optimized_df[col].sum()
            if planned > 0:
                planned_lines.append(f"**{consumer['name']}**: {planned:.1f} kWh")
    if planned_lines:
        st.info("🏭 Geplante flexible Verbraucher: " + " | ".join(planned_lines))

    render_savings_metrics(savings_info)
    render_optimization_chart(
        optimized_df,
        baseline_df,
        matched_baseline_df,
        hourly_savings_euro=savings_info.get("hourly_savings_euro"),
        hourly_matched_baseline_cost_euro=savings_info.get(
            "hourly_matched_baseline_cost_euro"
        ),
        hourly_optimized_cost_euro=savings_info.get("hourly_optimized_cost_euro"),
        hourly_matched_baseline_consumption_kwh=savings_info.get(
            "hourly_matched_baseline_consumption_kwh"
        ),
        hourly_optimized_consumption_kwh=savings_info.get(
            "hourly_optimized_consumption_kwh"
        ),
    )
    render_applied_targets(savings_info)
    persist_simulation_debug(
        savings_info,
        optimized_df,
        baseline_df,
        kind="historical_day",
        initial_soc=initial_soc,
        target_date=selected_date.isoformat(),
        historical_meta=meta,
        matched_baseline_df=matched_baseline_df,
    )
    render_simulation_details(
        optimized_df,
        title=f"📋 Simulations-Details ({selected_date.strftime('%d.%m.%Y')})",
    )

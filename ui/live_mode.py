"""Live-Modus: Sunset-Horizont-Simulation mit sunrise→sunrise-Chart."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st
import pandas as pd

from integrations import awattar_client
from data import consumer_targets, live_consumption, profile_manager
from runtime_store import run_state
from optimizer import schedule as optimization_schedule
import optimizer
from ui.chart_context import build_live_chart_context, live_now
from ui.history_navigation import get_s2_cycle_offset, get_s2_segment_index
from ui.help_hint import render_status_with_help
from ui.main_py_sync import MAIN_PY_SYNC_HELP, main_py_sync_status_message
from ui.runtime_config import reload_runtime_config, simulation_settings_fingerprint
from ui.simulation_results import (
    persist_simulation_debug,
    render_optimization_results,
)


def _render_main_py_sync_notice(
    wait_sec: int,
    reason: str,
    *,
    key: str,
    prominent: bool,
) -> None:
    render_status_with_help(
        main_py_sync_status_message(wait_sec, reason),
        MAIN_PY_SYNC_HELP,
        key=key,
        prominent=prominent,
    )


def _render_live_optimization_results(
    savings_info: dict,
    optimized_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    matched_baseline_df: pd.DataFrame | None,
    matrix: list,
    planning_window,
) -> None:
    chart_context = build_live_chart_context(
        get_s2_cycle_offset(),
        get_s2_segment_index(),
        now=live_now(),
        planning_window=planning_window,
        sim_rows=optimized_df.to_dict("records"),
    )
    render_optimization_results(
        savings_info,
        optimized_df,
        baseline_df,
        matched_baseline_df,
        chart_context=chart_context,
        optimization_matrix=matrix,
    )


def fetch_market_data():
    market_data = awattar_client.fetch_awattar_prices()
    if not market_data:
        st.error(
            "🚨 Fehler: Börsenstrompreise von aWATTar konnten nicht geladen werden. "
            "Abbruch der Simulation."
        )
        return None
    return market_data


def _live_optimization_cache_key(current_slot: str, main_state: dict | None) -> str:
    completed = (main_state or {}).get("completed_at", "")
    return f"{current_slot}|{completed}|{simulation_settings_fingerprint()}"


def _live_optimization_placeholder() -> st.delta_generator.DeltaGenerator:
    """Ein Slot für die Live-Optimierungs-UI (verhindert Fragment-Duplikate)."""
    if "live_optimization_placeholder" not in st.session_state:
        st.session_state.live_optimization_placeholder = st.empty()
    return st.session_state.live_optimization_placeholder


def _apply_main_run_to_live_df(
    optimized_df: pd.DataFrame,
    main_state: dict | None,
) -> pd.DataFrame:
    """Stunde 0 aus main.py übernehmen, wenn der Produktiv-Durchlauf zum Slot passt."""
    if optimized_df is None or optimized_df.empty or not main_state:
        return optimized_df
    if not optimization_schedule.completed_at_in_current_slot(main_state.get("completed_at")):
        return optimized_df
    rows = optimizer.overlay_main_run_on_rows(optimized_df.to_dict("records"), main_state)
    return pd.DataFrame(rows)


def render_optimization_savings_and_chart(current_soc: float) -> None:
    """MILP-Simulation im Sunset-2-Sunset-Modus."""
    reload_runtime_config()
    _live_optimization_fragment(current_soc)


def _live_results_cache_valid(
    cache_key: str,
    cached_key: str | None,
) -> bool:
    return (
        cached_key == cache_key
        and st.session_state.get("live_optimization_df") is not None
        and st.session_state.get("live_savings_info") is not None
        and not st.session_state["live_optimization_df"].empty
    )


def _render_cached_live_results(main_state: dict | None) -> None:
    cached_savings = st.session_state["live_savings_info"]
    cached_df = _apply_main_run_to_live_df(
        st.session_state["live_optimization_df"], main_state
    )
    baseline_df = pd.DataFrame(cached_savings.get("baseline_rows", []))
    matched_baseline_df = pd.DataFrame(cached_savings.get("matched_baseline_rows", []))
    _render_live_optimization_results(
        cached_savings,
        cached_df,
        baseline_df,
        matched_baseline_df,
        st.session_state.get("live_optimization_matrix", []),
        st.session_state.get("live_planning_window"),
    )


@st.fragment(run_every=timedelta(seconds=10))
def _live_optimization_fragment(current_soc: float) -> None:
    """MILP-Simulation: Einsparungen und Chart (Refresh nach main.py-Sync)."""
    current_slot = optimization_schedule.quarter_hour_slot_key()
    main_state = run_state.load_run_state()
    ready, reason, wait_sec = optimization_schedule.live_simulation_readiness(
        (main_state or {}).get("completed_at"),
    )
    cache_key = _live_optimization_cache_key(current_slot, main_state)
    cached_key = st.session_state.get("live_optimization_cache_key")
    has_cache = _live_results_cache_valid(cache_key, cached_key)

    if not ready:
        with _live_optimization_placeholder().container():
            _render_main_py_sync_notice(
                wait_sec,
                reason,
                key="main_py_sync_pending",
                prominent=True,
            )
            if has_cache:
                _render_cached_live_results(main_state)
        return

    if has_cache:
        with _live_optimization_placeholder().container():
            _render_cached_live_results(main_state)
        return

    planning_window = profile_manager.compute_live_planning_window()
    market_data = awattar_client.fetch_awattar_prices(planning_end=planning_window.end)
    if not market_data:
        st.error(
            "🚨 Fehler: Börsenstrompreise von aWATTar konnten nicht geladen werden. "
            "Abbruch der Simulation."
        )
        return

    matrix = profile_manager.build_live_planning_matrix(market_data, planning_window)
    from data.planning_window import sunrise_anchor_slot_index

    sunrise_soc_min_index = sunrise_anchor_slot_index(planning_window)

    snapshot = None
    if main_state and main_state.get("consumption_snapshot"):
        age = run_state.age_seconds(main_state)
        if age is not None and age <= optimization_schedule.QUARTER_HOUR_SECONDS * 1.5:
            snapshot = main_state["consumption_snapshot"]

    if snapshot is None:
        snapshot = live_consumption.fetch_live_consumption_snapshot()

    if snapshot:
        matrix = live_consumption.apply_live_snapshot_to_matrix(matrix, snapshot, hour_index=0)

    sim_soc = float(main_state.get("soc_percent", current_soc)) if main_state else current_soc
    targets = consumer_targets.resolve_consumer_daily_targets(matrix=matrix)
    savings_info = optimizer.calculate_optimization_savings(
        matrix,
        sim_soc,
        consumer_daily_targets_kwh=targets,
        sunrise_soc_min_index=sunrise_soc_min_index,
    )

    optimized_df = pd.DataFrame(savings_info["optimized_rows"])
    baseline_df = pd.DataFrame(savings_info["baseline_rows"])
    matched_baseline_df = pd.DataFrame(savings_info.get("matched_baseline_rows", []))
    optimized_df_raw = optimized_df.copy()
    optimized_df = _apply_main_run_to_live_df(optimized_df, main_state)
    st.session_state["live_optimization_cache_key"] = cache_key
    st.session_state["live_optimization_df"] = optimized_df
    st.session_state["live_savings_info"] = savings_info
    st.session_state["live_optimization_matrix"] = matrix
    st.session_state["live_planning_window"] = planning_window

    with _live_optimization_placeholder().container():
        _render_live_optimization_results(
            savings_info,
            optimized_df,
            baseline_df,
            matched_baseline_df,
            matrix,
            planning_window,
        )

    persist_simulation_debug(
        savings_info,
        optimized_df,
        baseline_df,
        kind="live",
        initial_soc=sim_soc,
        main_state=main_state,
        quarter_hour_slot=current_slot,
        sync_reason=reason,
        optimized_df_raw=optimized_df_raw,
        matched_baseline_df=matched_baseline_df,
    )

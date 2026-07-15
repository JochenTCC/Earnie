"""Live-Modus: Sunset-Horizont-Anzeige aus main.py-Persistenz (opt-in UI-Simulation)."""
from __future__ import annotations

import streamlit as st
import pandas as pd

from integrations import awattar_client
from data import consumer_targets, live_consumption, profile_manager
from runtime_store import run_state
from runtime_store.live_display_loader import (
    load_live_display_snapshot,
    snapshot_completed_at,
)
from optimizer import schedule as optimization_schedule
import optimizer
from ui.chart_context import build_live_chart_context, live_now
from ui.fragment_refresh import CHARTS_FRAGMENT_RUN_EVERY, main_sync_poll_interval_sec
from ui.history_navigation import get_s2_cycle_offset, get_s2_segment_index, render_s2_nav_buttons
from ui.help_hint import render_status_with_help
from ui.main_py_sync import MAIN_PY_SYNC_HELP, main_py_sync_status_message
from ui.runtime_config import reload_runtime_config, simulation_settings_fingerprint
from ui.chart_debug_capture import render_chart_debug_capture_controls
from ui.simulation_results import (
    SESSION_LIVE_DISPLAY_BUNDLE,
    build_optimization_display_bundle,
    build_optimization_display_bundle_from_snapshot,
    persist_simulation_debug,
    render_optimization_chart1,
    render_optimization_chart2,
    render_optimization_results_tail,
)

SESSION_OPT_IN_SIMULATION = "live_opt_in_simulation_confirmed"
SESSION_SNAPSHOT_CACHE_KEY = "live_display_snapshot_cache_key"


def _render_main_py_sync_notice(
    retry_sec: int,
    sync_wait_sec: int,
    reason: str,
    *,
    key: str,
    prominent: bool,
) -> None:
    render_status_with_help(
        main_py_sync_status_message(retry_sec, sync_wait_sec, reason),
        MAIN_PY_SYNC_HELP,
        key=key,
        prominent=prominent,
    )


def _snapshot_cache_key(
    current_slot: str,
    snapshot: dict | None,
    cycle_offset: int,
    segment_index: int,
) -> str:
    completed = snapshot_completed_at(snapshot) or ""
    return (
        f"{current_slot}|{completed}|{simulation_settings_fingerprint()}"
        f"|s2:{cycle_offset}:{segment_index}"
    )


def _store_bundle_from_snapshot(snapshot: dict) -> bool:
    bundle = build_optimization_display_bundle_from_snapshot(
        snapshot,
        cycle_offset=get_s2_cycle_offset(),
        segment_index=get_s2_segment_index(),
        now=live_now(),
    )
    if bundle is None:
        st.session_state.pop(SESSION_LIVE_DISPLAY_BUNDLE, None)
        return False
    st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] = bundle
    return True


def _refresh_snapshot_bundle(snapshot: dict | None, cache_key: str) -> None:
    if snapshot is None:
        st.session_state.pop(SESSION_LIVE_DISPLAY_BUNDLE, None)
        return
    if st.session_state.get(SESSION_SNAPSHOT_CACHE_KEY) == cache_key:
        return
    if _store_bundle_from_snapshot(snapshot):
        st.session_state[SESSION_SNAPSHOT_CACHE_KEY] = cache_key


def _render_main_down_notice(snapshot: dict | None, *, persisted_fresh: bool) -> None:
    completed = snapshot_completed_at(snapshot)
    if not completed:
        return
    label = completed[:16].replace("T", " ")
    if persisted_fresh:
        st.info(
            f"main.py nicht aktiv — Anzeige basiert auf letztem Lauf um **{label}**."
        )
    else:
        st.warning(
            f"Daten veraltet (>1 h) — main.py seit **{label}** nicht aktiv."
        )


def _render_opt_in_simulation_prompt() -> None:
    st.caption(
        "Ohne aktuellen main.py-Lauf kann eine **einmalige** UI-Simulation "
        "gestartet werden (forecast.solar, kein Loxone-Schreiben)."
    )
    if st.button("Einmalige Simulation starten", key="live_opt_in_simulation_btn"):
        st.session_state[SESSION_OPT_IN_SIMULATION] = True
        st.rerun()


def render_optimization_savings_and_chart(current_soc: float) -> None:
    """Cockpit-Charts aus main.py-Persistenz (opt-in UI-Simulation bei Ausfall)."""
    reload_runtime_config()
    _live_optimization_prepare_fragment(current_soc)
    _live_optimization_chart1_fragment(current_soc)
    render_s2_nav_buttons(now=live_now())
    _live_optimization_chart2_fragment()
    bundle = st.session_state.get(SESSION_LIVE_DISPLAY_BUNDLE)
    if bundle is not None:
        render_optimization_results_tail(bundle)


def _opt_in_cache_key(current_slot: str, main_state: dict | None) -> str:
    completed = (main_state or {}).get("completed_at", "")
    return f"opt_in|{current_slot}|{completed}|{simulation_settings_fingerprint()}"


def _opt_in_cache_valid(cache_key: str) -> bool:
    return (
        st.session_state.get("live_opt_in_cache_key") == cache_key
        and st.session_state.get("live_optimization_df") is not None
        and st.session_state.get("live_savings_info") is not None
        and not st.session_state["live_optimization_df"].empty
    )


def _store_opt_in_display_bundle(
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
    st.session_state[SESSION_LIVE_DISPLAY_BUNDLE] = build_optimization_display_bundle(
        savings_info,
        optimized_df,
        baseline_df,
        matched_baseline_df,
        chart_context=chart_context,
        optimization_matrix=matrix,
    )


def _run_opt_in_live_simulation(
    current_soc: float,
    main_state: dict | None,
    current_slot: str,
    sync_reason: str,
) -> None:
    """Einmalige UI-Simulation — nur nach expliziter Nutzerbestätigung."""
    cache_key = _opt_in_cache_key(current_slot, main_state)
    if _opt_in_cache_valid(cache_key):
        cached_savings = st.session_state["live_savings_info"]
        cached_df = st.session_state["live_optimization_df"]
        baseline_df = pd.DataFrame(cached_savings.get("baseline_rows", []))
        matched_baseline_df = pd.DataFrame(cached_savings.get("matched_baseline_rows", []))
        _store_opt_in_display_bundle(
            cached_savings,
            cached_df,
            baseline_df,
            matched_baseline_df,
            st.session_state.get("live_optimization_matrix", []),
            st.session_state.get("live_planning_window"),
        )
        return

    planning_window = profile_manager.compute_live_planning_window()
    market_data = awattar_client.fetch_awattar_prices(planning_end=planning_window.end)
    if not market_data:
        st.error(
            "🚨 Fehler: Börsenstrompreise von aWATTar konnten nicht geladen werden. "
            "Abbruch der Simulation."
        )
        st.session_state.pop(SESSION_LIVE_DISPLAY_BUNDLE, None)
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
        snapshot = live_consumption.fetch_live_consumption_snapshot(main_state)

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
    if main_state:
        rows = optimizer.overlay_main_run_on_rows(optimized_df.to_dict("records"), main_state)
        optimized_df = pd.DataFrame(rows)

    st.session_state["live_opt_in_cache_key"] = cache_key
    st.session_state["live_optimization_df"] = optimized_df
    st.session_state["live_savings_info"] = savings_info
    st.session_state["live_optimization_matrix"] = matrix
    st.session_state["live_planning_window"] = planning_window
    st.session_state.pop(SESSION_OPT_IN_SIMULATION, None)

    _store_opt_in_display_bundle(
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
        sync_reason=sync_reason,
        optimized_df_raw=optimized_df_raw,
        matched_baseline_df=matched_baseline_df,
    )


@st.fragment(run_every=CHARTS_FRAGMENT_RUN_EVERY)
def _live_optimization_prepare_fragment(current_soc: float) -> None:
    """Cockpit-Daten aus Persistenz laden (ohne Standard-Live-MILP)."""
    reload_runtime_config()
    current_slot = optimization_schedule.quarter_hour_slot_key()
    main_state = run_state.load_run_state()
    snapshot = load_live_display_snapshot()
    persisted_at = snapshot_completed_at(snapshot)
    poll_sec = main_sync_poll_interval_sec()
    _ready, reason, retry_sec, sync_wait_sec, persisted_fresh = (
        optimization_schedule.live_simulation_readiness(
            (main_state or {}).get("completed_at"),
            poll_sec=poll_sec,
            persisted_completed_at=persisted_at,
        )
    )
    cache_key = _snapshot_cache_key(
        current_slot,
        snapshot,
        get_s2_cycle_offset(),
        get_s2_segment_index(),
    )

    if reason == "wait_main":
        _render_main_py_sync_notice(
            retry_sec,
            sync_wait_sec,
            reason,
            key="main_py_sync_pending",
            prominent=True,
        )
        _refresh_snapshot_bundle(snapshot, cache_key)
        return

    if reason == "main_synced":
        if snapshot is None:
            st.session_state.pop(SESSION_LIVE_DISPLAY_BUNDLE, None)
            st.caption("Warte auf ersten main.py-Durchlauf für diesen Slot …")
            return
        _refresh_snapshot_bundle(snapshot, cache_key)
        return

    # main_down
    if persisted_fresh and snapshot:
        _render_main_down_notice(snapshot, persisted_fresh=True)
        _refresh_snapshot_bundle(snapshot, cache_key)
        return

    _render_main_down_notice(snapshot, persisted_fresh=False)
    if st.session_state.get(SESSION_OPT_IN_SIMULATION):
        _run_opt_in_live_simulation(current_soc, main_state, current_slot, reason)
        return

    if snapshot:
        _refresh_snapshot_bundle(snapshot, cache_key)
    else:
        st.session_state.pop(SESSION_LIVE_DISPLAY_BUNDLE, None)
        st.warning("Warte auf ersten main.py-Durchlauf.")
    _render_opt_in_simulation_prompt()


@st.fragment(run_every=CHARTS_FRAGMENT_RUN_EVERY)
def _live_optimization_chart1_fragment(current_soc: float) -> None:
    bundle = st.session_state.get(SESSION_LIVE_DISPLAY_BUNDLE)
    if bundle is not None:
        render_optimization_chart1(bundle)
        render_chart_debug_capture_controls(current_soc)


@st.fragment(run_every=CHARTS_FRAGMENT_RUN_EVERY)
def _live_optimization_chart2_fragment() -> None:
    bundle = st.session_state.get(SESSION_LIVE_DISPLAY_BUNDLE)
    if bundle is not None:
        render_optimization_chart2(bundle)

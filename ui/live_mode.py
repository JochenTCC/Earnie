"""Live-Modus: Sunset-Horizont-Simulation mit sunrise→sunrise-Chart."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st
import pandas as pd

from integrations import awattar_client
from data import consumer_targets, live_consumption, profile_manager
from runtime_store import history_timeline, run_state
from optimizer import schedule as optimization_schedule
import optimizer
from ui.chart_context import build_live_chart_context
from ui.history_navigation import (
    get_s2_cycle_offset,
    get_s2_segment_index,
    render_history_navigation,
)
from ui.runtime_config import reload_runtime_config, simulation_settings_fingerprint
from ui.simulation_results import (
    persist_simulation_debug,
    render_history_timeline_results,
    render_optimization_results,
)


def _render_live_captions(
    *,
    main_state: dict | None,
    snapshot: dict | None,
    sim_soc: float,
    sync_note: str,
) -> None:
    if main_state:
        st.caption(
            f"📡 **Aktuelle Stunde:** Verbrauch aus "
            f"{'main.py' if main_state.get('consumption_snapshot') and snapshot == main_state.get('consumption_snapshot') else 'Loxone live'} · "
            f"SoC für Simulation: **{sim_soc:.1f} %** (main.py) · "
            f"Stunde 0 = Produktiv-Durchlauf main.py — übrige Stunden simuliert{sync_note}."
        )
    elif snapshot:
        st.caption(
            f"📡 **Aktuelle Stunde (Live):** Grundlast {snapshot['baseload_kw']:.2f} kW · "
            f"Gesamt {snapshot['house_kw']:.2f} kW · PV {snapshot['pv_kw']:.2f} kW — "
            f"Rest des Horizonts aus Profil-Prognose{sync_note}."
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


def _clear_live_optimization_placeholder() -> None:
    st.session_state.pop("live_optimization_placeholder", None)


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


def _render_history_timeline(offset_days: int) -> None:
    try:
        result = history_timeline.build_history_timeline(offset_days)
    except ValueError as exc:
        st.error(str(exc))
        return
    render_history_timeline_results(result)


def render_optimization_savings_and_chart(current_soc: float) -> None:
    """MILP-Simulation (Live) oder Produktiv-Historie mit gemeinsamer Navigation."""
    reload_runtime_config()
    offset_days = render_history_navigation()
    if offset_days > 0:
        _clear_live_optimization_placeholder()
        _render_history_timeline(offset_days)
        return
    _live_optimization_fragment(current_soc)


def _render_pending_live_sync(wait_sec: int, reason: str) -> bool:
    """Zeigt vorherige Simulation, solange auf main.py gewartet wird."""
    cached_df = st.session_state.get("live_optimization_df")
    cached_savings = st.session_state.get("live_savings_info")
    if cached_df is None or cached_savings is None or cached_df.empty:
        return False

    baseline_df = pd.DataFrame(cached_savings.get("baseline_rows", []))
    matched_baseline_df = pd.DataFrame(cached_savings.get("matched_baseline_rows", []))
    main_state = run_state.load_run_state()
    cached_df = _apply_main_run_to_live_df(cached_df, main_state)
    with _live_optimization_placeholder().container():
        _render_live_captions(
            main_state=main_state,
            snapshot=(main_state or {}).get("consumption_snapshot"),
            sim_soc=float((main_state or {}).get("soc_percent", 0.0) or 0.0),
            sync_note="",
        )
        _render_live_optimization_results(
            cached_savings, cached_df, baseline_df, matched_baseline_df,
            st.session_state.get("live_optimization_matrix", []),
            st.session_state.get("live_planning_window"),
        )
        if reason == "delay":
            st.caption(
                f"⏳ **Synchronisation mit main.py:** Aktualisierung in ca. **{wait_sec} s** "
                f"(1 Min nach Viertelstunden-Wechsel)."
            )
        else:
            st.caption(
                f"⏳ **Warte auf main.py-Durchlauf** für den aktuellen Slot "
                f"(noch ca. **{wait_sec} s**)."
            )
    return True


@st.fragment(run_every=timedelta(seconds=10))
def _live_optimization_fragment(current_soc: float) -> None:
    """MILP-Simulation: Einsparungen und Chart (Refresh nach main.py-Sync)."""
    current_slot = optimization_schedule.quarter_hour_slot_key()
    main_state = run_state.load_run_state()
    cache_key = _live_optimization_cache_key(current_slot, main_state)
    cached_key = st.session_state.get("live_optimization_cache_key")

    if (
        cached_key == cache_key
        and st.session_state.get("live_optimization_df") is not None
        and st.session_state.get("live_savings_info") is not None
        and not st.session_state["live_optimization_df"].empty
    ):
        cached_savings = st.session_state["live_savings_info"]
        cached_df = _apply_main_run_to_live_df(
            st.session_state["live_optimization_df"], main_state
        )
        baseline_df = pd.DataFrame(cached_savings.get("baseline_rows", []))
        matched_baseline_df = pd.DataFrame(cached_savings.get("matched_baseline_rows", []))
        with _live_optimization_placeholder().container():
            _render_live_captions(
                main_state=main_state,
                snapshot=(main_state or {}).get("consumption_snapshot"),
                sim_soc=float((main_state or {}).get("soc_percent", current_soc) or current_soc),
                sync_note="",
            )
            _render_live_optimization_results(
                cached_savings,
                cached_df,
                baseline_df,
                matched_baseline_df,
                st.session_state.get("live_optimization_matrix", []),
                st.session_state.get("live_planning_window"),
            )
        return

    ready, reason, wait_sec = optimization_schedule.live_simulation_readiness(
        (main_state or {}).get("completed_at"),
    )
    if not ready:
        if _render_pending_live_sync(wait_sec, reason):
            return
        st.info(
            f"⏳ Live-Simulation startet nach Synchronisation mit **main.py** "
            f"(noch ca. **{wait_sec} s**)."
        )
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

    sync_note = ""
    if reason == "main_synced":
        sync_note = " · synchron mit main.py"
    elif reason == "fallback":
        sync_note = " · main.py für diesen Slot nicht verfügbar (Live-Fallback)"

    with _live_optimization_placeholder().container():
        _render_live_captions(
            main_state=main_state,
            snapshot=snapshot,
            sim_soc=sim_soc,
            sync_note=sync_note,
        )

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

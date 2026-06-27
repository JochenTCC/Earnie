"""Live-Modus: 24h-Simulation und Plausibilitäts-Debug."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st
import pandas as pd

from integrations import awattar_client
from data import consumer_targets, live_consumption, profile_manager
from runtime_store import history_timeline, live_optimization_debug, run_state
from optimizer import schedule as optimization_schedule
import optimizer
from ui.history_navigation import render_history_navigation
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
        render_optimization_results(
            cached_savings, cached_df, baseline_df, matched_baseline_df
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


def render_plausibility_debug_panel(main_state: dict | None) -> None:
    """Zeigt Abgleich main.py vs. App-Simulation und Pfad zum Debug-Snapshot."""
    debug = live_optimization_debug.load_debug_snapshot(kind="live")
    if not debug or debug.get("simulation_kind") != "live":
        return

    path = live_optimization_debug.debug_file_path("live")
    plaus = debug.get("plausibility") or {}

    with st.expander("🔍 Plausibilität main.py ↔ App-Simulation"):
        st.caption(
            f"Debug-Snapshot: `{path}` · Slot **{debug.get('quarter_hour_slot', '?')}** · "
            f"Sync: **{debug.get('sync_reason', '?')}**"
        )
        if main_state and debug.get("main_run_completed_at") != main_state.get("completed_at"):
            st.warning(
                "Der gespeicherte Snapshot stammt von einem anderen main.py-Lauf als dem aktuellen Panel."
            )

        if plaus.get("available"):
            if plaus.get("aligned"):
                st.success("Stunde 0 (nach main.py-Overlay) stimmt mit dem Produktiv-Durchlauf überein.")
            else:
                st.error("Abweichungen in Stunde 0 (nach Overlay):")
                for issue in plaus.get("issues", []):
                    st.markdown(f"- {issue}")

        plaus_raw = debug.get("plausibility_before_overlay") or {}
        if plaus_raw.get("available") and not plaus_raw.get("aligned"):
            st.info(
                "Vor dem main.py-Overlay wich die reine App-Simulation in Stunde 0 ab — "
                "das ist erwartbar, wenn main.py die maßgeblichen Produktivwerte liefert."
            )
            with st.container():
                st.markdown("**Roh-Simulation Stunde 0 vs. main.py:**")
                for issue in plaus_raw.get("issues", []):
                    st.markdown(f"- {issue}")

        st.caption(
            "Die Datei enthält `main_run`, `simulation_rows_raw`, `simulation_rows` (24h) "
            "und `baseline_rows` zum gemeinsamen Nachrechnen."
        )


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
            render_optimization_results(
                cached_savings, cached_df, baseline_df, matched_baseline_df
            )
            render_plausibility_debug_panel(main_state)
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

    market_data = fetch_market_data()
    if market_data is None:
        return

    _, _, matrix = profile_manager.get_forecast_vectors(market_data)

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
    )

    optimized_df = pd.DataFrame(savings_info["optimized_rows"])
    baseline_df = pd.DataFrame(savings_info["baseline_rows"])
    matched_baseline_df = pd.DataFrame(savings_info.get("matched_baseline_rows", []))
    optimized_df_raw = optimized_df.copy()
    optimized_df = _apply_main_run_to_live_df(optimized_df, main_state)
    st.session_state["live_optimization_cache_key"] = cache_key
    st.session_state["live_optimization_df"] = optimized_df
    st.session_state["live_savings_info"] = savings_info

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

        render_optimization_results(
            savings_info, optimized_df, baseline_df, matched_baseline_df
        )
        render_plausibility_debug_panel(main_state)

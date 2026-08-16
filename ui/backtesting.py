"""Backtesting-Auswertung und UI-Start aus scripts/run_backtesting.py."""
from __future__ import annotations

import time

import streamlit as st
import pandas as pd

import config
from data import cons_data_store
from runtime_store.persist_paths import resolve_backtesting_log_dir
from simulation import backtesting_log
from simulation.backtesting_fingerprint import fingerprint_for_current_config
from simulation.backtesting_progress import (
    ProgressEtaTracker,
    build_progress_display_rows,
    format_progress_bar_caption,
    ordered_backtesting_result_ids,
)
from simulation.engine import HISTORICAL_REFERENCE_ID, plan_per_scenario_reference_tasks
from simulation.horizon_mode import DEFAULT_HORIZON_MODE, FIXED_24H, SUNRISE_WINDOW
from ui.backtesting_charts import scenario_monthly_cost_chart
from ui.backtesting_cons_data import render_cons_data_section
from ui.backtesting_deviation_list import render_deviation_list
from ui.backtesting_results_helpers import (
    build_annual_cost_rows,
    build_scenario_consumption_rows,
    format_test_run_caption,
    nav_bounds_from_period,
    ordered_monthly_chart_labels,
    reference_kwh_for_period,
    scenario_consumption_subheader,
)
from ui.backtesting_runner import (
    auto_backtesting_workers,
    count_backtesting_parallel_tasks,
    default_progress_file_path,
    run_backtesting_subprocess,
    suggest_test_month,
)
from ui.backtesting_time_ranges import render_time_range_help
from ui.doc_links import DocLink, get_page_docs, markdown_doc_link
from ui.scenario_form_helpers import ordered_user_scenario_ids
from scripts.run_backtesting import BACKTESTING_YEAR, HISTORICAL_REFERENCE_LABEL
_LEGACY_STALE_WARNING = (
    "Älterer Szenario-Explorer-Lauf ohne Konfigurations-Fingerabdruck — "
    "bitte einmal neu berechnen."
)
_MISMATCH_STALE_WARNING = (
    "Gespeicherter Szenario-Explorer-Lauf passt nicht zur aktuellen Konfiguration. "
    "Bitte neu berechnen."
)
_STALE_CAPTION = (
    "Die aktuelle Konfiguration weicht vom gespeicherten Lauf ab. "
    "Ergebnisse unten sind veraltet."
)
_HORIZON_STALE_WARNING = (
    "Der gewählte Planungshorizont weicht vom gespeicherten Szenario-Explorer-Lauf ab. "
    "Die Ergebnisse unten sind ungültig — bitte neu berechnen oder die "
    "ursprüngliche Horizont-Auswahl wiederherstellen."
)
_HORIZON_RESULTS_HIDDEN_INFO = (
    "Gespeicherte Ergebnisse sind ausgeblendet: Der gewählte Planungshorizont "
    "weicht vom letzten Lauf ab. Zur Anzeige die ursprüngliche Auswahl "
    "wiederherstellen oder neu berechnen."
)
_BACKTESTING_LOG_ANCHOR_KEY = "_backtesting_log_anchor"


@st.cache_data(ttl=60, show_spinner="Lade Szenario-Explorer-Log...")
def load_backtesting_data():
    return backtesting_log.load_backtesting_log()


def scenario_labels_map() -> dict[str, str]:
    return config.get_scenario_labels()


def try_get_backtesting_scenarios() -> tuple[dict[str, dict] | None, str | None]:
    """Löst Szenarien auf; bei Konfigurationsfehler (None, Fehlermeldung)."""
    try:
        return config.get_backtesting_scenarios(), None
    except ValueError as exc:
        return None, str(exc)




def log_stale_reason(meta: dict) -> str | None:
    """'legacy' | 'mismatch' wenn veraltet, sonst None."""
    stored = meta.get("config_fingerprint")
    if not stored:
        return "legacy"
    period = meta.get("period")
    try:
        current = fingerprint_for_current_config(period=period)
    except ValueError:
        return "mismatch"
    if stored != current:
        return "mismatch"
    return None


def log_matches_current_config(meta: dict) -> bool:
    return log_stale_reason(meta) is None






def render_configured_scenarios() -> None:
    st.subheader("Konfigurierte Szenarien")
    scenarios, error = try_get_backtesting_scenarios()
    if error:
        st.error(_format_config_error(error))
        return
    labels = scenario_labels_map()
    for scenario_id in ordered_user_scenario_ids(
        scenarios,
        live_scenario_id=config.get_live_scenario_id(),
        labels=labels,
    ):
        st.write(f"- **{labels.get(scenario_id, scenario_id)}** (`{scenario_id}`)")
    if not scenarios:
        st.caption(
            "Keine aktiven Szenarien für den Szenario-Explorer. "
            "Im Szenarienkonfigurator „Aktiv für Szenario-Explorer“ setzen."
        )

_HORIZON_MODE_LABELS = {
    FIXED_24H: "24h (E-Auto-Anker)",
    SUNRISE_WINDOW: "Sunrise Now→SA₂ (Standard, wie Live)",
}


def log_horizon_mode(meta: dict | None) -> str | None:
    if meta is None:
        return None
    # Missing key = legacy runs before horizon_mode was persisted (were fixed_24h).
    return meta.get("period", {}).get("horizon_mode", FIXED_24H)


def horizon_selection_stale(meta: dict | None, selected_horizon: str) -> bool:
    log_horizon = log_horizon_mode(meta)
    if log_horizon is None:
        return False
    return selected_horizon != log_horizon


def sync_horizon_selectbox_from_log(meta: dict) -> None:
    """Bindet die Planungshorizont-Auswahl an den gespeicherten Backtesting-Lauf."""
    anchor = str(meta.get("created_at", ""))
    if st.session_state.get(_BACKTESTING_LOG_ANCHOR_KEY) == anchor:
        return
    st.session_state.backtesting_horizon_mode = log_horizon_mode(meta)
    st.session_state[_BACKTESTING_LOG_ANCHOR_KEY] = anchor
































def render_backtesting_block() -> None:
    log_exists = backtesting_log.log_exists()
    meta: dict | None = None
    log_stale = False
    stale_reason: str | None = None

    if log_exists:
        try:
            meta, _hourly = load_backtesting_data()
            stale_reason = log_stale_reason(meta)
            log_stale = stale_reason is not None
        except Exception as exc:
            st.error(f"Szenario-Explorer-Log konnte nicht geladen werden: {exc}")
            log_exists = False

    cons_ready = render_cons_data_section()
    _warn_if_house_profile_imports_short_for_se()

    render_configured_scenarios()

    if log_exists and meta is not None and log_stale:
        warning = (
            _LEGACY_STALE_WARNING if stale_reason == "legacy" else _MISMATCH_STALE_WARNING
        )
        st.warning(warning)

    horizon_stale = render_backtesting_run_controls(
        log_exists=log_exists,
        log_stale=log_stale,
        stale_reason=stale_reason,
        cons_data_ready=cons_ready,
        meta=meta,
    )

    if not log_exists or meta is None:
        if not log_exists:
            st.info(
                "Noch kein Szenario-Explorer-Lauf vorhanden. "
                "Starte die Berechnung mit dem Button oben."
            )
        return

    if horizon_stale:
        st.info(_HORIZON_RESULTS_HIDDEN_INFO)
        return

    _render_backtesting_results(meta, _hourly)

from ui.backtesting_run import (
    _execute_backtesting_run,
    _format_backtesting_run_error,
    _format_config_error,
    _render_imported_pv_run_notice,
    _warn_if_house_profile_imports_short_for_se,
    render_backtesting_run_controls,
    validate_backtesting_config,
)
from ui.backtesting_results import (
    _annual_cost_details_markdown,
    _deviation_labels_map,
    _hourly_timestamps_for_scenario,
    _optimized_scenario_ids,
    _reference_kwh_for_meta,
    _render_backtesting_results,
    _render_imported_pv_results_notice,
    render_annual_cost_table,
    render_backtesting_log_caption,
    render_backtesting_monthly_chart,
    render_scenario_consumption_table,
)

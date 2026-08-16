"""Backtesting results tables and charts UI."""
from __future__ import annotations

from ui.backtesting import _HORIZON_MODE_LABELS

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



def _render_imported_pv_results_notice(meta: dict) -> None:
    labels = meta.get("labels") or scenario_labels_map()
    used = meta.get("imported_pv_scenario_ids") or []
    missing = meta.get("imported_pv_missing_scenario_ids") or []
    if used:
        names = ", ".join(labels.get(sid, sid) for sid in used)
        st.info(
            f"Dieser Lauf nutzte importiertes PV-Profil (statt PV aus Wetterdaten) für: {names}."
        )
    if missing:
        names = ", ".join(labels.get(sid, sid) for sid in missing)
        st.warning(
            f"Szenarien wollten importiertes PV, hatten aber keine ausreichende CSV "
            f"(≥12 Monate; Fallback: synthetisches PV aus Wetterdaten): {names}."
        )

def render_backtesting_log_caption(meta: dict) -> None:
    st.subheader("Szenario-Explorer-Log")
    st.caption(f"Ergebnisdatei: `{backtesting_log.backtesting_log_json_path()}`")
    created = meta.get("created_at", "")[:19].replace("T", " ")
    period = meta.get("period", {})
    horizon = period.get("horizon_mode", FIXED_24H)
    st.caption(
        f"Erstellt: {created} UTC · "
        f"Zeitraum: {period.get('start', '?')} – {period.get('end', '?')} "
        f"({period.get('windows', '?')} Fenster) · "
        f"Horizont: {_HORIZON_MODE_LABELS.get(horizon, horizon)}"
    )
    caption = format_test_run_caption(period)
    if caption:
        st.warning(caption)

def _hourly_timestamps_for_scenario(
    hourly_df: pd.DataFrame,
    scenario_id: str,
    nav_bounds: tuple | None,
) -> list[str]:
    part = hourly_df.loc[hourly_df["scenario_id"] == scenario_id].copy()
    if part.empty or "ts" not in part.columns:
        return []
    part["ts"] = pd.to_datetime(part["ts"])
    if nav_bounds is not None:
        start, end = nav_bounds
        part = part[(part["ts"] >= start) & (part["ts"] <= end)]
    return [pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M:%S") for ts in part["ts"]]

def _optimized_scenario_ids(meta: dict, scenarios: dict[str, dict]) -> list[str]:
    ref_id = meta.get("reference_id")
    return [
        scenario_id
        for scenario_id in meta.get("scenario_ids", [])
        if scenario_id != ref_id
        and isinstance(scenarios.get(scenario_id, {}).get("_house_profile"), dict)
    ]

def _reference_kwh_for_meta(meta: dict) -> float | None:
    period = meta.get("period", {})
    if not cons_data_store.is_cons_data_populated():
        return None
    cons_df = cons_data_store.load_cons_data()
    return reference_kwh_for_period(cons_df, period)

def _annual_cost_details_markdown() -> str:
    """Clickable doc links for the Jahres Verbrauch caption."""
    parts: list[str] = []
    explorer_docs = get_page_docs("scenario-explorer")
    if explorer_docs is not None:
        parts.append(markdown_doc_link(explorer_docs.primary))
        jahres = next(
            (
                link
                for link in explorer_docs.secondaries
                if link.fragment == "gesamtkosten-jahres-verbrauch-kwh"
            ),
            None,
        )
        if jahres is not None:
            parts.append(markdown_doc_link(jahres))
    parts.append(
        markdown_doc_link(
            DocLink(
                "Tarife und Preise nachrechnen",
                "docs/referenz/tarife-quellen.md",
            )
        )
    )
    return " · ".join(parts)

def render_annual_cost_table(meta: dict) -> None:
    st.subheader("Gesamtkosten und -Verbrauch")
    ref_kwh = _reference_kwh_for_meta(meta)
    rows = build_annual_cost_rows(meta, ref_kwh)
    if not rows:
        st.info("Keine Gesamtkosten im Log.")
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    fee_map = meta.get("monthly_fee_by_scenario") or {}
    has_fees = any(float(v or 0) > 0 for v in fee_map.values())
    fee_note = (
        " Jahres-/Monatskosten inkl. **Näherung Fixkosten** aus dem Tarifkatalog "
        "(nicht Live-MILP). Fake-Jahresrechnungen: Ordner `invoices/` neben dem Log. "
        if has_fees
        else " Fake-Jahresrechnungen: Ordner `invoices/` neben dem Log. "
    )
    st.caption(
        "**Jahres Verbrauch:** Bei „Historisch“ Summe des Ist-Verbrauchs aus "
        "`cons_data` (Zähler). Bei Referenz- und Optimierungszeilen Summe aus dem "
        "Hausprofil-Modell bzw. der gelieferten Optimierungsenergie — "
        "Abweichungen zu Historisch sind erwartbar, wenn Ist ≠ Modell."
        + fee_note
        + "Volumetrische **Netznutzung Arbeitspreis** (Hausprofil) fließt in die "
        "Kosten ein und erscheint in Fake-Jahresrechnungen getrennt. "
        "Abweichung >5% vs. Live-Referenz → Warnung in Spalte Hinweis "
        "(Config-Dump über Info / About → Kontakt). "
        f"Details: {_annual_cost_details_markdown()}."
    )

def render_scenario_consumption_table(meta: dict, hourly_df: pd.DataFrame | None = None) -> None:
    period = meta.get("period", {})
    st.subheader(scenario_consumption_subheader(period))
    st.caption(
        "Summe der gelieferten kWh über alle 24h-Fenster im Lauf "
        "(Grundlast + flexible Verbraucher). Δ ≈ 0 bei zeitlicher Lastverschiebung mit gleicher Spec-Energie."
    )
    ref_kwh = _reference_kwh_for_meta(meta)
    scenarios, scenario_error = try_get_backtesting_scenarios()
    timestamps: list[str] | None = None
    if hourly_df is not None and scenarios and not scenario_error:
        scenario_ids = _optimized_scenario_ids(meta, scenarios)
        if scenario_ids:
            timestamps = _hourly_timestamps_for_scenario(
                hourly_df,
                scenario_ids[0],
                nav_bounds_from_period(period),
            )
    rows = build_scenario_consumption_rows(
        meta,
        ref_kwh,
        hourly_df=hourly_df,
        scenarios=scenarios if not scenario_error else None,
        timestamps=timestamps,
    )
    if not rows:
        st.info("Keine Szenarien im Log.")
        return
    has_totals = any(
        row["Optimiert (kWh)"] != "—"
        for row in rows
        if row["Plausibilität"] != "—"
    )
    if not has_totals:
        st.info(
            "Verbrauchssummen fehlen in diesem Log (älterer Lauf). "
            "Bitte Szenario-Explorer neu berechnen."
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

def render_backtesting_monthly_chart(meta: dict) -> None:
    st.subheader("Monatlicher Kostenvergleich")
    monthly = meta.get("summary", {}).get("monthly_eur", {})
    if not monthly:
        st.info("Keine Monatswerte im Log.")
        return
    df = pd.DataFrame(monthly).T.round(2)
    chart_columns = [
        col for col in df.columns if not col.startswith("Einsparung")
    ]
    if not chart_columns:
        return
    chart_columns = ordered_monthly_chart_labels(meta, chart_columns)
    chart_monthly = {
        month: {col: float(df.loc[month, col]) for col in chart_columns}
        for month in df.index
    }
    st.plotly_chart(
        scenario_monthly_cost_chart(chart_monthly, scenario_order=chart_columns),
        width="stretch",
    )
    fee_map = meta.get("monthly_fee_by_scenario") or {}
    if any(float(v or 0) > 0 for v in fee_map.values()):
        st.caption(
            "Monatswerte inkl. Näherung Fixkosten (eine volle Gebühr pro "
            "Kalendermonat). Volumetrische **Netznutzung Arbeitspreis** "
            "(Hausprofil) ist in den Energiekosten enthalten. Nachrechnen: "
            "Tarife und Preise nachrechnen."
        )
    else:
        st.caption(
            "Volumetrische **Netznutzung Arbeitspreis** (Hausprofil) ist in den "
            "Energiekosten enthalten. Nachrechnen: Tarife und Preise nachrechnen."
        )

def _deviation_labels_map(meta: dict) -> dict[str, str]:
    labels = scenario_labels_map()
    labels.update(meta.get("labels", {}))
    return labels

def _render_backtesting_results(meta: dict, hourly_df: pd.DataFrame) -> None:
    from runtime_store.cloud_demo import render_cloud_demo_feedback_banner

    render_backtesting_log_caption(meta)
    _render_imported_pv_results_notice(meta)
    render_cloud_demo_feedback_banner()
    render_annual_cost_table(meta)
    render_backtesting_monthly_chart(meta)
    render_scenario_consumption_table(meta, hourly_df)
    render_deviation_list(
        meta,
        _deviation_labels_map(meta),
        log_dir=resolve_backtesting_log_dir(),
        hourly_df=hourly_df,
    )

"""Backtesting run controls and execution UI."""
from __future__ import annotations

import config
from ui.backtesting import (
    _HORIZON_MODE_LABELS,
    _HORIZON_STALE_WARNING,
    horizon_selection_stale,
    load_backtesting_data,
    log_horizon_mode,
    scenario_labels_map,
    sync_horizon_selectbox_from_log,
    try_get_backtesting_scenarios,
)

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



def validate_backtesting_config() -> str | None:
    """None wenn auflösbar, sonst Fehlermeldung für die UI."""
    from house_config.tariff_plausibility import (
        collect_tariff_plausibility_errors,
        format_tariff_plausibility_errors,
    )
    from runtime_store.persist_paths import (
        resolve_backtesting_scenarios_json_path,
        resolve_tariffs_json_path,
        resolve_tariffs_schema_template_path,
    )

    tariff_errors = collect_tariff_plausibility_errors(
        tariffs_path=resolve_tariffs_json_path(),
        scenarios_path=resolve_backtesting_scenarios_json_path(),
        schema_path=resolve_tariffs_schema_template_path(),
    )
    if tariff_errors:
        return format_tariff_plausibility_errors(tariff_errors)

    _, error = try_get_backtesting_scenarios()
    return error

def _format_config_error(message: str) -> str:
    if "export_tariff_id" in message or "import_tariff_id" in message:
        return (
            f"{message}\n\n"
            "Prüfe im **Szenarienkonfigurator → Runtime**, ob Bezugs- und Einspeisetarif "
            "noch im Tarifkatalog existieren."
        )
    return message

def _format_backtesting_run_error(output: str) -> str | None:
    if "cons_data.csv" in output:
        return (
            "Szenario-Explorer benötigt Verbrauchsdaten in `cons_data.csv` "
            f"unter `{resolve_backtesting_log_dir()}` (bzw. dem in der Config "
            "konfigurierten `path_cons_data`). "
            "Für Greenfield: Daten per `scripts/generate_cons_data.py` erzeugen "
            "oder aus `runtime/` übernehmen."
        )
    if "No module named scripts" in output:
        return (
            "Szenario-Explorer-Subprocess konnte das Skript nicht starten. "
            "Streamlit neu starten; unter VS Code `subProcess: false` in launch.json "
            "verwenden (bereits für Greenfield-Launch gesetzt)."
        )
    return None

def _prepare_backtesting_run_context() -> dict | None:
    config_error = validate_backtesting_config()
    if config_error:
        st.error(_format_config_error(config_error))
        return None
    from runtime_store.cloud_demo import mark_cloud_demo_se_simulation_started

    mark_cloud_demo_se_simulation_started()
    scenarios, _ = try_get_backtesting_scenarios()
    live_scenario_id = config.get_live_scenario_id()
    parallel_task_count = count_backtesting_parallel_tasks(
        scenarios or {},
        live_scenario_id=live_scenario_id,
    )
    scenario_labels = config.get_scenario_labels()
    own_ref_flags = config.get_own_reference_flags()
    _, extra_ref_labels, extra_ref_specs = plan_per_scenario_reference_tasks(
        scenarios or {},
        live_scenario_id=live_scenario_id,
        scenario_labels=scenario_labels,
        own_reference_by_scenario=own_ref_flags,
    )
    return {
        "workers": auto_backtesting_workers(parallel_task_count),
        "progress_file": default_progress_file_path(),
        "labels_for_order": {
            HISTORICAL_REFERENCE_ID: HISTORICAL_REFERENCE_LABEL,
            **scenario_labels,
            **extra_ref_labels,
        },
        "preferred_progress_ids": ordered_backtesting_result_ids(
            scenarios or {},
            live_scenario_id=live_scenario_id,
            extra_ref_ids=[ref_id for ref_id, _params, _label in extra_ref_specs],
        ),
        "eta_tracker": ProgressEtaTracker(),
    }


def _render_backtesting_progress(snapshot: dict, ctx: dict, progress_host) -> None:
    rows = build_progress_display_rows(
        ctx["preferred_progress_ids"],
        snapshot,
        ctx["labels_for_order"],
    )
    if not rows:
        return
    now = time.monotonic()
    workers = ctx["workers"]
    eta_tracker = ctx["eta_tracker"]
    with progress_host.container():
        active_count = sum(
            1
            for row in rows
            if row["placeholder"] or row["total"] <= 0 or row["current"] < row["total"]
        )
        if workers > 1:
            st.caption(
                f"Parallele Berechnung: {workers} Worker · "
                f"{active_count} aktive Tasks"
            )
        for row in rows:
            eta_sec = None
            if not row["placeholder"] and row["total"] > 0:
                eta_sec = eta_tracker.update(
                    row["result_id"],
                    current=row["current"],
                    total=row["total"],
                    now_monotonic=now,
                )
            st.caption(
                format_progress_bar_caption(
                    label=row["label"],
                    current=row["current"],
                    total=row["total"],
                    phase=row["phase"],
                    placeholder=row["placeholder"],
                    eta_seconds=eta_sec,
                )
            )
            if row["placeholder"] or row["total"] <= 0:
                st.progress(0.0)
            else:
                st.progress(min(row["current"] / row["total"], 1.0))


def _execute_backtesting_run(
    *,
    start_month: int | None = None,
    end_month: int | None = None,
    status_label: str,
    horizon_mode: str = DEFAULT_HORIZON_MODE,
) -> None:
    ctx = _prepare_backtesting_run_context()
    if ctx is None:
        return
    with st.status(status_label, expanded=True) as status:
        progress_host = st.empty()

        def _on_progress(snapshot: dict) -> None:
            _render_backtesting_progress(snapshot, ctx, progress_host)

        exit_code, output = run_backtesting_subprocess(
            start_month=start_month,
            end_month=end_month,
            progress_file=ctx["progress_file"],
            horizon_mode=horizon_mode,
            workers=ctx["workers"],
            on_progress=_on_progress,
        )
        if exit_code == 0:
            status.update(label="Szenario-Explorer abgeschlossen", state="complete")
            load_backtesting_data.clear()
            st.rerun()
            return
        status.update(label="Szenario-Explorer fehlgeschlagen", state="error")
        hint = _format_backtesting_run_error(output)
        if hint:
            st.error(hint)
        st.error(f"Exit-Code {exit_code}")
        tail = output[-8000:] if len(output) > 8000 else output
        if tail:
            st.code(tail)

def _render_season_mirror_toggle() -> None:
    from data.cons_data_season_mirror import is_season_mirror_enabled
    from ui.house_config_io import load_main_config, save_main_config

    mirror_key = "backtesting_season_mirror_to_last_month"
    if mirror_key not in st.session_state:
        st.session_state[mirror_key] = is_season_mirror_enabled()
    mirror_checked = st.checkbox(
        "Verbrauchsdaten auf letzten Kalendermonat spiegeln (aktuelle Tarife)",
        key=mirror_key,
        help=(
            "Kalendermonate aus cons_data auf die letzten 12 vollständigen Monate "
            "(Wanduhr) abbilden, damit Spot-/Tarifpreise aktuell sind. "
            "Die CSV-Datei auf der Festplatte bleibt unverändert."
        ),
    )
    if bool(mirror_checked) != is_season_mirror_enabled():
        cfg = load_main_config()
        sim = dict(cfg.get("scenario_explorer_conf") or {})
        sim["season_mirror_to_last_month"] = bool(mirror_checked)
        cfg["scenario_explorer_conf"] = sim
        save_main_config(cfg)
        st.rerun()
    if mirror_checked:
        st.caption(
            "Season-Mirror aktiv: Verbrauch/PV nach Kalendermonat auf den "
            "aktuellen 12-Monats-Horizont gespiegelt."
        )


def _render_horizon_select(log_exists: bool, meta: dict | None) -> tuple[str, bool]:
    selectbox_index = [FIXED_24H, SUNRISE_WINDOW].index(DEFAULT_HORIZON_MODE)
    if "backtesting_horizon_mode" not in st.session_state:
        log_horizon = log_horizon_mode(meta) if log_exists else None
        if log_horizon in (FIXED_24H, SUNRISE_WINDOW):
            selectbox_index = [FIXED_24H, SUNRISE_WINDOW].index(log_horizon)
    horizon_mode = st.selectbox(
        "Planungshorizont",
        options=[FIXED_24H, SUNRISE_WINDOW],
        format_func=lambda mode: _HORIZON_MODE_LABELS[mode],
        index=selectbox_index,
        key="backtesting_horizon_mode",
        help=(
            "Sunrise (Standard): wie Live-Optimierung (SA_0-->SA_2); Voraussetzung für SA-Zonen in Chart1/2. "
            "24h: Referenzmodus für Jahresvergleiche. "
            "Bei vorhandenem Lauf entspricht die Auswahl dem gespeicherten Horizont; "
            "eine Änderung macht die Ergebnisse ungültig bis zur Neuberechnung."
        ),
    )
    horizon_stale = horizon_selection_stale(meta, horizon_mode)
    if horizon_stale:
        st.warning(_HORIZON_STALE_WARNING)
    return horizon_mode, horizon_stale


def _render_run_buttons(
    *,
    label: str,
    cons_data_ready: bool,
    test_month: int | None,
    horizon_mode: str,
    log_stale: bool,
) -> None:
    col_full, col_test = st.columns(2)
    if col_full.button(
        label,
        type="primary",
        key="backtesting_run_btn",
        disabled=not cons_data_ready,
    ):
        _execute_backtesting_run(
            status_label="Szenario-Explorer läuft…",
            horizon_mode=horizon_mode,
        )
    test_disabled = not cons_data_ready or test_month is None
    if col_test.button(
        "Szenario-Explorer-Berechnung testen",
        type="secondary",
        key="backtesting_test_run_btn",
        disabled=test_disabled,
    ):
        st.warning(
            "Testlauf (1 Monat) überschreibt das bestehende Szenario-Explorer-Log."
        )
        _execute_backtesting_run(
            start_month=test_month,
            end_month=test_month,
            status_label=f"Szenario-Explorer-Testlauf (Monat {test_month}/{BACKTESTING_YEAR})…",
            horizon_mode=horizon_mode,
        )
    if not cons_data_ready:
        st.caption(
            "Szenario-Explorer ist deaktiviert, bis gültige Verbrauchsdaten in "
            "`cons_data.csv` vorhanden sind (siehe Abschnitt oben)."
        )
    elif test_month is None:
        st.caption(
            "Testlauf deaktiviert: keine cons_data-Daten im Szenario-Explorer-Basisjahr."
        )
    if log_stale:
        st.caption(_STALE_CAPTION)


def _render_worker_and_pv_notice() -> None:
    scenarios, scenario_error = try_get_backtesting_scenarios()
    if scenario_error or not scenarios:
        return
    live_scenario_id = config.get_live_scenario_id()
    parallel_task_count = count_backtesting_parallel_tasks(
        scenarios,
        live_scenario_id=live_scenario_id,
    )
    worker_count = auto_backtesting_workers(parallel_task_count)
    if worker_count > 1:
        st.caption(
            f"Automatisch parallele Berechnung: bis zu {worker_count} Worker "
            f"für {parallel_task_count} Tasks "
            f"({len(scenarios)} optimierte Szenarien + Referenzberechnungen)."
        )
    _render_imported_pv_run_notice(scenarios)


def render_backtesting_run_controls(
    *,
    log_exists: bool,
    log_stale: bool,
    stale_reason: str | None,
    cons_data_ready: bool,
    meta: dict | None = None,
) -> bool:
    """Rendert Start-Steuerung. True wenn Horizont-Auswahl vom Log abweicht."""
    del stale_reason
    label = "Szenario-Explorer neu berechnen" if log_exists else "Szenario-Explorer starten"
    log_period = meta.get("period") if meta else None
    render_time_range_help(key="backtesting_time_ranges_run", log_period=log_period)
    test_month = suggest_test_month()
    if log_exists and meta is not None:
        sync_horizon_selectbox_from_log(meta)
    _render_season_mirror_toggle()
    horizon_mode, horizon_stale = _render_horizon_select(log_exists, meta)
    _render_worker_and_pv_notice()
    _render_run_buttons(
        label=label,
        cons_data_ready=cons_data_ready,
        test_month=test_month,
        horizon_mode=horizon_mode,
        log_stale=log_stale,
    )
    return horizon_stale

def _render_imported_pv_run_notice(scenarios: dict[str, dict]) -> None:
    from simulation.engine import collect_imported_pv_scenario_meta

    used, missing = collect_imported_pv_scenario_meta(scenarios)
    labels = scenario_labels_map()
    if used:
        names = ", ".join(labels.get(sid, sid) for sid in used)
        st.info(
            f"Hinweis: Für folgende Szenarien wird importiertes PV-Profil "
            f"statt PV aus Wetterdaten verwendet: {names}."
        )
    if missing:
        names = ", ".join(labels.get(sid, sid) for sid in missing)
        st.warning(
            f"Szenarien mit aktiviertem „Importiertes PV“, aber ohne ausreichende "
            f"`pv_profile_csv` (≥12 Monate) im Hausprofil "
            f"(Fallback: synthetisches PV aus Wetterdaten): {names}."
        )

def _warn_if_house_profile_imports_short_for_se() -> None:
    """One-line reminder when live house-profile imports are too short for SE."""
    from house_config.consumption_csv import (
        load_hourly_profile_csv,
        profile_csv_adequate_for_se,
        shared_import_span_hours,
    )
    from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID
    from ui.house_config_io import load_house_profiles

    scenarios, error = try_get_backtesting_scenarios()
    if error or not scenarios:
        return
    live = scenarios.get(DEFAULT_LIVE_SCENARIO_ID) or next(iter(scenarios.values()), {})
    profile = live.get("_house_profile") if isinstance(live, dict) else None
    if not isinstance(profile, dict):
        profiles = load_house_profiles().get("profiles", {})
        hid = str((live or {}).get("house_profile_id", "") or "").strip()
        profile = profiles.get(hid, {}) if hid else {}
    if not isinstance(profile, dict):
        return
    v_path = str(profile.get("total_profile_csv", "") or "").strip()
    p_path = str(profile.get("pv_profile_csv", "") or "").strip()
    if not v_path and not p_path:
        return
    if p_path and not profile_csv_adequate_for_se(p_path):
        st.caption(
            "Hausprofil-PV-Import ist kürzer als 12 Monate — Szenario-Explorer "
            "nutzt synthetisches PV (Open-Meteo), CSV nur zur visuellen Kontrolle."
        )
        return
    if not v_path:
        return
    try:
        v_rows = load_hourly_profile_csv(v_path)
        p_rows = load_hourly_profile_csv(p_path) if p_path else None
    except (OSError, ValueError, FileNotFoundError):
        return
    if shared_import_span_hours(v_rows, p_rows) < 8760:
        st.caption(
            "Hausprofil-CSV-Import kürzer als 12 Monate — nur visuelle Kontrolle; "
            "Szenario-Explorer rechnet mit synthetischen Werten."
        )

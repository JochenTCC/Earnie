"""Backtesting-Auswertung und UI-Start aus scripts/run_backtesting.py."""
from __future__ import annotations

import streamlit as st
import pandas as pd

import config
from data import cons_data_store
from runtime_store.persist_paths import resolve_backtesting_log_dir
from simulation import backtesting_log
from simulation.backtesting_fingerprint import fingerprint_for_current_config
from scripts.run_backtesting import BACKTESTING_YEAR
from ui.backtesting_charts import scenario_monthly_cost_chart
from ui.backtesting_cons_data import render_cons_data_section
from ui.backtesting_results_helpers import (
    build_annual_cost_rows,
    cons_data_has_flex_energy,
    nav_bounds_from_period,
    reference_consumption_subheader,
    reference_kwh_for_period,
    slice_cons_data_for_period,
    format_test_run_caption,
)
from ui.backtesting_runner import (
    default_progress_file_path,
    run_backtesting_subprocess,
    suggest_test_month,
)
from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display

_LEGACY_STALE_WARNING = (
    "Älterer Backtesting-Lauf ohne Konfigurations-Fingerabdruck — "
    "bitte einmal neu berechnen."
)
_MISMATCH_STALE_WARNING = (
    "Gespeicherter Backtesting-Lauf passt nicht zur aktuellen Konfiguration. "
    "Bitte neu berechnen."
)
_STALE_CAPTION = (
    "Die aktuelle Konfiguration weicht vom gespeicherten Lauf ab. "
    "Ergebnisse unten sind veraltet."
)


@st.cache_data(ttl=60, show_spinner="Lade Backtesting-Log...")
def load_backtesting_data():
    return backtesting_log.load_backtesting_log()


def scenario_labels_map() -> dict[str, str]:
    labels = {"runtime_settings": "Runtime (Baseline)"}
    for scenario in config.get_scenarios():
        labels[scenario["id"]] = scenario.get("label", scenario["id"])
    return labels


def try_get_backtesting_scenarios() -> tuple[dict[str, dict] | None, str | None]:
    """Löst Szenarien auf; bei Konfigurationsfehler (None, Fehlermeldung)."""
    try:
        return config.get_backtesting_scenarios(), None
    except ValueError as exc:
        return None, str(exc)


def validate_backtesting_config() -> str | None:
    """None wenn auflösbar, sonst Fehlermeldung für die UI."""
    _, error = try_get_backtesting_scenarios()
    return error


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


def _format_config_error(message: str) -> str:
    if "export_tariff_id" in message or "import_tariff_id" in message:
        return (
            f"{message}\n\n"
            "Prüfe im **Szenarieneditor → Runtime**, ob Bezugs- und Einspeisetarif "
            "noch im Tarifkatalog existieren (Tarif-IDs wurden mit 1.24.f teils umbenannt, "
            "z. B. `awattar_sunny_float` → `dynamic_epex`)."
        )
    return message


def _format_backtesting_run_error(output: str) -> str | None:
    if "cons_data_hourly.csv" in output:
        return (
            "Backtesting benötigt Verbrauchsdaten in `cons_data_hourly.csv` "
            f"unter `{resolve_backtesting_log_dir()}` (bzw. dem in der Config "
            "konfigurierten `path_cons_data`). "
            "Für Greenfield: Daten per `scripts/generate_cons_data.py` erzeugen "
            "oder aus `runtime/` übernehmen."
        )
    if "No module named scripts" in output:
        return (
            "Backtesting-Subprocess konnte das Skript nicht starten. "
            "Streamlit neu starten; unter VS Code `subProcess: false` in launch.json "
            "verwenden (bereits für Greenfield-Launch gesetzt)."
        )
    return None


def render_configured_scenarios() -> None:
    st.subheader("Konfigurierte Szenarien")
    scenarios, error = try_get_backtesting_scenarios()
    if error:
        st.error(_format_config_error(error))
        return
    labels = scenario_labels_map()
    for scenario_id in scenarios:
        st.write(f"- **{labels.get(scenario_id, scenario_id)}** (`{scenario_id}`)")


def _execute_backtesting_run(
    *,
    start_month: int | None = None,
    end_month: int | None = None,
    status_label: str,
) -> None:
    config_error = validate_backtesting_config()
    if config_error:
        st.error(_format_config_error(config_error))
        return

    progress_file = default_progress_file_path()
    with st.status(status_label, expanded=True) as status:
        progress_bar = st.progress(0.0)
        progress_caption = st.empty()

        def _on_progress(progress: dict) -> None:
            total = int(progress.get("total") or 0)
            current = int(progress.get("current") or 0)
            scenario = str(progress.get("scenario") or "")
            phase = str(progress.get("phase") or "")
            if total > 0:
                progress_bar.progress(min(current / total, 1.0))
            if phase == "reference":
                progress_caption.caption(f"Referenz: {scenario}")
            elif total > 0:
                progress_caption.caption(f"{scenario}: {current}/{total} h")
            else:
                progress_caption.caption(scenario or "Backtesting läuft…")

        exit_code, output = run_backtesting_subprocess(
            start_month=start_month,
            end_month=end_month,
            progress_file=progress_file,
            on_progress=_on_progress,
        )
        if exit_code == 0:
            progress_bar.progress(1.0)
            status.update(label="Backtesting abgeschlossen", state="complete")
            load_backtesting_data.clear()
            st.rerun()
        else:
            status.update(label="Backtesting fehlgeschlagen", state="error")
            hint = _format_backtesting_run_error(output)
            if hint:
                st.error(hint)
            st.error(f"Exit-Code {exit_code}")
            tail = output[-8000:] if len(output) > 8000 else output
            if tail:
                st.code(tail)


def render_backtesting_run_controls(
    *,
    log_exists: bool,
    log_stale: bool,
    stale_reason: str | None,
    cons_data_ready: bool,
) -> None:
    label = "Backtesting neu berechnen" if log_exists else "Backtesting starten"
    test_month = suggest_test_month()
    col_full, col_test = st.columns(2)
    if col_full.button(
        label,
        type="primary",
        key="backtesting_run_btn",
        disabled=not cons_data_ready,
    ):
        _execute_backtesting_run(status_label="Backtesting läuft…")

    test_disabled = not cons_data_ready or test_month is None
    if col_test.button(
        "Backtesting-Berechnung testen",
        type="secondary",
        key="backtesting_test_run_btn",
        disabled=test_disabled,
    ):
        st.warning(
            "Testlauf (1 Monat) überschreibt das bestehende Backtesting-Log."
        )
        _execute_backtesting_run(
            start_month=test_month,
            end_month=test_month,
            status_label=f"Backtesting-Testlauf (Monat {test_month}/{BACKTESTING_YEAR})…",
        )
    if not cons_data_ready:
        st.caption(
            "Backtesting ist deaktiviert, bis gültige Verbrauchsdaten in "
            "`cons_data_hourly.csv` vorhanden sind (siehe Abschnitt oben)."
        )
    elif test_month is None:
        st.caption(
            "Testlauf deaktiviert: keine cons_data-Daten im Backtesting-Basisjahr."
        )
    if log_stale:
        st.caption(_STALE_CAPTION)


def render_backtesting_log_caption(meta: dict) -> None:
    st.subheader("Backtesting-Log")
    created = meta.get("created_at", "")[:19].replace("T", " ")
    period = meta.get("period", {})
    st.caption(
        f"Erstellt: {created} UTC · "
        f"Zeitraum: {period.get('start', '?')} – {period.get('end', '?')} "
        f"({period.get('windows', '?')} Fenster)"
    )
    caption = format_test_run_caption(period)
    if caption:
        st.warning(caption)


def render_annual_cost_table(meta: dict) -> None:
    st.subheader("Gesamtkosten")
    period = meta.get("period", {})
    ref_kwh: float | None = None
    if cons_data_store.is_cons_data_populated():
        cons_df = cons_data_store.load_cons_data()
        ref_kwh = reference_kwh_for_period(cons_df, period)
    rows = build_annual_cost_rows(meta, ref_kwh)
    if not rows:
        st.info("Keine Gesamtkosten im Log.")
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_reference_consumption_ui(meta: dict) -> None:
    period = meta.get("period", {})
    st.subheader(reference_consumption_subheader(period))
    if not cons_data_store.is_cons_data_populated():
        st.info("Keine Verbrauchsdaten (`cons_data_hourly.csv`) für die Visualisierung.")
        return
    cons_df = cons_data_store.load_cons_data()
    sliced = slice_cons_data_for_period(cons_df, period)
    if sliced.empty:
        st.info("Keine Verbrauchsdaten im Zeitraum des Backtesting-Logs.")
        return
    if not cons_data_has_flex_energy(sliced):
        st.warning(
            "In den Verbrauchsdaten fehlen Werte für flexible Verbraucher "
            "(nur Basislast sichtbar). Bitte **Verbrauchsdaten generieren** "
            "oder `cons_data_hourly.csv` mit `{verbraucher_id}_kw`-Spalten "
            "bereitstellen."
        )
    nav_bounds = nav_bounds_from_period(period)
    try:
        render_consumption_display(
            ConsumptionDisplayMode.CONS_DATA,
            key_prefix="backtesting_reference",
            cons_data=sliced,
            reset_token=str(meta.get("created_at", "")),
            nav_bounds=nav_bounds,
        )
    except ValueError as exc:
        st.error(f"Verbrauchsdaten konnten nicht visualisiert werden: {exc}")


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
    chart_monthly = {
        month: {col: float(df.loc[month, col]) for col in chart_columns}
        for month in df.index
    }
    st.plotly_chart(scenario_monthly_cost_chart(chart_monthly), width="stretch")


def _render_backtesting_results(meta: dict) -> None:
    render_backtesting_log_caption(meta)
    render_annual_cost_table(meta)
    render_reference_consumption_ui(meta)
    render_backtesting_monthly_chart(meta)


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
            st.error(f"Backtesting-Log konnte nicht geladen werden: {exc}")
            log_exists = False

    cons_ready = render_cons_data_section()

    render_configured_scenarios()

    if log_exists and meta is not None and log_stale:
        warning = (
            _LEGACY_STALE_WARNING if stale_reason == "legacy" else _MISMATCH_STALE_WARNING
        )
        st.warning(warning)

    render_backtesting_run_controls(
        log_exists=log_exists,
        log_stale=log_stale,
        stale_reason=stale_reason,
        cons_data_ready=cons_ready,
    )

    if not log_exists or meta is None:
        if not log_exists:
            st.info(
                "Noch kein Backtesting-Lauf vorhanden. "
                "Starte die Berechnung mit dem Button oben."
            )
        return

    _render_backtesting_results(meta)

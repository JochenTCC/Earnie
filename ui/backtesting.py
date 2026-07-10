"""Backtesting-Auswertung und UI-Start aus scripts/run_backtesting.py."""
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from data import cons_data_store
from runtime_store.persist_paths import resolve_backtesting_log_dir
from simulation import backtesting_log
from simulation.backtesting_fingerprint import fingerprint_for_current_config
from simulation.engine import HISTORICAL_REFERENCE_ID
from scripts.run_backtesting import BACKTESTING_YEAR
from ui.backtesting_charts import scenario_monthly_cost_chart
from ui.backtesting_cons_data import render_cons_data_section
from ui.backtesting_plausibility_charts import (
    cockpit_hint_caption,
    failure_window_label,
    plausibility_window_consumption_chart,
    slice_cons_data_for_window,
)
from ui.backtesting_runner import (
    default_progress_file_path,
    run_backtesting_subprocess,
    suggest_test_month,
)

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


def render_backtesting_controls(meta: dict, hourly: pd.DataFrame) -> tuple[str, str | None]:
    """Detailansicht-Steuerung im Seiten-Body (ersetzt die frühere Sidebar)."""
    st.subheader("📊 Backtesting-Log")
    created = meta.get("created_at", "")[:19].replace("T", " ")
    period = meta.get("period", {})
    st.caption(
        f"Erstellt: {created} UTC · "
        f"Zeitraum: {period.get('start', '?')} – {period.get('end', '?')} "
        f"({period.get('windows', '?')} Fenster)"
    )

    labels = meta.get("labels", {})
    scenario_ids = meta.get("scenario_ids", hourly["scenario_id"].unique().tolist())
    scenario_labels = [labels.get(sid, sid) for sid in scenario_ids]
    months = sorted(hourly["ts"].dt.to_period("M").astype(str).unique())

    col_scenario, col_month = st.columns(2)
    selected_label = col_scenario.selectbox(
        "Szenario (Detailansicht)",
        scenario_labels,
        index=0,
    )
    selected_id = scenario_ids[scenario_labels.index(selected_label)]

    month_filter = col_month.selectbox(
        "Monat (Detailansicht)",
        ["Gesamter Zeitraum"] + months,
    )
    month_key = None if month_filter == "Gesamter Zeitraum" else month_filter
    return selected_id, month_key


def render_backtesting_summary(meta: dict) -> None:
    st.subheader("💶 Gesamtkosten-Vergleich")
    summary = meta.get("summary", {})
    totals = summary.get("total_eur", {})
    labels = meta.get("labels", {})
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    ref_total = totals.get(ref_id)

    cols = st.columns(min(len(totals), 4))
    for idx, (sid, total) in enumerate(totals.items()):
        col = cols[idx % len(cols)]
        label = labels.get(sid, sid)
        if sid == ref_id:
            col.metric(label, f"{total:.2f} €", help="Historischer Verbrauch ohne Optimierung")
        elif ref_total is not None:
            savings = ref_total - total
            col.metric(
                label,
                f"{total:.2f} €",
                delta=f"{savings:+.2f} € vs Referenz",
                delta_color="normal" if savings >= 0 else "inverse",
            )
        else:
            col.metric(label, f"{total:.2f} €")


def render_backtesting_monthly_table(meta: dict) -> None:
    st.subheader("📅 Monatlicher Kostenvergleich")
    monthly = meta.get("summary", {}).get("monthly_eur", {})
    if not monthly:
        st.info("Keine Monatswerte im Log.")
        return
    df = pd.DataFrame(monthly).T.round(2)
    df.index.name = "Monat"
    st.dataframe(df, width="stretch")

    chart_columns = [
        col for col in df.columns if not col.startswith("Einsparung")
    ]
    if chart_columns:
        chart_monthly = {
            month: {col: float(df.loc[month, col]) for col in chart_columns}
            for month in df.index
        }
        st.plotly_chart(scenario_monthly_cost_chart(chart_monthly), width="stretch")


def render_backtesting_plausibility(meta: dict, scenario_id: str) -> None:
    plausi = meta.get("plausibility", {}).get(scenario_id)
    if not plausi:
        return
    label = meta.get("labels", {}).get(scenario_id, scenario_id)
    st.subheader(f"✅ Plausibilisierung – {label}")
    ok = plausi.get("ok_count", 0)
    total = plausi.get("total_windows", 0)
    failed = plausi.get("failed_count", 0)
    st.caption(
        f"{ok}/{total} Fenster OK "
        f"(Toleranz: {plausi.get('tolerance_kwh')} kWh oder "
        f"{plausi.get('tolerance_rel', 0) * 100:.0f} % relativ)"
    )
    failures: list[dict] = list(plausi.get("failures", []))
    if not failures:
        return

    st.warning(f"{failed} Fenster ausserhalb der Toleranz")
    only_failed = st.checkbox(
        "Nur Fenster außerhalb Toleranz",
        value=True,
        key=f"plausi_only_failed_{scenario_id}",
    )
    visible_failures = failures if only_failed else failures
    if not visible_failures:
        st.info("Keine Fehlerfenster zur Anzeige.")
        return

    labels = [failure_window_label(item) for item in visible_failures]
    selected_label = st.selectbox(
        "Fenster analysieren",
        labels,
        key=f"plausi_window_select_{scenario_id}",
    )
    selected = visible_failures[labels.index(selected_label)]
    st.dataframe(
        pd.DataFrame(visible_failures),
        width="stretch",
        hide_index=True,
    )

    cons_df = cons_data_store.load_cons_data()
    window_slice = slice_cons_data_for_window(cons_df, str(selected["window_end"]))
    st.plotly_chart(
        plausibility_window_consumption_chart(window_slice, selected),
        width="stretch",
    )
    st.caption(cockpit_hint_caption())


def render_backtesting_hourly_chart(
    hourly: pd.DataFrame,
    scenario_id: str,
    month_key: str | None,
) -> None:
    df = hourly[hourly["scenario_id"] == scenario_id].copy()
    if month_key:
        df = df[df["ts"].dt.to_period("M").astype(str) == month_key]
    if df.empty:
        st.warning("Keine Stundenwerte für die Auswahl.")
        return

    label = df["scenario_label"].iloc[0]
    st.subheader(f"📈 Stundenverlauf – {label}" + (f" ({month_key})" if month_key else ""))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["ts"],
        y=df["sim_cost"],
        name="Stromkosten (€/h)",
        marker_color="steelblue",
        yaxis="y",
    ))
    if "sim_soc" in df.columns and df["sim_soc"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["ts"],
            y=df["sim_soc"],
            name="SoC (%)",
            line=dict(color="gold", width=2),
            yaxis="y2",
        ))
    fig.update_layout(
        xaxis_title="Zeit",
        yaxis=dict(title="Kosten (€)", side="left"),
        yaxis2=dict(title="SoC (%)", side="right", overlaying="y", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=40, r=40, t=40, b=40),
        height=400,
    )
    st.plotly_chart(fig, width="stretch")

    with st.expander("Stundendetails"):
        st.dataframe(
            df.sort_values("ts", ascending=False),
            width="stretch",
            hide_index=True,
        )


def _render_backtesting_results(meta: dict, hourly: pd.DataFrame) -> None:
    selected_id, month_key = render_backtesting_controls(meta, hourly)
    render_backtesting_summary(meta)
    render_backtesting_monthly_table(meta)

    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    if selected_id != ref_id:
        render_backtesting_plausibility(meta, selected_id)

    render_backtesting_hourly_chart(hourly, selected_id, month_key)


def render_backtesting_block() -> None:
    log_exists = backtesting_log.log_exists()
    meta: dict | None = None
    hourly: pd.DataFrame | None = None
    log_stale = False
    stale_reason: str | None = None

    if log_exists:
        try:
            meta, hourly = load_backtesting_data()
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

    if not log_exists or meta is None or hourly is None:
        if not log_exists:
            st.info(
                "Noch kein Backtesting-Lauf vorhanden. "
                "Starte die Berechnung mit dem Button oben."
            )
        return

    _render_backtesting_results(meta, hourly)

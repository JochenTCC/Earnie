"""Backtesting-UI: cons_data_hourly.csv anzeigen, prüfen und generieren."""
from __future__ import annotations

import streamlit as st

from data import cons_data_store
from scripts.generate_cons_data import generate
from ui.backtesting_results_helpers import cons_data_has_flex_energy
from ui.backtesting_time_ranges import cons_data_section_caption, render_time_range_help
from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display

import config
from house_config.scenario_resolution import DEFAULT_LIVE_SCENARIO_ID

_MATCH_OK = "Passt zur aktuellen Konfiguration (Verbraucher-IDs und Hausprofil)."
_MATCH_MISSING_META = "Prüfung nicht möglich (keine Meta-Datei)."
_MATCH_ID_MISMATCH = (
    "Verbraucher-IDs in den gespeicherten Daten weichen von der aktuellen "
    "Konfiguration ab — bitte neu generieren."
)
_MATCH_PROFILE_MISMATCH = (
    "Hausprofil-Parameter wurden seit der letzten Generierung geändert — "
    "bitte Verbrauchsdaten neu generieren."
)


def cons_data_ready() -> bool:
    return cons_data_store.is_cons_data_populated()


def _format_match_status(reason: str | None) -> tuple[str, str]:
    if reason is None:
        return "success", _MATCH_OK
    if reason == "missing_meta":
        return "warning", _MATCH_MISSING_META
    if reason == "profile_mismatch":
        return "warning", _MATCH_PROFILE_MISMATCH
    return "warning", _MATCH_ID_MISMATCH


def render_cons_data_section() -> bool:
    """Zeigt Verbrauchsdaten-Abschnitt; gibt True zurück wenn Backtesting starten kann."""
    path = cons_data_store.get_output_path()
    st.subheader("Verbrauchsdaten (`cons_data_hourly.csv`)")
    st.caption(f"Pfad: `{path}`")
    st.caption(cons_data_section_caption())
    render_time_range_help(key="backtesting_time_ranges_cons_data")

    populated = cons_data_ready()
    if not populated:
        st.warning(
            "Keine gültigen Verbrauchsdaten vorhanden. "
            "Generiere die Datei aus der Hauskonfiguration, bevor du Szenario-Explorer startest."
        )
    else:
        df = cons_data_store.load_cons_data(path)
        ts_min, ts_max = df.index.min(), df.index.max()
        st.caption(
            f"Zeitraum: {ts_min.strftime('%Y-%m-%d %H:%M')} – "
            f"{ts_max.strftime('%Y-%m-%d %H:%M')} · {len(df)} Stunden"
        )
        match_reason = cons_data_store.cons_data_consumer_match_reason(path)
        level, message = _format_match_status(match_reason)
        if level == "success":
            st.success(message)
        else:
            st.warning(message)

    if st.button(
        "Verbrauchsdaten generieren (synthetisch)",
        key="backtesting_cons_data_generate_btn",
    ):
        with st.status("Generiere Verbrauchsdaten…", expanded=True) as status:
            try:
                generate(source="synthetic")
            except Exception as exc:
                status.update(label="Generierung fehlgeschlagen", state="error")
                st.error(f"Generierung fehlgeschlagen: {exc}")
            else:
                status.update(label="Verbrauchsdaten generiert", state="complete")
                st.rerun()

    if populated:
        df = cons_data_store.load_cons_data(path)
        if not cons_data_has_flex_energy(df):
            st.warning(
                "Flexible Verbraucher haben in `cons_data_hourly.csv` keine "
                "messbaren Werte (nur Basislast). Bitte Daten neu generieren."
            )
        try:
            scenarios_for_pv = None
            live_id = None
            try:
                scenarios_for_pv = config.get_backtesting_scenarios()
                live_id = config.get_live_scenario_id() or DEFAULT_LIVE_SCENARIO_ID
            except Exception:
                scenarios_for_pv = None
            render_consumption_display(
                ConsumptionDisplayMode.CONS_DATA,
                key_prefix="backtesting_cons_data",
                cons_data=df,
                reset_token=str(df.index.max()),
                scenarios_for_pv=scenarios_for_pv,
                live_scenario_id=live_id,
            )
        except ValueError as exc:
            st.error(f"Verbrauchsdaten konnten nicht visualisiert werden: {exc}")

    return cons_data_ready()

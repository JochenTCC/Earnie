"""Backtesting-UI: cons_data_hourly.csv anzeigen, prüfen und generieren."""
from __future__ import annotations

import streamlit as st

from data import cons_data_store
from scripts.generate_cons_data import generate
from ui.backtesting_results_helpers import cons_data_has_flex_energy
from ui.backtesting_time_ranges import cons_data_section_caption, render_time_range_help
from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display

_MATCH_OK = "Passt zur aktuellen Konfiguration (Verbraucher-IDs)."
_MATCH_MISSING_META = "Prüfung nicht möglich (keine Meta-Datei)."
_MATCH_ID_MISMATCH = (
    "Verbraucher-IDs in den gespeicherten Daten weichen von der aktuellen "
    "Konfiguration ab — bitte neu generieren."
)


def cons_data_ready() -> bool:
    return cons_data_store.is_cons_data_populated()


def _format_match_status(reason: str | None) -> tuple[str, str]:
    if reason is None:
        return "success", _MATCH_OK
    if reason == "missing_meta":
        return "warning", _MATCH_MISSING_META
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
            "Generiere die Datei aus der Hauskonfiguration, bevor du Backtesting startest."
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
            render_consumption_display(
                ConsumptionDisplayMode.CONS_DATA,
                key_prefix="backtesting_cons_data",
                cons_data=df,
                reset_token=str(df.index.max()),
            )
        except ValueError as exc:
            st.error(f"Verbrauchsdaten konnten nicht visualisiert werden: {exc}")

    return cons_data_ready()

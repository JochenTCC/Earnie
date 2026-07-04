# app.py
from runtime_store import bootstrap

bootstrap.run()

import logging

import streamlit as st

import config

config.reinit_config()
from integrations import loxone_client
from runtime_store.config_drift import format_drift_message, load_config_drift_items
from version import __version__
from ui.auto_refresh import setup_auto_refresh
from ui.backtesting import render_backtesting_block
from ui.config_forms import render_parameter_input
from ui.countdown import render_countdown_block
from ui.historical import render_historical_inputs, render_historical_optimization_block
from ui.history_navigation import is_history_mode, is_live_s2_window, render_disabled_live_section
from ui.live_mode import render_optimization_savings_and_chart
from ui.mode_selector import render_mode_selector
from ui.runtime_config import reload_runtime_config
from ui.sankey import render_live_power_flow
from ui.styles import inject_compact_numeric_css

logger = logging.getLogger("app")

st.set_page_config(
    page_title="Ernie Energy Control Center",
    page_icon="🔋",
    layout="wide",
)


def main() -> None:
    inject_compact_numeric_css()
    st.title("🔋 Ernie Energy Control Center")
    st.caption(f"Version {__version__}")
    try:
        drift_items = load_config_drift_items()
        if drift_items:
            st.warning(format_drift_message(drift_items))
    except FileNotFoundError:
        pass
    mode = render_mode_selector()

    if mode == "Historischer Tag":
        st.markdown(
            "Historische **24-Stunden-Optimierung** mit Daten aus **cons_data_hourly.csv** "
            "(Grundlast, PV) und historischen Marktpreisen."
        )
    elif mode == "Backtesting":
        st.markdown(
            "Auswertung des **Backtesting-Logs** aus `scripts/run_backtesting.py` "
            "(Referenz ohne Optimierung vs. optimierte Szenarien)."
        )
    else:
        reload_runtime_config()
        if is_live_s2_window():
            setup_auto_refresh()
        st.markdown(
            "Produktiv-Cockpit **Sunset-2-Sunset**: Vergangenheit und Vorausschau "
            "in zwei Sonnenaufgang-Segmenten (SA₀→SA₁, SA₁→SA₂)."
        )

    render_parameter_input(mode)

    if mode == "Backtesting":
        render_backtesting_block()
        return

    if mode == "Historischer Tag":
        selected_date, initial_soc = render_historical_inputs()
        render_historical_optimization_block(selected_date, initial_soc)
        return

    current_soc = loxone_client.fetch_loxone_generic_value(config.get("LOXONE_SOC_NAME"))
    render_optimization_savings_and_chart(current_soc)
    if is_history_mode():
        render_disabled_live_section("Energiefluss (Live)")
        render_disabled_live_section("Countdown bis zur nächsten Optimierung")
    else:
        render_live_power_flow(current_soc)
        render_countdown_block()


if __name__ == "__main__":
    main()

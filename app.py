# app.py
from dotenv import load_dotenv

load_dotenv()

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
from ui.help_hint import render_page_title_with_help
from ui.history_navigation import is_live_s2_window
from ui.live_mode import render_optimization_savings_and_chart
from ui.main_py_sync import poll_main_py_sync_if_pending
from ui.mode_selector import render_mode_selector, UI_MODE_LABELS
from ui.price_forecast import render_price_forecast_block
from ui.runtime_config import reload_runtime_config
from ui.sankey import render_live_power_flow
from ui.styles import inject_compact_numeric_css, inject_help_hint_css

logger = logging.getLogger("app")

_PAGE_TITLE = "🔋 Ernie Energy Control Center"


def _mode_scope_help(mode: str) -> str:
    if mode == "Backtesting":
        return (
            "Auswertung des **Backtesting-Logs** aus `scripts/run_backtesting.py` "
            "(Referenz ohne Optimierung vs. optimierte Szenarien)."
        )
    return (
        "Produktiv-Cockpit **Sunset-2-Sunset**: Vergangenheit und Vorausschau "
        "in zwei Sonnenaufgang-Segmenten (SA₀→SA₁, SA₁→SA₂)."
    )


st.set_page_config(
    page_title="Ernie Energy Control Center",
    page_icon="🔋",
    layout="wide",
)


def main() -> None:
    inject_compact_numeric_css()
    inject_help_hint_css()
    try:
        drift_items = load_config_drift_items()
        if drift_items:
            st.warning(format_drift_message(drift_items))
    except FileNotFoundError:
        pass
    mode = render_mode_selector()
    render_page_title_with_help(
        _PAGE_TITLE,
        _mode_scope_help(mode),
        key="app_mode_scope_help",
        version=__version__,
    )

    if mode not in ("Backtesting", UI_MODE_LABELS["price_forecast"]):
        reload_runtime_config()
        if is_live_s2_window():
            setup_auto_refresh()
            poll_main_py_sync_if_pending()

    render_parameter_input(mode)

    if mode == "Backtesting":
        render_backtesting_block()
        return

    if mode == UI_MODE_LABELS["price_forecast"]:
        render_price_forecast_block()
        return

    current_soc = loxone_client.fetch_loxone_generic_value(config.get("LOXONE_SOC_NAME"))
    render_optimization_savings_and_chart(current_soc)
    render_live_power_flow(current_soc)
    render_countdown_block()


if __name__ == "__main__":
    main()

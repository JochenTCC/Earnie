# app.py
from runtime_store.dotenv_loader import load_app_dotenv

load_app_dotenv()

import logger_config

logger_config.configure_utf8_stdio()

from runtime_store import bootstrap

bootstrap.run()

import logging

import streamlit as st

from runtime_store.config_load import load_config_or_exit, reinit_config_or_exit

config = load_config_or_exit()
reinit_config_or_exit(config)

from runtime_store.config_drift import (
    format_drift_message,
    load_config_drift_items,
    should_show_config_drift,
)
from runtime_store.dotenv_io import needs_loxone_setup, require_loxone_credentials_for_config
from ui.setup_dotenv import render_loxone_setup_page
from version import __version__
from ui.mode_selector import get_enabled_ui_mode_keys, render_ui_mode_env_notices
from ui.navigation import build_navigation
from ui.setup_progress import render_setup_progress_notice
from ui.styles import inject_compact_numeric_css, inject_help_hint_css

logger = logging.getLogger("app")


st.set_page_config(
    page_title="Ernie Energy Control Center",
    page_icon="🔋",
    layout="wide",
)


def _render_sidebar_version() -> None:
    st.sidebar.caption(f"Version {__version__}")


def _render_drift_warning() -> None:
    if not should_show_config_drift():
        return
    try:
        drift_items = load_config_drift_items()
    except FileNotFoundError:
        return
    if drift_items:
        st.warning(format_drift_message(drift_items))


def main() -> None:
    if needs_loxone_setup():
        render_loxone_setup_page()
        st.stop()

    config.reinit_config(require_loxone_credentials=require_loxone_credentials_for_config())
    inject_compact_numeric_css()
    inject_help_hint_css()
    _render_sidebar_version()
    render_ui_mode_env_notices()
    render_setup_progress_notice()
    _render_drift_warning()

    navigation = build_navigation(get_enabled_ui_mode_keys())
    navigation.run()


if __name__ == "__main__":
    main()

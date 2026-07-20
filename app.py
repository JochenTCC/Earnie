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
from ui.chunk_load_recovery import inject_chunk_load_recovery
from ui.mode_selector import get_enabled_ui_mode_keys, render_ui_mode_env_notices
from ui.navigation import build_navigation
from ui.setup_progress import render_deferred_loxone_sidebar, render_setup_progress_notice
from ui.config_pack import render_config_pack_sidebar
from ui.info_sidebar import render_info_sidebar
from ui.styles import (
    inject_checkbox_highlight_css,
    inject_compact_numeric_css,
    inject_help_hint_css,
    inject_single_file_uploader_css,
)
from ui.truth_banner import render_truth_banner

logger = logging.getLogger("app")


st.set_page_config(
    page_title="Monitor",
    page_icon="🔋",
    layout="wide",
)


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
        render_info_sidebar()
        st.stop()

    config.reinit_config(require_loxone_credentials=require_loxone_credentials_for_config())
    inject_chunk_load_recovery()
    inject_compact_numeric_css()
    inject_help_hint_css()
    inject_single_file_uploader_css()
    inject_checkbox_highlight_css()
    render_ui_mode_env_notices()
    render_config_pack_sidebar()
    render_deferred_loxone_sidebar()
    render_setup_progress_notice()
    _render_drift_warning()
    render_truth_banner(where="main")

    navigation = build_navigation(get_enabled_ui_mode_keys())
    navigation.run()
    # After nav so Info / About sits at the bottom of the sidebar.
    render_info_sidebar()


if __name__ == "__main__":
    main()

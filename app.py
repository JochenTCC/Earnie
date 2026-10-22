# app.py
from runtime_store.dotenv_loader import load_app_dotenv

load_app_dotenv(override=True)

import logger_config

logger_config.configure_utf8_stdio()

import logging
import sys

import streamlit as st

from runtime_store.cloud_demo import ensure_cloud_session_env, render_cloud_demo_intro

ensure_cloud_session_env()

from runtime_store import bootstrap

bootstrap.run()

from runtime_store.migration.gate import (
    abort_message_de,
    migration_blocks_normal_startup,
    plan_for_active_config,
)
from runtime_store.shadow.mode import is_shadow_mode

_migration_plan = plan_for_active_config()
_migration_mode = migration_blocks_normal_startup(_migration_plan)

if _migration_mode and is_shadow_mode():
    print(abort_message_de(_migration_plan), file=sys.stderr)
    print(
        "Abbruch (Shadow): geteilte Konfiguration muss zuerst auf Prod "
        "migriert werden (Shadow migriert nie).",
        file=sys.stderr,
    )
    raise SystemExit(1)

config = None
if not _migration_mode:
    from runtime_store.config_load import load_config_or_exit, reinit_config_or_exit
    from runtime_store.shadow import refuse_shadow_startup_or_exit

    config = load_config_or_exit()
    reinit_config_or_exit(config)
    refuse_shadow_startup_or_exit()

from ui.branding import render_app_logo
from ui.shadow_banner import render_shadow_banner

logger = logging.getLogger("app")


st.set_page_config(
    page_title="Monitor" if not _migration_mode else "Konfigurations-Migration",
    page_icon="🔋",
    layout="wide",
)
render_app_logo()
if not _migration_mode:
    render_shadow_banner()


def _render_downgrade_warning() -> None:
    from runtime_store.version_track import consume_downgrade_warning

    message = consume_downgrade_warning()
    if message:
        st.warning(message)


def _render_drift_warning() -> None:
    from runtime_store.config_drift import (
        format_drift_message,
        load_config_drift_items,
        should_show_config_drift,
    )

    if not should_show_config_drift():
        return
    try:
        drift_items = load_config_drift_items()
    except FileNotFoundError:
        return
    if drift_items:
        st.warning(format_drift_message(drift_items))


def _render_loxone_auth_warning() -> None:
    from ui.loxone_auth_banner import render_loxone_auth_error_banner

    render_loxone_auth_error_banner()


def main() -> None:
    if _migration_mode:
        from ui.pages.page_config_migration import render as render_migration

        # No full sidebar (config pack export would touch live files).
        render_migration(_migration_plan)
        st.stop()

    from runtime_store.dotenv_io import (
        needs_loxone_setup,
        require_loxone_credentials_for_config,
    )
    from ui.chunk_load_recovery import inject_chunk_load_recovery
    from ui.config_pack import render_config_pack_sidebar
    from ui.flash import render_flash_notices
    from ui.info_sidebar import render_info_sidebar, render_missing_next_month_tariff_sidebar
    from ui.mode_selector import get_enabled_ui_mode_keys, render_ui_mode_env_notices
    from ui.navigation import build_navigation
    from ui.setup_dotenv import render_ehal_setup_page
    from ui.setup_progress import render_setup_progress_notice
    from ui.styles import (
        inject_checkbox_highlight_css,
        inject_compact_numeric_css,
        inject_compact_top_layout_css,
        inject_help_hint_css,
        inject_single_file_uploader_css,
    )
    from ui.truth_banner import render_truth_banner

    render_flash_notices()
    if needs_loxone_setup():
        render_ehal_setup_page()
        render_info_sidebar()
        st.stop()

    assert config is not None
    config.reinit_config(require_loxone_credentials=require_loxone_credentials_for_config())
    inject_chunk_load_recovery()
    inject_compact_top_layout_css()
    inject_compact_numeric_css()
    inject_help_hint_css()
    inject_single_file_uploader_css()
    inject_checkbox_highlight_css()
    render_ui_mode_env_notices()
    render_config_pack_sidebar()
    render_setup_progress_notice()
    render_missing_next_month_tariff_sidebar()
    _render_downgrade_warning()
    _render_drift_warning()
    _render_loxone_auth_warning()
    render_cloud_demo_intro()

    from runtime_store.feature_review import (
        SESSION_SE_ACTIVE_THIS_RUN_KEY,
        SESSION_SE_WAS_ACTIVE_KEY,
    )
    from ui.star_review_dialog import (
        arm_scenario_explorer_review_prompt,
        maybe_prompt_scenario_explorer_review,
    )

    prev_on_se = bool(st.session_state.get(SESSION_SE_WAS_ACTIVE_KEY))
    st.session_state[SESSION_SE_ACTIVE_THIS_RUN_KEY] = False
    navigation = build_navigation(get_enabled_ui_mode_keys())
    navigation.run()
    now_on_se = bool(st.session_state.get(SESSION_SE_ACTIVE_THIS_RUN_KEY))
    if prev_on_se and not now_on_se:
        arm_scenario_explorer_review_prompt()
    st.session_state[SESSION_SE_WAS_ACTIVE_KEY] = now_on_se
    maybe_prompt_scenario_explorer_review()
    # After nav: Banner der Wahrheit at page bottom; Info / About at sidebar bottom.
    render_truth_banner(where="main")
    render_info_sidebar()


if __name__ == "__main__":
    main()

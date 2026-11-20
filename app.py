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
    migration_blocks_normal_startup,
    plan_for_active_config,
)
from runtime_store.shadow.hooks import shadow_migration_mode_refusal

_migration_plan = plan_for_active_config()
_migration_mode = migration_blocks_normal_startup(_migration_plan)

_shadow_refusal = shadow_migration_mode_refusal(_migration_plan)
if _shadow_refusal:
    print(f"Abbruch (Shadow): {_shadow_refusal}", file=sys.stderr)
    raise SystemExit(1)

config = None
# Config load error under Streamlit: shown in the UI instead of SystemExit (which
# would kill the script thread and leave the browser spinning without a message).
_config_error: str | None = None
if not _migration_mode:
    from runtime_store.config_load import load_config_for_ui
    from runtime_store.shadow.hooks import refuse_shadow_startup_or_exit

    config, _config_error = load_config_for_ui()
    if _config_error is None:
        refuse_shadow_startup_or_exit()

from ui.branding import APP_PAGE_ICON, render_app_logo
from runtime_store.shadow.mode import is_shadow_mode

logger = logging.getLogger("app")


if _migration_mode:
    _page_title = "Konfigurations-Migration"
elif _config_error is not None:
    _page_title = "Konfigurationsfehler"
else:
    _page_title = "Monitor"
st.set_page_config(
    page_title=_page_title,
    page_icon=APP_PAGE_ICON,
    layout="wide",
)
render_app_logo()
if not _migration_mode and _config_error is None and is_shadow_mode():
    from ui.shadow_banner import render_shadow_banner

    render_shadow_banner()


def _render_config_error_page(message: str) -> None:
    """Config does not load: show why and keep the config-pack import usable."""
    from ui.config_pack import render_backup_transfer_sidebar

    st.error(f"Die Konfiguration kann nicht geladen werden:\n\n{message}")
    st.info(
        "Korrigieren Sie die Konfigurationsdateien oder laden Sie in der Seitenleiste "
        "unter „Sichern & Übertragen“ ein gültiges Config-Paket (ZIP)."
    )
    render_backup_transfer_sidebar(expanded=True)


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
    from ui.pages.page_config_migration import render as render_migration, report_pending

    # After a successful run the plan is empty, so ``_migration_mode`` is already
    # False; the report (backup, to-dos, daemon state) still has to be shown once.
    if _migration_mode or report_pending():
        # No full sidebar (config pack export would touch live files).
        render_migration(_migration_plan)
        st.stop()

    if _config_error is not None:
        _render_config_error_page(_config_error)
        st.stop()

    from runtime_store.dotenv_io import (
        needs_loxone_setup,
        require_loxone_credentials_for_config,
    )
    from ui.chunk_load_recovery import inject_chunk_load_recovery
    from ui.config_pack import render_backup_transfer_sidebar
    from ui.flash import render_flash_notices
    from ui.info_sidebar import render_info_sidebar, render_missing_next_month_tariff_sidebar
    from ui.mode_selector import get_enabled_ui_mode_keys, render_ui_mode_env_notices
    from ui.navigation import build_navigation
    from ui.sponsor_button import render_sponsor_sidebar_button
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
        render_sponsor_sidebar_button()
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
    render_sponsor_sidebar_button()
    render_backup_transfer_sidebar()
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

"""App-shell widgets for the coverage tests: the test picks one via ``cov_case``.

Monkeypatches of the test (feed health, registry, send_review, ...) apply, because
AppTest runs in the test process and these modules come from ``sys.modules``.
"""
import streamlit as st

case = st.session_state.get("cov_case")

if case == "shadow_banner":
    from ui.shadow_banner import render_shadow_banner

    render_shadow_banner()
elif case == "shadow_table":
    from ui.shadow_banner import render_shadow_would_write_table

    render_shadow_would_write_table()
elif case == "truth_sidebar":
    from ui.truth_banner import render_truth_banner

    render_truth_banner(where="sidebar")
elif case == "truth_main":
    from ui.truth_banner import render_truth_banner

    render_truth_banner(where="main")
elif case == "registry_caption":
    from ui.truth_banner import render_registry_status_caption

    render_registry_status_caption()
elif case == "info_sidebar":
    from ui.info_sidebar import render_info_sidebar

    render_info_sidebar()
elif case == "missing_tariff":
    from ui.info_sidebar import render_missing_next_month_tariff_sidebar

    render_missing_next_month_tariff_sidebar()
elif case == "star_review":
    from ui.star_review_dialog import open_star_review_dialog

    open_star_review_dialog("cov_review", "Wie war es?", ["Einfach", "Verständlich"])
elif case == "usage_settings":
    from ui.usage_ping_consent import render_usage_ping_settings

    render_usage_ping_settings()
elif case == "loxone_verify":
    from ui.setup_dotenv import display_loxone_verify_results

    display_loxone_verify_results(st.session_state["cov_ok"], st.session_state["cov_results"])
elif case == "ehal_setup":
    from ui.setup_dotenv import render_ehal_setup_page

    render_ehal_setup_page()
elif case == "styles":
    from ui.chunk_load_recovery import inject_chunk_load_recovery
    from ui.styles import (
        inject_checkbox_highlight_css,
        inject_compact_numeric_css,
        inject_compact_top_layout_css,
        inject_help_hint_css,
        inject_single_file_uploader_css,
    )

    inject_compact_top_layout_css()
    inject_compact_numeric_css()
    inject_help_hint_css()
    inject_single_file_uploader_css()
    inject_checkbox_highlight_css()
    inject_chunk_load_recovery()
elif case == "navigation":
    from ui.navigation import _NAV_PAGES_SESSION_KEY, build_navigation

    build_navigation(st.session_state["cov_mode_keys"])
    st.session_state["cov_nav_urls"] = sorted(st.session_state[_NAV_PAGES_SESSION_KEY])
else:
    raise RuntimeError(f"unknown cov_case {case!r}")

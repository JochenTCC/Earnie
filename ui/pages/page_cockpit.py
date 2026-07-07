"""Cockpit-Seite: Sunset-2-Sunset-Produktivansicht (bestehender S-2-Block)."""
from __future__ import annotations

import config
from integrations import loxone_client
from version import __version__
from ui.auto_refresh import setup_auto_refresh
from ui.countdown import render_countdown_block
from ui.help_hint import render_page_title_with_help
from ui.history_navigation import is_live_s2_window
from ui.live_mode import render_optimization_savings_and_chart
from ui.main_py_sync import poll_main_py_sync_if_pending
from ui.runtime_config import reload_runtime_config
from ui.sankey import render_live_power_flow

_PAGE_TITLE = "🔋 Ernie Energy Control Center"
_COCKPIT_HELP = (
    "Produktiv-Cockpit **Sunset-2-Sunset**: Vergangenheit und Vorausschau "
    "in zwei Sonnenaufgang-Segmenten (SA₀→SA₁, SA₁→SA₂)."
)


def render() -> None:
    reload_runtime_config()
    if is_live_s2_window():
        setup_auto_refresh()
        poll_main_py_sync_if_pending()

    render_page_title_with_help(
        _PAGE_TITLE,
        _COCKPIT_HELP,
        key="cockpit_scope_help",
        version=__version__,
    )

    current_soc = loxone_client.fetch_loxone_generic_value(config.get("LOXONE_SOC_NAME"))
    render_optimization_savings_and_chart(current_soc)
    render_live_power_flow(current_soc)
    render_countdown_block()

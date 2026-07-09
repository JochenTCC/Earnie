"""Backtesting-Seite: wrappt ui/backtesting.py (Controls im Seiten-Body)."""
from __future__ import annotations

from ui.backtesting import render_backtesting_block
from ui.help_hint import render_page_title_with_help

_BACKTESTING_HELP = (
    "Backtesting aus der Konfiguration starten und Ergebnisse auswerten "
    "(Referenz ohne Optimierung vs. optimierte Szenarien). "
    "Läuft offline via `scripts.run_backtesting`."
)


def render() -> None:
    render_page_title_with_help(
        "📊 Backtesting",
        _BACKTESTING_HELP,
        key="backtesting_scope_help",
    )
    render_backtesting_block()

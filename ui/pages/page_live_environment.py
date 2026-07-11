"""Echtzeit-Umgebung: Live-Szenario wählen und Entitäts-Referenzen für den Echtzeitbetrieb."""
from __future__ import annotations

from ui.config_forms import render_live_environment_section
from ui.help_hint import render_page_title_with_help

_HELP = (
    "Wählt das Live-Szenario (`live_scenario_id` in `config.json`) und pflegt "
    "die Entitäts-Referenzen für Echtzeit-Optimierung und die Scenario-Exploration-Baseline. "
    "Batterie-Entitäten legst du im Hauskonfigurator an; weitere Szenarien im Szenarieneditor."
)


def render() -> None:
    render_page_title_with_help(
        "⚡ Live-Konfiguration",
        _HELP,
        key="live_environment_help",
    )
    render_live_environment_section()

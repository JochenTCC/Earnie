"""Seiten-Registry für die native Menüstruktur (st.navigation / st.Page).

Das Env-/Config-Gating (ENERGY_OPTIMIZER_UI_MODES, ui.price_forecast_page_enabled)
steuert nur noch, welche Seiten registriert werden. Cockpit, Manuelle Geräte und
die Konfigurations-/Mockup-Seiten sind immer verfügbar; Backtesting und
Preis-Prognose (Dev) folgen dem bisherigen Modus-Gating.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class PageSpec:
    """Beschreibt eine registrierbare Seite unabhängig von Streamlit."""

    render: Callable[[], None]
    title: str
    icon: str
    section: str
    url_path: str
    default: bool = False


def build_page_specs(enabled_mode_keys: list[str]) -> list[PageSpec]:
    """Liefert die zu registrierenden Seiten anhand des Modus-Gatings."""
    from ui.pages import (
        page_backtesting,
        page_cockpit,
        page_config,
        page_consumer_analysis,
        page_devices,
        page_house_config,
        page_price_forecast,
        page_scenario_editor,
    )

    specs: list[PageSpec] = [
        PageSpec(page_cockpit.render, "Cockpit", "🔋", "Betrieb", "cockpit", default=True),
        PageSpec(page_devices.render, "Manuelle Geräte", "🔌", "Betrieb", "devices"),
    ]
    if "backtesting" in enabled_mode_keys:
        specs.append(
            PageSpec(page_backtesting.render, "Backtesting", "📊", "Analyse", "backtesting")
        )
    if "price_forecast" in enabled_mode_keys:
        specs.append(
            PageSpec(
                page_price_forecast.render,
                "Preis-Prognose (Dev)",
                "💹",
                "Analyse",
                "price-forecast",
            )
        )
    specs.append(
        PageSpec(
            page_consumer_analysis.render,
            "Verbraucheranalyse",
            "📈",
            "Analyse",
            "consumer-analysis",
        )
    )
    specs += [
        PageSpec(page_config.render, "Konfiguration", "⚙️", "Konfiguration", "config"),
        PageSpec(
            page_scenario_editor.render,
            "Szenarieneditor",
            "🧪",
            "Konfiguration",
            "scenario-editor",
        ),
        PageSpec(
            page_house_config.render,
            "Hauskonfigurator",
            "🏠",
            "Konfiguration",
            "house-config",
        ),
    ]
    return specs


def build_navigation(enabled_mode_keys: list[str]):
    """Erzeugt die st.navigation-Struktur aus den aktiven Seiten-Specs."""
    import streamlit as st

    sections: dict[str, list] = {}
    for spec in build_page_specs(enabled_mode_keys):
        page = st.Page(
            spec.render,
            title=spec.title,
            icon=spec.icon,
            url_path="" if spec.default else spec.url_path,
            default=spec.default,
        )
        sections.setdefault(spec.section, []).append(page)
    return st.navigation(sections)

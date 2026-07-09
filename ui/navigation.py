"""Seiten-Registry für die native Menüstruktur (st.navigation / st.Page).

Das Env-/Config-Gating (ENERGY_OPTIMIZER_UI_MODES, ui.price_forecast_page_enabled)
steuert nur noch, welche Seiten registriert werden. Cockpit, Manuelle Geräte und
die Konfigurations-/Mockup-Seiten sind immer verfügbar; Backtesting und
Preis-Prognose (Dev) folgen dem bisherigen Modus-Gating.

Nach Minimal-Bootstrap (Greenfield) sind bis zur vollständigen Planungs-Konfiguration
nur Hauskonfigurator und Konfiguration sichtbar. Danach wird Analyse freigeschaltet;
Betrieb (Cockpit, Manuelle Geräte) erst nach vollständiger Loxone-Merker-Konfiguration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ui.setup_readiness import (
    is_betrieb_unlocked,
    is_planning_ready,
    is_scenario_editor_unlocked,
    is_setup_navigation_restricted,
)


@dataclass(frozen=True)
class PageSpec:
    """Beschreibt eine registrierbare Seite unabhängig von Streamlit."""

    render: Callable[[], None]
    title: str
    icon: str
    section: str
    url_path: str
    default: bool = False


def _restricted_page_specs() -> list[PageSpec]:
    from ui.pages import page_config, page_house_config

    return [
        PageSpec(
            page_house_config.render,
            "Hauskonfigurator",
            "🏠",
            "Konfiguration",
            "house-config",
            default=True,
        ),
        PageSpec(page_config.render, "Konfiguration", "⚙️", "Konfiguration", "config"),
    ]


def build_page_specs(enabled_mode_keys: list[str]) -> list[PageSpec]:
    """Liefert die zu registrierenden Seiten anhand des Modus-Gatings."""
    if is_setup_navigation_restricted():
        return _restricted_page_specs()

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

    specs: list[PageSpec] = []
    betrieb_unlocked = is_betrieb_unlocked()
    if betrieb_unlocked:
        specs.extend(
            [
                PageSpec(
                    page_cockpit.render,
                    "Cockpit",
                    "🔋",
                    "Betrieb",
                    "cockpit",
                    default=True,
                ),
                PageSpec(
                    page_devices.render,
                    "Manuelle Geräte",
                    "🔌",
                    "Betrieb",
                    "devices",
                ),
            ]
        )

    backtesting_allowed = "backtesting" in enabled_mode_keys and is_planning_ready()
    analyse_default = not betrieb_unlocked
    if backtesting_allowed:
        specs.append(
            PageSpec(
                page_backtesting.render,
                "Backtesting",
                "📊",
                "Analyse",
                "backtesting",
                default=analyse_default,
            )
        )
        analyse_default = False
    if "price_forecast" in enabled_mode_keys:
        specs.append(
            PageSpec(
                page_price_forecast.render,
                "Preis-Prognose (Dev)",
                "💹",
                "Analyse",
                "price-forecast",
                default=analyse_default,
            )
        )
        analyse_default = False
    specs.append(
        PageSpec(
            page_consumer_analysis.render,
            "Verbraucheranalyse",
            "📈",
            "Analyse",
            "consumer-analysis",
            default=analyse_default,
        )
    )
    specs.append(
        PageSpec(page_config.render, "Konfiguration", "⚙️", "Konfiguration", "config")
    )
    if is_scenario_editor_unlocked():
        specs.append(
            PageSpec(
                page_scenario_editor.render,
                "Szenarieneditor",
                "🧪",
                "Konfiguration",
                "scenario-editor",
            )
        )
    specs.append(
        PageSpec(
            page_house_config.render,
            "Hauskonfigurator",
            "🏠",
            "Konfiguration",
            "house-config",
        )
    )
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

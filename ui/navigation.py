"""Seiten-Registry für die native Menüstruktur (st.navigation / st.Page).

Das Env-/Config-Gating (EARNIE_UI_MODES / ENERGY_OPTIMIZER_UI_MODES)
steuert, welche Seiten registriert werden: Live-Cockpit (Monitor, Manuelle Geräte)
braucht ``sunset2sunset``; Live-Konfiguration und Daemon Control brauchen
``live_environment``; Szenario-Explorer und Preis-Prognose (Dev) folgen ihren
Keys. Konfigurations-Seiten bleiben über Setup-Readiness gesteuert.

Nach Minimal-Bootstrap (Greenfield) sind bis zur vollständigen Planungs-
Konfiguration nur Hauskonfigurator und ggf. Daemon Control sichtbar
(Szenarieneditor nach Hausprofil). Danach wird Szenario-Explorer freigeschaltet;
Live-Cockpit erst nach vollständiger Loxone-Merker-Konfiguration und wenn
``sunset2sunset`` in EARNIE_UI_MODES steht.
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

SECTION_BETRIEB = "Live-Cockpit"
SECTION_KONFIGURATION = "Konfiguration"
SECTION_ECHTZEIT = "Daemon Control"

_VA_OFFLINE_NOTICE = (
    "Verbraucheranalyse ist ohne Live-Verbindung zur Smarthome-Steuerung "
    "nicht verfügbar (EARNIE_OFFLINE oder unvollständige Live-Konfiguration). "
    "Bitte Live-Konfiguration abschließen bzw. Offline-Modus deaktivieren."
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


def wrap_offline_stub(
    render: Callable[[], None],
    notice: str,
    *,
    is_offline: Callable[[], bool] | None = None,
) -> Callable[[], None]:
    """Keep the nav entry; show ``notice`` instead of ``render`` when offline."""

    def _wrapped() -> None:
        import streamlit as st

        from runtime_store.env_vars import is_effective_offline

        offline_fn = is_offline or is_effective_offline
        if offline_fn():
            st.warning(notice)
            return
        render()

    return _wrapped


def _konfiguration_core_specs(*, house_config_default: bool) -> list[PageSpec]:
    from ui.pages import page_house_config, page_scenario_editor

    specs = [
        PageSpec(
            page_house_config.render,
            "Hauskonfigurator",
            "🏠",
            SECTION_KONFIGURATION,
            "house-config",
            default=house_config_default,
        ),
    ]
    if is_scenario_editor_unlocked():
        specs.append(
            PageSpec(
                page_scenario_editor.render,
                "Szenarieneditor",
                "🧪",
                SECTION_KONFIGURATION,
                "scenario-editor",
            )
        )
    return specs


def _live_konfiguration_spec() -> PageSpec:
    from ui.pages import page_live_environment

    return PageSpec(
        page_live_environment.render,
        "Live-Konfiguration",
        "⚡",
        SECTION_KONFIGURATION,
        "live-environment",
    )


def _echtzeit_page_specs() -> list[PageSpec]:
    from ui.pages import page_daemon, page_loxone_debug

    return [
        PageSpec(
            page_daemon.render,
            "Optimierer-Dienst",
            "🛠️",
            SECTION_ECHTZEIT,
            "optimizer-daemon",
        ),
        PageSpec(
            page_loxone_debug.render,
            "Loxone-Kommunikation",
            "🔗",
            SECTION_ECHTZEIT,
            "loxone-debug",
        ),
    ]


def _append_konfiguration_and_echtzeit(
    specs: list[PageSpec],
    enabled_mode_keys: list[str],
    *,
    house_config_default: bool,
    force_echtzeit: bool = False,
    scenario_explorer: PageSpec | None = None,
) -> None:
    specs.extend(_konfiguration_core_specs(house_config_default=house_config_default))
    show_live = force_echtzeit or "live_environment" in enabled_mode_keys
    if scenario_explorer is not None:
        specs.append(scenario_explorer)
    if show_live:
        specs.append(_live_konfiguration_spec())
        specs.extend(_echtzeit_page_specs())


def _restricted_page_specs(enabled_mode_keys: list[str]) -> list[PageSpec]:
    # Onboarding always needs Live-Konfiguration / daemon / Loxone pages,
    # even when EARNIE_UI_MODES is explorer-only (no live_environment key).
    specs: list[PageSpec] = []
    _append_konfiguration_and_echtzeit(
        specs,
        enabled_mode_keys,
        house_config_default=True,
        force_echtzeit=True,
    )
    return specs


def _ensure_one_default(specs: list[PageSpec]) -> list[PageSpec]:
    """If no page is default, mark the first as default."""
    if not specs or any(s.default for s in specs):
        return specs
    first = specs[0]
    return [
        PageSpec(
            first.render,
            first.title,
            first.icon,
            first.section,
            first.url_path,
            default=True,
        ),
        *specs[1:],
    ]


def build_page_specs(enabled_mode_keys: list[str]) -> list[PageSpec]:
    """Liefert die zu registrierenden Seiten anhand des Modus-Gatings."""
    if is_setup_navigation_restricted():
        return _restricted_page_specs(enabled_mode_keys)

    from ui.pages import (
        page_backtesting,
        page_cockpit,
        page_consumer_analysis,
        page_devices,
        page_price_forecast,
    )

    specs: list[PageSpec] = []
    betrieb_shown = (
        is_betrieb_unlocked() and "sunset2sunset" in enabled_mode_keys
    )
    if betrieb_shown:
        specs.extend(
            [
                PageSpec(
                    page_cockpit.render,
                    "Monitor",
                    "🔋",
                    SECTION_BETRIEB,
                    "cockpit",
                    default=True,
                ),
                PageSpec(
                    page_devices.render,
                    "Manuelle Geräte",
                    "🔌",
                    SECTION_BETRIEB,
                    "devices",
                ),
            ]
        )
        if "live_environment" in enabled_mode_keys:
            specs.append(
                PageSpec(
                    wrap_offline_stub(
                        page_consumer_analysis.render,
                        _VA_OFFLINE_NOTICE,
                    ),
                    "Verbraucheranalyse",
                    "📈",
                    SECTION_BETRIEB,
                    "consumer-analysis",
                )
            )

    if "price_forecast" in enabled_mode_keys:
        specs.append(
            PageSpec(
                page_price_forecast.render,
                "Preis-Prognose (Dev)",
                "💹",
                SECTION_BETRIEB,
                "price-forecast",
                default=not betrieb_shown and not any(s.default for s in specs),
            )
        )

    scenario_explorer: PageSpec | None = None
    if "scenario_explorer" in enabled_mode_keys and is_planning_ready():
        scenario_explorer = PageSpec(
            page_backtesting.render,
            "Szenario-Explorer",
            "📊",
            SECTION_KONFIGURATION,
            "scenario-explorer",
            default=not any(s.default for s in specs),
        )

    _append_konfiguration_and_echtzeit(
        specs,
        enabled_mode_keys,
        house_config_default=False,
        scenario_explorer=scenario_explorer,
    )
    return _ensure_one_default(specs)


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

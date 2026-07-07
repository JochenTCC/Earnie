"""Manuelle Geräte: Empfehlungsmodus (günstigste Startzeit im 6-h-Horizont).

Rein beratend (Schritt 3b, Backlog Z. 27): pro Gerät wird die Leistung
(Loxone-Merker oder manuelles Eingabefeld) und die Laufzeit erfasst und
darüber die günstigste Startstunde nach Netzbezugskosten ermittelt.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from data import profile_manager
from integrations import awattar_client
from optimizer.appliance_recommendation import (
    STAR_MAX,
    DEFAULT_HORIZON_H,
    ApplianceRecommendation,
    recommend_start_times,
)
from ui.help_hint import render_page_title_with_help

_DEVICES_HELP = (
    "Empfehlungsmodus für manuelle Geräte (Waschmaschine, Trockner, "
    "Geschirrspüler): günstigste Startstunde im nächsten 6-h-Horizont nach "
    "reinen Netzbezugskosten. Rein beratend — es wird kein Loxone-Signal "
    "geschaltet."
)
_DEFAULT_RUNTIME_H = 2.0


def render() -> None:
    render_page_title_with_help(
        "🔌 Manuelle Geräte", _DEVICES_HELP, key="devices_scope_help"
    )
    appliances = config.get_appliances()
    if not appliances:
        st.info(
            "Keine manuellen Geräte konfiguriert — 'appliances'-Block in "
            "config.json ergänzen (siehe config.example.json)."
        )
        return
    st.caption(
        f"Rein beratend · Ranking nach Netzbezugskosten · Horizont {DEFAULT_HORIZON_H} h."
    )
    matrix = _load_planning_matrix()
    if not matrix:
        return
    for appliance in appliances:
        _render_appliance(appliance, matrix)
        st.divider()


def _load_planning_matrix() -> list | None:
    """Stündliche Live-Planungsmatrix (Preis je Slot) oder None mit Fehlermeldung."""
    try:
        window = profile_manager.compute_live_planning_window()
        market_data = awattar_client.fetch_awattar_prices(planning_end=window.end)
    except Exception as exc:  # noqa: BLE001 — UI: jede Datenquelle als Fehler zeigen
        st.error(f"Planungsdaten konnten nicht geladen werden: {exc}")
        return None
    if not market_data:
        st.error("aWATTar-Börsenpreise konnten nicht geladen werden.")
        return None
    try:
        return profile_manager.build_live_planning_matrix(market_data, window)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Planungsmatrix konnte nicht erstellt werden: {exc}")
        return None


def _render_appliance(appliance: dict, matrix: list) -> None:
    st.markdown(f"#### {appliance['name']}")
    col_power, col_runtime = st.columns(2)
    power_kw = _resolve_power_kw(appliance, col_power)
    runtime_h = col_runtime.number_input(
        "Laufzeit (h)",
        min_value=0.25,
        value=float(appliance.get("default_runtime_h") or _DEFAULT_RUNTIME_H),
        step=0.25,
        key=f"appliance_runtime_{appliance['id']}",
    )
    if power_kw is None or power_kw <= 0:
        st.warning("Keine gültige Leistung — Empfehlung nicht möglich.")
        return
    _render_recommendation(matrix, power_kw, runtime_h)


def _resolve_power_kw(appliance: dict, col) -> float | None:
    """Nennleistung (kW) für die Kostenbewertung: manuelles Feld oder default_power_kw.

    Bei power_source=loxone dient der Loxone-Merker nur einem späteren
    Adaptionsalgo (der default_power_kw pflegt); hier wird kein Live-Wert
    abgefragt, sondern die konfigurierte Nennleistung verwendet.
    """
    if appliance["power_source"] == "manual":
        return col.number_input(
            "Leistung (kW)",
            min_value=0.0,
            value=float(appliance.get("default_power_kw") or 0.0),
            step=0.1,
            key=f"appliance_power_{appliance['id']}",
        )
    power = appliance.get("default_power_kw")
    col.metric("Nennleistung (kW)", f"{power:.2f}" if power else "—")
    if appliance.get("loxone_power_name"):
        col.caption(
            f"Nennleistung wird später per Adaptionsalgo aus Loxone-Merker "
            f"'{appliance['loxone_power_name']}' ermittelt."
        )
    return float(power) if power else None


def _render_recommendation(matrix: list, power_kw: float, runtime_h: float) -> None:
    try:
        rec = recommend_start_times(
            matrix, power_kw, runtime_h, horizon_h=DEFAULT_HORIZON_H
        )
    except ValueError as exc:
        st.warning(str(exc))
        return
    _render_cheapest_caption(rec)
    st.dataframe(_recommendation_dataframe(rec), hide_index=True, width="stretch")
    if rec.skipped_start_slots:
        st.caption(
            f"{rec.skipped_start_slots} spätere Startstunde(n) entfallen — "
            "Planungsdaten reichen nicht für die volle Laufzeit."
        )


def _render_cheapest_caption(rec: ApplianceRecommendation) -> None:
    best = rec.cheapest
    text = f"Günstigste Startzeit: **{best.start_datetime:%H:%M} Uhr** · {best.cost_eur:.2f} €"
    if best.savings_vs_now_eur > 0.005:
        text += f" · spart {best.savings_vs_now_eur:.2f} € ggü. sofort starten"
    st.success(text)


def _stars_text(stars: int) -> str:
    return "★" * stars + "☆" * (STAR_MAX - stars)


def _recommendation_dataframe(rec: ApplianceRecommendation) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Start": f"{option.start_datetime:%H:%M}",
                "Güte": _stars_text(option.stars),
                "Kosten (€)": round(option.cost_eur, 2),
                "Ersparnis (€)": round(option.savings_vs_now_eur, 2),
            }
            for option in rec.options
        ]
    )

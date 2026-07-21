"""Zeitraum-Erklärungen für die Backtesting-UI (cons_data vs. Simulation)."""
from __future__ import annotations

from datetime import date

import streamlit as st

import config
from data import cons_data_store
from data.data_loader import resolve_simulation_window

_PRICE_RANGE_DESCRIPTIONS = {
    "last_12_months": (
        "12 Kalendermonate bis zum letzten vollständigen Monat in cons_data "
        "(ein Fenster pro Tag, chronologisch)"
    ),
}


def configured_retention_months() -> int:
    return cons_data_store.get_retention_months()


def configured_price_range() -> str:
    sim = config.get_scenario_explorer_conf()
    return str(sim.get("price_range", "last_12_months"))


def default_simulation_window() -> tuple[date, date]:
    start, end = resolve_simulation_window(configured_price_range())
    return start.date(), end.date()


def describe_price_range(price_range: str) -> str:
    return _PRICE_RANGE_DESCRIPTIONS.get(price_range, price_range)


def cons_data_section_caption() -> str:
    months = configured_retention_months()
    return (
        f"Vollständige Datei (Aufbewahrung bis {months} Monate, "
        f"`cons_data_retention_months`). Der Backtesting-Lauf wertet nur den "
        f"Simulationszeitraum aus (`price_range`) — Hinweis bei **Backtesting starten**."
    )


def build_time_range_help_lines(*, log_period: dict | None = None) -> list[str]:
    retention = configured_retention_months()
    price_range = configured_price_range()
    sim_start, sim_end = default_simulation_window()
    lines = [
        (
            f"**`cons_data_hourly.csv`:** Aufbewahrung **{retention}** Monate "
            f"(`cons_data_retention_months`; ältere Stunden werden beim Speichern "
            f"entfernt). Die Visualisierung im Abschnitt oben zeigt die **gesamte Datei**."
        ),
        (
            f"**Backtesting-Simulation:** `price_range` = `{price_range}` "
            f"({describe_price_range(price_range)}) — aktuell "
            f"**{sim_start.isoformat()}** bis **{sim_end.isoformat()}**."
        ),
    ]
    if log_period and log_period.get("start") and log_period.get("end"):
        lines.append(
            "**Referenz-Verbrauch im Log:** nur Zeitraum des letzten Laufs "
            f"({log_period['start']} – {log_period['end']}), nicht die volle "
            "`cons_data`-Datei."
        )
    else:
        lines.append(
            "**Referenz-Verbrauch nach einem Lauf:** nur der gespeicherte "
            "Simulationszeitraum (geschnittene `cons_data`), nicht die volle Datei."
        )
    lines.append(
        "**Hauskonfigurator (Jahresverbrauch / Modell):** ein Referenzjahr "
        "(**8760 h**); unabhängig von der `cons_data`-Aufbewahrung."
    )
    return lines


def render_time_range_help(
    *,
    key: str,
    log_period: dict | None = None,
) -> None:
    with st.expander(
        "Zeiträume: cons_data, Simulation, Referenz",
        expanded=False,
        key=key,
    ):
        st.markdown(
            "\n".join(f"- {line}" for line in build_time_range_help_lines(log_period=log_period))
        )

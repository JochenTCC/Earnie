"""Monitor tile "Mit Earnie gespart" from the savings ledger (spec ``docs/dev/savings-ledger.md`` § 5).

The main figure is the lifetime total of the closed SA-days of the chain. The running
day stays apart ("Heute bisher") with the same figures as Chart 2, because its SoC
correction is provisional until the day closes.

Reads only: the daemon owns the ledger files (``savings_ledger_store.peek_state``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

import streamlit as st

import config
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from ui.chart_ledger_savings import open_day_figures
from ui.saving_text import euro_amount, saving_is_loss, saving_text, soc_correction_text

logger = logging.getLogger(__name__)

NOTICE_NOT_RUNNING = "Mit Earnie gespart: Das Ersparnis-Buch läuft noch nicht."
NOTICE_NO_BATTERY = "Mit Earnie gespart: Ohne Hausbatterie gibt es keinen Vergleich, das Ersparnis-Buch ruht."
NOTICE_UNREADABLE = "Mit Earnie gespart: Das Ersparnis-Buch ist nicht lesbar, Details stehen im Log."

_METHOD_HELP = (
    "**Vergleich:** gleicher Verbrauch, gleiche PV, Batterie im Herstellermodus "
    "(Eigenverbrauch), gleiche Preise. Gezählt sind die abgeschlossenen Tage von "
    "Sonnenaufgang zu Sonnenaufgang, jeweils mit der SoC-Korrektur.\n\n"
    "**Grenzen:** Verbraucher laufen im Vergleich zur selben Zeit wie gemessen, das "
    "Verschieben von Verbrauch ist also nicht bewertet. Was Powerstations aus ihrem "
    "Speicher liefern, ist nicht bewertet; ihr Laden zählt zur tatsächlichen Zeit. "
    "Das Ergebnis hängt vom eingestellten Batterie-Wirkungsgrad ab und ist keine "
    "Stromrechnung."
)


@dataclass(frozen=True)
class LedgerKpi:
    """Figures of the tile; ``total_euro`` is ``None`` while there is no result to show."""

    chain_start: datetime
    days: int
    incomplete_days: int
    total_euro: float | None
    today_saving_euro: float | None
    today_correction_euro: float | None


@dataclass(frozen=True)
class LedgerKpiNotice:
    """Why the tile has no figures; never shown as 0.00 €."""

    text: str
    is_warning: bool = False


def build_ledger_kpi(
    state: sl.LedgerState,
    battery_params: dict,
    rows: Sequence[dict[str, Any]],
    *,
    now: datetime,
) -> LedgerKpi:
    """Lifetime figures of the state's chain and the running day. Pure."""
    summary = sl.lifetime_summary(list(rows), state.chain_start)
    running = bool(state.slots) and state.day_start <= now < state.day_end
    today_saving, today_correction = (
        open_day_figures(state, battery_params) if running else (None, None)
    )
    return LedgerKpi(
        chain_start=state.chain_start,
        days=summary["days"],
        incomplete_days=summary["incomplete_days"],
        total_euro=summary["saving_adjusted_eur"] if summary["slots_present"] else None,
        today_saving_euro=today_saving,
        today_correction_euro=today_correction,
    )


def load_ledger_kpi(now: datetime) -> LedgerKpi | LedgerKpiNotice:
    """Figures from the runtime files, or the notice why there are none."""
    batteries = config.get_battery_params_list()
    if not batteries:
        return LedgerKpiNotice(NOTICE_NO_BATTERY)
    loaded = store.peek_state()
    if loaded.restart_reason == sl.CHAIN_STATE_UNREADABLE:
        return LedgerKpiNotice(NOTICE_UNREADABLE, is_warning=True)
    if loaded.state is None:
        return LedgerKpiNotice(NOTICE_NOT_RUNNING)
    try:
        return build_ledger_kpi(
            loaded.state, sl.shadow_battery_params(batteries), store.read_rows(), now=now
        )
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("savings ledger: the Monitor tile cannot read the ledger (%s).", exc)
        return LedgerKpiNotice(NOTICE_UNREADABLE, is_warning=True)


def _days_text(days: int) -> str:
    return "1 Tag" if days == 1 else f"{days} Tage"


def _incomplete_text(incomplete_days: int) -> str:
    if not incomplete_days:
        return "Unvollständige Tage: keine."
    return (
        f"Unvollständige Tage: {incomplete_days} (weniger als 80 % der Viertelstunden gebucht). "
        "Sie zählen mit und sind in Chart 2 markiert."
    )


def tile_help(kpi: LedgerKpi) -> str:
    return f"{_METHOD_HELP}\n\n{_incomplete_text(kpi.incomplete_days)}"


def today_text(kpi: LedgerKpi) -> str | None:
    """Running day as Chart 2 labels it, or ``None`` without booked slots of today."""
    if kpi.today_saving_euro is None or kpi.today_correction_euro is None:
        return None
    return (
        f"Heute bisher: {saving_text(kpi.today_saving_euro)} · "
        f"SoC-Korrektur: {soc_correction_text(kpi.today_correction_euro)}"
    )


def _since_text(kpi: LedgerKpi) -> str:
    return kpi.chain_start.strftime("%d.%m.%Y")


def _render_figures(kpi: LedgerKpi) -> None:
    if kpi.days == 0:
        st.caption(f"Mit Earnie gespart: Noch kein abgeschlossener Tag, Zählung seit {_since_text(kpi)}.")
    elif kpi.total_euro is None:
        st.caption(
            f"Mit Earnie gespart: nicht auswertbar. Seit {_since_text(kpi)} "
            "wurde keine Viertelstunde gebucht."
        )
    else:
        label = "Mit Earnie mehr ausgegeben" if saving_is_loss(kpi.total_euro) else "Mit Earnie gespart"
        st.metric(label, euro_amount(kpi.total_euro), help=tile_help(kpi))
        st.caption(f"seit {_since_text(kpi)} ({_days_text(kpi.days)})")


def render_ledger_kpi(now: datetime) -> None:
    """Tile above Chart 2; a missing result is named, not shown as a figure."""
    kpi = load_ledger_kpi(now)
    if isinstance(kpi, LedgerKpiNotice):
        if kpi.is_warning:
            st.warning(kpi.text)
        else:
            st.caption(kpi.text)
        return
    _render_figures(kpi)
    today = today_text(kpi)
    if today:
        st.caption(today)

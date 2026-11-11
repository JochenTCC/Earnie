"""Monitor tile "Mit Earnie gespart" from the savings ledger (spec ``docs/dev/savings-ledger.md`` § 5).

The main figure is the lifetime total of the closed SA-days of the chain, read from the
ledger files. The running day stays apart ("Heute bisher"), because its SoC correction
is provisional until the day closes. Its figures come from the dict Chart 2 draws
(``savings_view["ledger_savings"]``), so both show the same values of the same moment.

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
from ui.saving_text import euro_amount, saving_is_loss, saving_text, soc_correction_text

logger = logging.getLogger(__name__)

NOTICE_NOT_RUNNING = "Mit Earnie gespart: Das Ersparnis-Buch läuft noch nicht."
NOTICE_UNREADABLE = "Mit Earnie gespart: Das Ersparnis-Buch ist nicht lesbar, Details stehen im Log."

# Method note of savings_v 2 (spec docs/dev/savings-ledger.md § 3, § 7).
_METHOD_HELP = (
    "**Vergleich „ohne Earnie“:** gleiche PV, gleiche Preise und je Gerät der gleiche "
    "Tagesverbrauch, aber zur gewohnten Zeit: Geräte laufen nach ihrem Profil oder in ihrem "
    "Zeitfenster, der Poolfilter in seinem eigenen Fenster, das E-Auto lädt ab dem Einstecken "
    "mit voller Leistung, ein Heizstab neben Gas, Öl oder Pellets bleibt aus und die Wärme "
    "kommt aus dem Brennstoff. Eine Hausbatterie läuft im Herstellermodus (Eigenverbrauch). "
    "Gezählt sind die abgeschlossenen Tage von Sonnenaufgang zu Sonnenaufgang, jeweils mit "
    "der SoC-Korrektur.\n\n"
    "**Heute bisher** ist vorläufig: Es zählt nur die Batterie. Verschobene Geräte, E-Auto "
    "und Heizstab kommen beim Tagesabschluss dazu.\n\n"
    "**Grenzen:** Die gewohnte Zeit ist ein Profil, nicht der tatsächliche Tagesablauf. Die "
    "Szenario-Analyse vergleicht strenger, mit Standard-Regeln wie Laden bei PV-Überschuss; "
    "ihre Ersparnis ist deshalb meist kleiner. Was Powerstations aus ihrem Speicher liefern, "
    "ist nicht bewertet; ihr Laden zählt zur tatsächlichen Zeit. Das Ergebnis hängt vom "
    "eingestellten Batterie-Wirkungsgrad ab und ist keine Stromrechnung."
)
_OPENEMS_HELP = (
    "**OpenEMS:** Earnie liest hier keine Leistung je Gerät. Gezählt ist nur die Batterie."
)
# The chain-switch note stays this many closed days after a new chain for a new version.
CHAIN_SWITCH_NOTE_DAYS = 7


@dataclass(frozen=True)
class LedgerKpi:
    """Figures of the tile; ``total_euro`` is ``None`` while there is no result to show."""

    chain_start: datetime
    days: int
    incomplete_days: int
    total_euro: float | None
    chain_start_reason: str
    # Consumers of the newest closed day without their own meter (``flex_timing: logged_no_meter``).
    no_meter_names: tuple[str, ...]
    openems: bool


@dataclass(frozen=True)
class LedgerKpiNotice:
    """Why the tile has no figures; never shown as 0.00 €."""

    text: str
    is_warning: bool = False


def build_ledger_kpi(
    state: sl.LedgerState,
    rows: Sequence[dict[str, Any]],
    *,
    consumer_names: dict[str, str],
    openems: bool,
) -> LedgerKpi:
    """Lifetime figures of the state's chain. Pure.

    ``consumer_names`` maps consumer ids to the names the help shows; an id without a
    name (a consumer no longer configured) is shown as its id.
    """
    summary = sl.lifetime_summary(list(rows), state.chain_start)
    chain = [
        r
        for r in rows
        if r.get("chain_start") == state.chain_start.isoformat() and r.get("savings_v") == sl.SAVINGS_V
    ]
    no_meter: tuple[str, ...] = ()
    if chain:
        timing = chain[-1].get("flex_timing") or {}
        no_meter = tuple(
            consumer_names.get(cid, cid)
            for cid, label in sorted(timing.items())
            if label == "logged_no_meter"
        )
    return LedgerKpi(
        chain_start=state.chain_start,
        days=summary["days"],
        incomplete_days=summary["incomplete_days"],
        total_euro=summary["saving_adjusted_eur"] if summary["slots_present"] else None,
        chain_start_reason=state.chain_start_reason,
        no_meter_names=no_meter,
        openems=openems,
    )


def _consumer_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for consumer in config.get_flexible_consumers():
        name = str(consumer.get("name") or "").strip()
        if name:
            names[str(consumer["id"])] = name
    return names


def load_ledger_kpi() -> LedgerKpi | LedgerKpiNotice:
    """Figures from the runtime files, or the notice why there are none."""
    from integrations import ehal_live

    loaded = store.peek_state()
    if loaded.restart_reason == sl.CHAIN_STATE_UNREADABLE:
        return LedgerKpiNotice(NOTICE_UNREADABLE, is_warning=True)
    if loaded.state is None:
        return LedgerKpiNotice(NOTICE_NOT_RUNNING)
    try:
        return build_ledger_kpi(
            loaded.state,
            store.read_rows(),
            consumer_names=_consumer_names(),
            openems=ehal_live.is_openems_backend(),
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


def _no_meter_text(names: tuple[str, ...]) -> str | None:
    if not names:
        return None
    return (
        f"**Ohne eigenen Zähler:** {', '.join(names)}. Diese Geräte zählen im Vergleich zur "
        "gemessenen Zeit, ihr Verschieben ist nicht bewertet."
    )


def tile_help(kpi: LedgerKpi) -> str:
    parts = [_METHOD_HELP]
    if kpi.openems:
        parts.append(_OPENEMS_HELP)
    no_meter = _no_meter_text(kpi.no_meter_names)
    if no_meter:
        parts.append(no_meter)
    parts.append(_incomplete_text(kpi.incomplete_days))
    return "\n\n".join(parts)


def chain_switch_text(kpi: LedgerKpi) -> str | None:
    """One-time note after a new calculation version started a new count (first week)."""
    if kpi.chain_start_reason != sl.CHAIN_SAVINGS_V_CHANGED or kpi.days >= CHAIN_SWITCH_NOTE_DAYS:
        return None
    return (
        f"Neue Zählung seit {_since_text(kpi)}: Die Ersparnis zählt jetzt auch verschobene "
        "Geräte, das E-Auto ab dem Einstecken und den Heizstab. Die frühere Summe ist darin "
        "nicht enthalten."
    )


def today_text(ledger: dict[str, Any] | None, now: datetime) -> str | None:
    """Running day as Chart 2 shows it; ``None`` without figures or once the day has ended.

    ``ledger`` is ``savings_view["ledger_savings"]``, ``None`` without a display bundle.
    """
    if not ledger or ledger["saving_euro"] is None or ledger["soc_correction_euro"] is None:
        return None
    day_start = datetime.fromisoformat(ledger["open_day_start"])
    day_end = datetime.fromisoformat(ledger["open_day_end"])
    if not day_start <= now < day_end:
        return None
    return (
        f"Heute bisher (vorläufig): {saving_text(ledger['saving_euro'])} · "
        f"SoC-Korrektur: {soc_correction_text(ledger['soc_correction_euro'])}"
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


def render_ledger_kpi(now: datetime, ledger: dict[str, Any] | None) -> None:
    """Tile above Chart 2; a missing result is named, not shown as a figure."""
    kpi = load_ledger_kpi()
    if isinstance(kpi, LedgerKpiNotice):
        if kpi.is_warning:
            st.warning(kpi.text)
        else:
            st.caption(kpi.text)
        return
    _render_figures(kpi)
    switch = chain_switch_text(kpi)
    if switch:
        st.caption(switch)
    today = today_text(ledger, now)
    if today:
        st.caption(today)

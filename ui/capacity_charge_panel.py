"""Monitor block "Leistungspreis" (max-power tariff P6b): month peak, cap, amount, plan warning.

Shown only when the Live scenario has an import cap or the grid area has a capacity charge in the
current month. The month is the host clock's, as the peak store keeps it. A month without a stored
peak is unknown, never 0. The warning comes from ``runtime/import_cap_report.json``, which the
optimizer service writes each cycle (P6a, ``optimizer.import_cap_report``).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from house_config.import_cap import ImportCap, check_import_cap, parse_import_cap
from optimizer.import_cap_report import (
    CAUSE_LABELS_DE,
    NOT_PLANNED_AUTOMATIK,
    NOT_PLANNED_TRIVIAL,
)
from runtime_store.capacity_peak_store import MonthPeak
from ui.number_format import format_decimal, format_euro

NOT_PLANNED_LABELS_DE = {
    NOT_PLANNED_TRIVIAL: "Fenster ohne Optimierung (keine Batterie und keine flexiblen Verbraucher)",
    NOT_PLANNED_AUTOMATIK: "Automatikbetrieb, weil Earnie nicht planen konnte",
}


@dataclass(frozen=True)
class CapacityPanel:
    """What the block shows. Amounts are gross, with the VAT of the import tariff."""

    month: str  # YYYY-MM
    cap: ImportCap | None
    has_grid_area: bool
    cap_errors: tuple[str, ...]
    cap_notes: tuple[str, ...]
    charge: Any | None  # Edibert CapacityCharge of the month
    peak: MonthPeak | None
    billed_kw: float | None
    gross_eur: float | None
    minimum_gross_eur: float | None  # only while the month is unknown
    next_kw_gross_eur: float | None
    planning_limit_kw: float | None
    plan_report: dict[str, Any] | None
    measured: tuple[dict[str, Any], ...]


def build_capacity_panel(
    params: dict | None,
    now: datetime,
    *,
    read_peak: Callable[[str], MonthPeak | None],
    report: Mapping[str, Any],
) -> CapacityPanel | None:
    """The block for the resolved Live scenario ``params``; ``None`` when there is nothing to show.

    ``report``: ``import_cap_report_store.load()``. Edibert errors (gap in the grid area's charges,
    unreadable files) are raised, not hidden.
    """
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, grid_fee, tariff
    from house_config.edibert_tariffs import (
        IMPORT,
        capacity_charge_for_month,
        capacity_charge_net_eur,
    )

    cap = parse_import_cap(params)
    ref = params.get(EDIBERT_PRICING_KEY) if isinstance(params, dict) else None
    fee = grid_fee(ref) if isinstance(ref, dict) else None
    first_day = now.date().replace(day=1)
    charge = capacity_charge_for_month(fee, first_day) if fee is not None else None
    if cap is None and charge is None:
        return None
    month = f"{first_day:%Y-%m}"
    check = check_import_cap(cap, fee, first_day) if cap is not None else None
    peak = read_peak(month) if charge is not None else None
    billed_kw = gross = minimum = next_kw = limit = None
    if charge is not None:
        assert isinstance(ref, dict)  # a charge needs a grid area, which needs the reference
        factor = 1.0 + float(tariff(ref, IMPORT).vat_percent) / 100.0
        if peak is None:
            minimum = capacity_charge_net_eur(charge, 0.0) * factor
        else:
            billed_kw = max(float(peak.peak_kw), float(charge.min_kw))
            gross = capacity_charge_net_eur(charge, float(peak.peak_kw)) * factor
            next_kw = (
                capacity_charge_net_eur(charge, billed_kw + 1.0)
                - capacity_charge_net_eur(charge, billed_kw)
            ) * factor
        if cap is not None:
            peak_kw = float(peak.peak_kw) if peak is not None else 0.0
            limit = max(cap.cap_kw, peak_kw) - cap.margin_kw
    measured = tuple(report.get("measured", {}).get(month) or ()) if cap is not None else ()
    return CapacityPanel(
        month=month,
        cap=cap,
        has_grid_area=fee is not None,
        cap_errors=check.errors if check is not None else (),
        cap_notes=check.notes if check is not None else (),
        charge=charge,
        peak=peak,
        billed_kw=billed_kw,
        gross_eur=gross,
        minimum_gross_eur=minimum,
        next_kw_gross_eur=next_kw,
        planning_limit_kw=limit,
        plan_report=report.get("plan") if cap is not None and charge is not None else None,
        measured=measured,
    )


def _kw(value: float) -> str:
    return f"{format_decimal(value, 2)} kW"


def _slot(value: str) -> str:
    return datetime.fromisoformat(str(value)).strftime("%d.%m. %H:%M")


def _month_label(month: str) -> str:
    return datetime.strptime(month, "%Y-%m").strftime("%m/%Y")


def main_cause(slots: list[dict[str, Any]]) -> str:
    """The main cause found most often over the slots; on a tie the earliest slot's."""
    return Counter(str(entry["cause"]) for entry in slots).most_common(1)[0][0]


def _plan_rows(slots: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Viertelstunde": _slot(entry["slot"]),
                "Bezug geplant (kW)": entry["import_kw"],
                "Grenze (kW)": entry["limit_kw"],
                "Darüber (kW)": entry["over_kw"],
                "Ursachen": ", ".join(CAUSE_LABELS_DE[cause] for cause in entry["causes"]),
                "Verbraucher mit Ziel": ", ".join(
                    f"{cid} {format_decimal(kw, 2)} kW"
                    for cid, kw in (entry.get("consumers_kw") or {}).items()
                ),
            }
            for entry in slots
        ]
    )


def _measured_rows(events: tuple[dict[str, Any], ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Viertelstunde": _slot(event["slot"]),
                "Bezug gemessen (kW)": event["import_kw"],
                "Schwelle (kW)": event["threshold_kw"],
                "Darüber (kW)": event["over_kw"],
                "Ursache": CAUSE_LABELS_DE[event["cause"]],
            }
            for event in events
        ]
    )


def _render_figures(panel: CapacityPanel) -> None:
    charge = panel.charge
    peak = panel.peak
    min_kw = float(charge.min_kw)
    cols = st.columns(4)
    cols[0].metric(
        "Monatsspitze",
        _kw(peak.peak_kw) if peak is not None else "unbekannt",
        help="Höchste Viertelstunde des Netzbezugs im Monat, von Earnie selbst gemessen.",
    )
    cols[1].metric(
        "Abgerechnet",
        _kw(panel.billed_kw) if panel.billed_kw is not None else "unbekannt",
        help=f"Monatsspitze, mindestens die Mindestleistung des Netzbereichs ({_kw(min_kw)}).",
    )
    cols[2].metric(
        "Bisher (brutto)",
        format_euro(panel.gross_eur)
        if panel.gross_eur is not None
        else f"mind. {format_euro(panel.minimum_gross_eur)}",
        help="Leistungspreis des Monats bei der bisherigen Spitze, mit der USt des Bezugstarifs.",
    )
    cols[3].metric(
        "Nächstes kW",
        format_euro(panel.next_kw_gross_eur) if panel.next_kw_gross_eur is not None else "unbekannt",
        help="Was ein kW mehr Monatsspitze diesen Monat zusätzlich kostet (brutto).",
    )
    if peak is None:
        st.caption(
            f"Für {_month_label(panel.month)} ist noch keine Viertelstunde gemessen. "
            f"Mindestens fällt die Mindestleistung von {_kw(min_kw)} an."
        )
        return
    parts = [
        f"Gemessen seit {_slot(peak.first_slot)}, höchste Viertelstunde {_slot(peak.peak_slot)}."
    ]
    if peak.slots_missing:
        parts.append(f"{peak.slots_missing} Viertelstunden fehlen.")
    if float(peak.peak_kw) < min_kw:
        parts.append(f"Abgerechnet wird die Mindestleistung ({_kw(min_kw)}).")
    parts.append(
        f"Jedes kW über {_kw(panel.billed_kw)} kostet diesen Monat "
        f"{format_euro(panel.next_kw_gross_eur)}."
    )
    parts.append("Earnie misst selbst; maßgeblich ist die Abrechnung des Netzbetreibers.")
    st.caption(" ".join(parts))


def _render_cap(panel: CapacityPanel) -> None:
    cap = panel.cap
    assert cap is not None
    for error in panel.cap_errors:
        if panel.has_grid_area:
            st.warning(f"{error} Earnie plant mit der Grenze wie eingegeben.")
        else:
            st.error(error)
    for note in panel.cap_notes:
        st.info(note)
    if panel.planning_limit_kw is None:
        st.caption(f"Bezugsgrenze {_kw(cap.cap_kw)}, Reserve {_kw(cap.margin_kw)}.")
        return
    text = (
        f"Bezugsgrenze {_kw(cap.cap_kw)}, Reserve {_kw(cap.margin_kw)}: "
        f"geplant wird bis {_kw(panel.planning_limit_kw)}."
    )
    if panel.peak is not None and float(panel.peak.peak_kw) > cap.cap_kw:
        text += " Die Monatsspitze liegt schon über der Grenze; bis zu ihr plant Earnie frei, sie ist ohnehin bezahlt."
    st.caption(text)


def _render_report(panel: CapacityPanel) -> None:
    report = panel.plan_report
    if report is None:
        st.caption("Noch kein Bericht des Optimierer-Dienstes zur Bezugsgrenze.")
    elif not report["planned"]:
        st.info(
            "Der letzte Zyklus hat die Bezugsgrenze nicht eingeplant: "
            f"{NOT_PLANNED_LABELS_DE[report['reason']]}."
        )
    elif report["slots"]:
        slots = report["slots"]
        first = slots[0]
        st.warning(
            f"Der Plan hält die Bezugsgrenze in {len(slots)} Viertelstunde(n) nicht. "
            f"Erste: {_slot(first['slot'])}, {_kw(first['over_kw'])} über {_kw(first['limit_kw'])}. "
            f"Hauptursache: {CAUSE_LABELS_DE[main_cause(slots)]}."
        )
    else:
        st.caption(f"Der Plan ab {_slot(report['first_slot'])} hält die Bezugsgrenze.")
    if panel.measured:
        last = panel.measured[-1]
        st.caption(
            f"Gemessen über der Grenze in {_month_label(panel.month)}: {len(panel.measured)} "
            f"Viertelstunde(n), zuletzt {_slot(last['slot'])} ({CAUSE_LABELS_DE[last['cause']]})."
        )
    plan_slots = (report or {}).get("slots") or []
    if not plan_slots and not panel.measured:
        return
    with st.expander("Details zur Bezugsgrenze"):
        if plan_slots:
            st.markdown(f"**Plan ab {_slot(report['first_slot'])}**")
            st.dataframe(_plan_rows(plan_slots), hide_index=True, width="stretch")
        if panel.measured:
            st.markdown("**Gemessen**")
            st.dataframe(_measured_rows(panel.measured), hide_index=True, width="stretch")


def render_capacity_panel(panel: CapacityPanel) -> None:
    st.subheader("Leistungspreis")
    if panel.charge is not None:
        _render_figures(panel)
    if panel.cap is not None:
        _render_cap(panel)
        if panel.charge is not None:
            _render_report(panel)


def load_capacity_panel(now: datetime | None = None) -> CapacityPanel | None:
    """The block for the current Live configuration; ``None`` during onboarding or without both."""
    import config
    from runtime_store import import_cap_report_store
    from runtime_store.capacity_peak_store import month_peak

    if config.is_runtime_params_deferred():
        return None
    return build_capacity_panel(
        config.get_resolved_runtime_settings(),
        now or datetime.now(),
        read_peak=month_peak,
        report=import_cap_report_store.load(),
    )


def render_capacity_charge_panel(
    load: Callable[[], CapacityPanel | None] = load_capacity_panel,
) -> None:
    """Monitor entry point; an error is shown in the block, the rest of the page goes on."""
    placeholder = st.empty()
    try:
        panel = load()
        if panel is not None:
            with placeholder.container():
                render_capacity_panel(panel)
    except Exception as exc:  # noqa: BLE001 — shown to the user, the Monitor must still render
        with placeholder.container():
            st.subheader("Leistungspreis")
            st.error(f"Leistungspreis kann nicht angezeigt werden: {exc}")

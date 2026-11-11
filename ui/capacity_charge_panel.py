"""Monitor block "Leistungspreis" (max-power tariff P6b): month peak, cap, amount, plan warning.

Shown only when the Live scenario has an import cap or the grid area has a capacity charge in the
current month. The month is the host clock's, as the peak store keeps it. A month without a stored
peak is unknown, never 0. The warning comes from ``runtime/import_cap_report.json``, which the
optimizer service writes each cycle (P6a, ``optimizer.import_cap_report``).

Observe mode (P6d-2, decision O4): the figures stay the real ones; a second row compares the
measured and the hypothetical month peak over the same observed quarter hours
(``capacity_peaks_observe_measured.json``, ``capacity_peaks_observe.json``), with the estimated
saving on the charge and the extra energy cost of the latest plan with the cap, and the details
list the quarter hours where that plan would have acted differently.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from house_config.import_cap import (
    MODE_OBSERVE,
    ImportCap,
    check_import_cap,
    parse_import_cap,
    parse_import_cap_mode,
)
from optimizer.import_cap_report import (
    CAUSE_LABELS_DE,
    NOT_PLANNED_AUTOMATIK,
    NOT_PLANNED_SHADOW,
    NOT_PLANNED_TRIVIAL,
)
from runtime_store.capacity_peak_store import MonthPeak
from ui.number_format import format_decimal, format_euro

NOT_PLANNED_LABELS_DE = {
    NOT_PLANNED_TRIVIAL: "Fenster ohne Optimierung (keine Batterie und keine flexiblen Verbraucher)",
    NOT_PLANNED_AUTOMATIK: "Automatikbetrieb, weil Earnie nicht planen konnte",
    NOT_PLANNED_SHADOW: "Der Vergleichsplan mit Grenze war nicht lösbar",
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
    # Observe mode (P6d): ``mode`` of the Live scenario, ``None`` without a cap.
    mode: str | None = None
    observe_peak: MonthPeak | None = None
    # Measured peak over the same quarter hours as ``observe_peak``; the saving compares the two.
    observe_baseline_peak: MonthPeak | None = None
    saving_gross_eur: float | None = None
    interventions: tuple[dict[str, Any], ...] = ()

    @property
    def observe(self) -> bool:
        return self.mode == MODE_OBSERVE


def build_capacity_panel(
    params: dict | None,
    now: datetime,
    *,
    read_peak: Callable[[str], MonthPeak | None],
    report: Mapping[str, Any],
    read_observe_peak: Callable[[str], MonthPeak | None] | None = None,
    read_observe_baseline: Callable[[str], MonthPeak | None] | None = None,
) -> CapacityPanel | None:
    """The block for the resolved Live scenario ``params``; ``None`` when there is nothing to show.

    ``report``: ``import_cap_report_store.load()``. ``read_observe_peak`` and
    ``read_observe_baseline``: the hypothetical and the measured month peak over the observed
    quarter hours, both needed in observe mode. Edibert errors (gap in the grid area's charges, unreadable
    files) and a cap without mode are raised, not hidden.
    """
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, grid_fee, tariff
    from house_config.edibert_tariffs import (
        IMPORT,
        capacity_charge_for_month,
        capacity_charge_net_eur,
    )

    cap = parse_import_cap(params)
    mode = parse_import_cap_mode(params, required=True)
    observe = mode == MODE_OBSERVE
    if observe and (read_observe_peak is None or read_observe_baseline is None):
        raise ValueError("Beobachtungsmodus: Monatsspitzen der Beobachtung nicht übergeben.")
    ref = params.get(EDIBERT_PRICING_KEY) if isinstance(params, dict) else None
    fee = grid_fee(ref) if isinstance(ref, dict) else None
    first_day = now.date().replace(day=1)
    charge = capacity_charge_for_month(fee, first_day) if fee is not None else None
    if cap is None and charge is None:
        return None
    month = f"{first_day:%Y-%m}"
    check = check_import_cap(cap, fee, first_day) if cap is not None else None
    peak = read_peak(month) if charge is not None else None
    observe_peak = read_observe_peak(month) if observe and charge is not None else None
    baseline = read_observe_baseline(month) if observe and charge is not None else None
    billed_kw = gross = minimum = next_kw = limit = saving = None
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
        if observe_peak is not None and baseline is not None:
            # Both peaks cover the same observed quarter hours, so the saving is one period's.
            saving = (
                capacity_charge_net_eur(charge, float(baseline.peak_kw))
                - capacity_charge_net_eur(charge, float(observe_peak.peak_kw))
            ) * factor
        if cap is not None:
            # The plan's ratchet: in observe mode the shadow plan runs on the hypothetical peak.
            ratchet = observe_peak if observe else peak
            peak_kw = float(ratchet.peak_kw) if ratchet is not None else 0.0
            limit = max(cap.cap_kw, peak_kw) - cap.margin_kw
    # Events of the other mode (the mode was switched this month) are not this mode's checks.
    measured = (
        tuple(
            event
            for event in report.get("measured", {}).get(month) or ()
            if bool(event.get("hypothetical")) == observe
        )
        if cap is not None
        else ()
    )
    interventions = (
        tuple(report.get("interventions", {}).get(month) or ()) if observe else ()
    )
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
        mode=mode,
        observe_peak=observe_peak,
        observe_baseline_peak=baseline,
        saving_gross_eur=saving,
        interventions=interventions,
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


def _hypothetical_rows(events: tuple[dict[str, Any], ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Viertelstunde": _slot(event["slot"]),
                "Bezug gemessen (kW)": event["measured_kw"],
                "Mit Earnie geschätzt (kW)": event["import_kw"],
                "Schwelle (kW)": event["threshold_kw"],
                "Darüber (kW)": event["over_kw"],
                "Ursache": CAUSE_LABELS_DE[event["cause"]],
            }
            for event in events
        ]
    )


def _consumer_changes(entry: dict[str, Any]) -> str:
    executed = (entry.get("executed") or {}).get("consumers_kw") or {}
    shadow = (entry.get("shadow") or {}).get("consumers_kw") or {}
    changes = []
    for cid in sorted(set(executed) | set(shadow)):
        before, after = float(executed.get(cid, 0.0)), float(shadow.get(cid, 0.0))
        if abs(after - before) > 0.01:
            changes.append(f"{cid} {format_decimal(before, 2)} → {format_decimal(after, 2)} kW")
    return ", ".join(changes)


def _intervention_rows(entries: tuple[dict[str, Any], ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Viertelstunde": _slot(entry["slot"]),
                "Bezug gemessen (kW)": entry["measured_kw"],
                "Mit Earnie geschätzt (kW)": entry["hypothetical_kw"],
                "Änderung (kW)": entry["delta_kw"],
                "Batterie ohne → mit Grenze (kW)": (
                    f"{format_decimal(entry['executed']['battery_kw'], 2)} → "
                    f"{format_decimal(entry['shadow']['battery_kw'], 2)}"
                ),
                "Verbraucher": _consumer_changes(entry),
                "Ursache, falls über der Grenze": (
                    CAUSE_LABELS_DE[entry["cause"]] if entry.get("cause") else ""
                ),
            }
            for entry in entries
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


def _render_observe_figures(panel: CapacityPanel) -> None:
    """Second row in observe mode: both peaks of the observed quarter hours and the saving."""
    observed = panel.observe_peak
    baseline = panel.observe_baseline_peak
    report = panel.plan_report or {}
    block = report.get("observe") if report.get("mode") == MODE_OBSERVE else None
    extra = block.get("energy_cost_extra_eur") if block else None
    cols = st.columns(4)
    cols[0].metric(
        "Spitze ohne Earnie",
        _kw(baseline.peak_kw) if baseline is not None else "unbekannt",
        help="Höchste gemessene Viertelstunde seit Beginn der Beobachtung.",
    )
    cols[1].metric(
        "Spitze mit Earnie",
        _kw(observed.peak_kw) if observed is not None else "unbekannt",
        help=(
            "Geschätzt für dieselben Viertelstunden: je Viertelstunde der gemessene Bezug plus die "
            "Änderung, die der Plan mit Grenze in dieser Viertelstunde vorgesehen hätte."
        ),
    )
    cols[2].metric(
        "Ersparnis (geschätzt)",
        format_euro(panel.saving_gross_eur) if panel.saving_gross_eur is not None else "unbekannt",
        help=(
            "Leistungspreis bei der Spitze ohne Earnie minus Leistungspreis bei der Spitze mit "
            "Earnie, beide seit Beginn der Beobachtung (brutto)."
        ),
    )
    cols[3].metric(
        "Mehrkosten Energie",
        format_euro(extra) if extra is not None else "unbekannt",
        help=(
            "Was das Einhalten der Grenze im aktuellen Plan an Strom mehr kostet, über den ganzen "
            "Planungshorizont. Schätzung; keine Monatssumme."
        ),
    )
    parts = []
    if observed is None:
        parts.append(
            f"Für {_month_label(panel.month)} liegt noch keine geschätzte Viertelstunde vor."
        )
    else:
        parts.append(f"Beide Spitzen seit {_slot(observed.first_slot)}.")
        if observed.slots_missing:
            parts.append(f"{observed.slots_missing} Viertelstunden ohne Vergleich zählen nicht.")
    parts.append(
        "Jeder Vergleichsplan startet vom tatsächlichen Zustand (Batterie, Verbraucher); "
        "die Werte sind eine Schätzung."
    )
    st.caption(" ".join(parts))


def _render_cap(panel: CapacityPanel) -> None:
    cap = panel.cap
    assert cap is not None
    if panel.observe:
        st.info(
            "Beobachtungsmodus: Earnie plant und steuert ohne die Bezugsgrenze und zeigt hier, "
            "wo und wie er eingegriffen hätte. Umstellen im Szenario-Editor beim Live-Szenario "
            "(„Im Live-Betrieb“: Danach planen)."
        )
    for error in panel.cap_errors:
        if panel.has_grid_area:
            used_by = "Der Vergleichsplan rechnet" if panel.observe else "Earnie plant"
            st.warning(f"{error} {used_by} mit der Grenze wie eingegeben.")
        else:
            st.error(error)
    for note in panel.cap_notes:
        st.info(note)
    if panel.planning_limit_kw is None:
        st.caption(f"Bezugsgrenze {_kw(cap.cap_kw)}, Reserve {_kw(cap.margin_kw)}.")
        return
    planned = "der Vergleichsplan rechnet" if panel.observe else "geplant wird"
    text = (
        f"Bezugsgrenze {_kw(cap.cap_kw)}, Reserve {_kw(cap.margin_kw)}: "
        f"{planned} bis {_kw(panel.planning_limit_kw)}."
    )
    ratchet = panel.observe_peak if panel.observe else panel.peak
    if ratchet is not None and float(ratchet.peak_kw) > cap.cap_kw:
        text += (
            " Die geschätzte Monatsspitze liegt schon über der Grenze; bis zu ihr hätte Earnie "
            "frei geplant."
            if panel.observe
            else " Die Monatsspitze liegt schon über der Grenze; bis zu ihr plant Earnie frei, sie ist ohnehin bezahlt."
        )
    st.caption(text)


def _render_report(panel: CapacityPanel) -> None:
    report = panel.plan_report
    if report is not None and (report.get("mode") == MODE_OBSERVE) != panel.observe:
        # The mode was just switched; the next cycle writes a report of the new mode.
        report = None
    plan_name = "Der Vergleichsplan mit Grenze" if panel.observe else "Der Plan"
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
            f"{plan_name} hält die Bezugsgrenze in {len(slots)} Viertelstunde(n) nicht. "
            f"Erste: {_slot(first['slot'])}, {_kw(first['over_kw'])} über {_kw(first['limit_kw'])}. "
            f"Hauptursache: {CAUSE_LABELS_DE[main_cause(slots)]}."
        )
    else:
        st.caption(f"{plan_name} ab {_slot(report['first_slot'])} hält die Bezugsgrenze.")
    if panel.interventions:
        last = panel.interventions[-1]
        st.caption(
            f"Eingegriffen hätte Earnie in {_month_label(panel.month)} in "
            f"{len(panel.interventions)} Viertelstunde(n), zuletzt {_slot(last['slot'])}."
        )
    if panel.measured:
        last = panel.measured[-1]
        what = "Mit Earnie geschätzt" if panel.observe else "Gemessen"
        st.caption(
            f"{what} über der Grenze in {_month_label(panel.month)}: {len(panel.measured)} "
            f"Viertelstunde(n), zuletzt {_slot(last['slot'])} ({CAUSE_LABELS_DE[last['cause']]})."
        )
    plan_slots = (report or {}).get("slots") or []
    if not plan_slots and not panel.measured and not panel.interventions:
        return
    with st.expander("Details zur Bezugsgrenze"):
        if panel.interventions:
            st.markdown("**Wo Earnie eingegriffen hätte**")
            st.dataframe(
                _intervention_rows(panel.interventions), hide_index=True, width="stretch"
            )
        if plan_slots:
            st.markdown(f"**{plan_name} ab {_slot(report['first_slot'])}**")
            st.dataframe(_plan_rows(plan_slots), hide_index=True, width="stretch")
        if panel.measured and panel.observe:
            st.markdown("**Mit Earnie geschätzt über der Grenze**")
            st.dataframe(_hypothetical_rows(panel.measured), hide_index=True, width="stretch")
        elif panel.measured:
            st.markdown("**Gemessen**")
            st.dataframe(_measured_rows(panel.measured), hide_index=True, width="stretch")


def render_capacity_panel(panel: CapacityPanel) -> None:
    st.subheader("Leistungspreis")
    if panel.charge is not None:
        _render_figures(panel)
        if panel.observe:
            _render_observe_figures(panel)
    if panel.cap is not None:
        _render_cap(panel)
        if panel.charge is not None:
            _render_report(panel)


def load_capacity_panel(now: datetime | None = None) -> CapacityPanel | None:
    """The block for the current Live configuration; ``None`` during onboarding or without both."""
    import config
    from runtime_store import import_cap_report_store
    from runtime_store.capacity_peak_store import month_peak, observe_baseline_path, observe_path

    if config.is_runtime_params_deferred():
        return None
    observe_file = observe_path()
    baseline_file = observe_baseline_path()
    return build_capacity_panel(
        config.get_resolved_runtime_settings(),
        now or datetime.now(),
        read_peak=month_peak,
        report=import_cap_report_store.load(),
        read_observe_peak=lambda month: month_peak(month, path=observe_file),
        read_observe_baseline=lambda month: month_peak(month, path=baseline_file),
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

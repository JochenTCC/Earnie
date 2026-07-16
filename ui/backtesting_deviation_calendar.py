"""Kalender-Index und UI für Backtesting-Abweichungen."""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime

import streamlit as st

from scripts.run_backtesting import BACKTESTING_YEAR
from simulation.backtesting_log import KIND_CRITICALITY_ORDER
from simulation.backtesting_snapshots import normalize_window_anchor_key
from simulation.engine import CONSUMPTION_TOLERANCE_KWH, window_anchor_for_date
from ui.backtesting_results_helpers import nav_bounds_from_period

SEVERITY_NONE = "none"
SEVERITY_YELLOW = "yellow"
SEVERITY_ORANGE = "orange"
SEVERITY_RED = "red"
SEVERITY_DISABLED = "disabled"

_SEVERITY_RANK: dict[str, int] = {
    SEVERITY_RED: 0,
    SEVERITY_ORANGE: 1,
    SEVERITY_YELLOW: 2,
    SEVERITY_NONE: 3,
    SEVERITY_DISABLED: 4,
}

_RED_KINDS = frozenset({"milp_no_optimal", "strict_slow", "strict_fallback"})
_GERMAN_MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
_WEEKDAY_HEADERS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
_SESSION_DATE_KEY = "backtesting_calendar_date"
_SESSION_MONTH_KEY = "backtesting_calendar_month"
_DAY_MARKER = {
    SEVERITY_NONE: "⚪",
    SEVERITY_YELLOW: "🟡",
    SEVERITY_ORANGE: "🟠",
    SEVERITY_RED: "🔴",
}


def deviation_marker_for_case(case: dict | None) -> str:
    """Emoji-Marker für Szenario-Checkbox wenn Abweichung vorliegt."""
    if case is None:
        return ""
    return _DAY_MARKER.get(case_severity(case), "")


@dataclass
class CalendarCellState:
    date: date
    in_run: bool
    severity: str
    anchor_iso: str | None = None
    cases_by_scenario: dict[str, dict] = field(default_factory=dict)


def anchor_for_calendar_date(cell_date: date) -> datetime:
    """Kalendertag → Fenster-Anker (wie simulation.engine.window_anchor_for_date)."""
    return window_anchor_for_date(cell_date)


def case_severity(case: dict) -> str:
    kind = str(case.get("kind", ""))
    if kind in _RED_KINDS:
        if case.get("window_consumption_ok") is True:
            return SEVERITY_YELLOW
        return SEVERITY_RED
    if kind == "consumption_tolerance":
        diff = abs(float(case.get("diff_kwh") or 0.0))
        if diff <= CONSUMPTION_TOLERANCE_KWH:
            return SEVERITY_YELLOW
        return SEVERITY_ORANGE
    return SEVERITY_NONE


def worst_severity(cases: list[dict]) -> str:
    if not cases:
        return SEVERITY_NONE
    best_rank = min(_SEVERITY_RANK.get(case_severity(case), 99) for case in cases)
    for severity, rank in _SEVERITY_RANK.items():
        if rank == best_rank:
            return severity
    return SEVERITY_NONE


def _worst_case_for_scenario(cases: list[dict]) -> dict | None:
    if not cases:
        return None
    return min(
        cases,
        key=lambda case: (
            KIND_CRITICALITY_ORDER.get(str(case.get("kind", "")), 99),
            -abs(float(case.get("diff_kwh") or 0.0)),
        ),
    )


def _period_date_bounds(period: dict) -> tuple[date, date] | None:
    bounds = nav_bounds_from_period(period)
    if bounds is None:
        return None
    start, end = bounds
    return start.date(), end.date()


def build_deviation_calendar_index(
    meta: dict,
    cases: list[dict],
    *,
    run_anchors: list[datetime],
) -> dict[date, CalendarCellState]:
    """Baut Zellzustände für Jan–Dez des Backtesting-Jahres."""
    period = meta.get("period") or {}
    year = int(period.get("backtesting_year") or BACKTESTING_YEAR)
    period_bounds = _period_date_bounds(period)
    run_anchor_keys = {
        normalize_window_anchor_key(anchor) for anchor in run_anchors
    }

    cases_by_anchor: dict[str, list[dict]] = {}
    for case in cases:
        anchor = case.get("window_anchor")
        if not anchor:
            continue
        key = normalize_window_anchor_key(str(anchor))
        cases_by_anchor.setdefault(key, []).append(case)

    index: dict[date, CalendarCellState] = {}
    for month in range(1, 13):
        days_in_month = calendar.monthrange(year, month)[1]
        for day in range(1, days_in_month + 1):
            cell_date = date(year, month, day)
            anchor = anchor_for_calendar_date(cell_date)
            anchor_key = normalize_window_anchor_key(anchor)
            in_period = (
                period_bounds is not None
                and period_bounds[0] <= cell_date <= period_bounds[1]
            )
            in_run = in_period and anchor_key in run_anchor_keys
            day_cases = cases_by_anchor.get(anchor_key, [])
            cases_by_scenario: dict[str, dict] = {}
            for scenario_id in {str(c.get("scenario_id", "?")) for c in day_cases}:
                scenario_cases = [
                    c for c in day_cases if str(c.get("scenario_id")) == scenario_id
                ]
                worst = _worst_case_for_scenario(scenario_cases)
                if worst is not None:
                    cases_by_scenario[scenario_id] = worst
            severity = worst_severity(day_cases) if in_run else SEVERITY_DISABLED
            index[cell_date] = CalendarCellState(
                date=cell_date,
                in_run=in_run,
                severity=severity,
                anchor_iso=anchor_key if in_run else None,
                cases_by_scenario=cases_by_scenario,
            )
    return index


def cases_for_date_and_scenario(
    index: dict[date, CalendarCellState],
    cell_date: date,
    scenario_id: str,
) -> dict | None:
    cell = index.get(cell_date)
    if cell is None or not cell.in_run:
        return None
    return cell.cases_by_scenario.get(scenario_id)


def scenario_ids_for_date(
    index: dict[date, CalendarCellState],
    cell_date: date,
    *,
    fallback_scenario_ids: list[str],
) -> list[str]:
    cell = index.get(cell_date)
    if cell is None or not cell.in_run:
        return []
    from_index = sorted(cell.cases_by_scenario.keys())
    if from_index:
        return from_index
    return list(fallback_scenario_ids)


def _month_grid_weeks(year: int, month: int) -> list[list[int | None]]:
    cal = calendar.Calendar(firstweekday=0)
    weeks: list[list[int | None]] = []
    week: list[int | None] = []
    for day in cal.itermonthdays(year, month):
        week.append(day if day != 0 else None)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        while len(week) < 7:
            week.append(None)
        weeks.append(week)
    return weeks


def _stored_selected_date() -> date | None:
    stored = st.session_state.get(_SESSION_DATE_KEY)
    if isinstance(stored, date):
        return stored
    if isinstance(stored, str):
        try:
            return date.fromisoformat(stored)
        except ValueError:
            return None
    return None


def month_with_most_deviation_days(
    index: dict[date, CalendarCellState],
    *,
    year: int,
) -> int | None:
    """Monat mit den meisten in-run Tagen mit mindestens einer Abweichung."""
    counts = {month: 0 for month in range(1, 13)}
    for cell_date, cell in index.items():
        if cell_date.year != year or not cell.in_run or not cell.cases_by_scenario:
            continue
        counts[cell_date.month] += 1
    best = max(counts.values())
    if best <= 0:
        return None
    return min(month for month, count in counts.items() if count == best)


def _default_visible_month(
    index: dict[date, CalendarCellState],
    year: int,
    selected_date: date | None,
) -> int:
    stored = st.session_state.get(_SESSION_MONTH_KEY)
    if isinstance(stored, int) and 1 <= stored <= 12:
        return stored
    if selected_date is not None and selected_date.year == year:
        return selected_date.month
    deviation_month = month_with_most_deviation_days(index, year=year)
    if deviation_month is not None:
        return deviation_month
    default = default_calendar_date(index)
    if default is not None and default.year == year:
        return default.month
    for month in range(1, 13):
        if any(
            cell.in_run
            for cell_date, cell in index.items()
            if cell_date.year == year and cell_date.month == month
        ):
            return month
    return 1


def _render_month(
    year: int,
    month: int,
    index: dict[date, CalendarCellState],
    selected_date: date | None,
) -> date | None:
    header_cols = st.columns(7)
    for col, label in zip(header_cols, _WEEKDAY_HEADERS, strict=True):
        col.markdown(f"**{label}**")

    clicked: date | None = None
    for week in _month_grid_weeks(year, month):
        day_cols = st.columns(7)
        for col, day in zip(day_cols, week, strict=True):
            with col:
                if day is None:
                    st.write("")
                    continue
                cell_date = date(year, month, day)
                cell = index[cell_date]
                if not cell.in_run:
                    st.button(str(day), disabled=True, key=f"cal_off_{cell_date.isoformat()}")
                    continue
                marker = _DAY_MARKER.get(cell.severity, "⚪")
                label = f"{marker}{day}"
                is_selected = selected_date == cell_date
                if st.button(
                    label,
                    key=f"cal_day_{cell_date.isoformat()}",
                    type="primary" if is_selected else "secondary",
                ):
                    clicked = cell_date
    return clicked


def render_deviation_calendar(
    index: dict[date, CalendarCellState],
    meta: dict,
) -> date | None:
    """Ein Monat mit Zurück/Vor-Navigation; gibt gewählten Kalendertag zurück."""
    period = meta.get("period") or {}
    year = int(period.get("backtesting_year") or BACKTESTING_YEAR)
    selected_date = _stored_selected_date()
    visible_month = _default_visible_month(index, year, selected_date)
    st.session_state[_SESSION_MONTH_KEY] = visible_month

    st.caption(
        "Legende: ⚪ ohne Abweichung · 🟡 Verbrauchstoleranz (≤ "
        f"{CONSUMPTION_TOLERANCE_KWH:g} kWh) / CBC-Marker bei feasiblem 24h-Ergebnis · "
        "🟠 darüber · 🔴 CBC/MILP mit echtem Problem · "
        "ausgegraut = außerhalb Lauf"
    )

    nav_prev, nav_title, nav_next = st.columns([1, 3, 1])
    with nav_prev:
        if st.button(
            "Zurück",
            disabled=visible_month <= 1,
            key="backtesting_calendar_prev",
        ):
            st.session_state[_SESSION_MONTH_KEY] = visible_month - 1
            st.rerun()
    with nav_title:
        st.markdown(f"**{_GERMAN_MONTHS[visible_month - 1]} {year}**")
    with nav_next:
        if st.button(
            "Vor",
            disabled=visible_month >= 12,
            key="backtesting_calendar_next",
        ):
            st.session_state[_SESSION_MONTH_KEY] = visible_month + 1
            st.rerun()

    clicked_date = _render_month(year, visible_month, index, selected_date)
    if clicked_date is not None:
        st.session_state[_SESSION_DATE_KEY] = clicked_date
        st.session_state[_SESSION_MONTH_KEY] = clicked_date.month
        return clicked_date
    return selected_date


def default_calendar_date(index: dict[date, CalendarCellState]) -> date | None:
    """Erster in-run Tag mit Abweichung, sonst erster in-run Tag."""
    deviation_dates = sorted(
        cell.date for cell in index.values() if cell.in_run and cell.cases_by_scenario
    )
    if deviation_dates:
        return deviation_dates[0]
    in_run = sorted(cell.date for cell in index.values() if cell.in_run)
    return in_run[0] if in_run else None

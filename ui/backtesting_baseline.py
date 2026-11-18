"""Baseline of the SE cost table, switchable after the run from the stored series.

Live always runs, so it is always a baseline. Besides it, every reference the run computed
(``references`` in the log): Historisch, Referenz ohne Speicher (L0) and L1. For L0 and L1 a
scenario compares with its own series or with Live's. Nothing is recomputed: every series is
in the log already.
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from simulation.reference_costs import HISTORICAL_REFERENCE_ID
from simulation.reference_selection import REF_HISTORICAL, REF_L0, REF_L1

BASELINE_LIVE = "live"
SERIES_OWN = "own"
SERIES_LIVE = "live"
PER_SCENARIO_BASELINES = (REF_L0, REF_L1)
BASELINE_LABELS = {
    BASELINE_LIVE: "Live (mit Earnie)",
    REF_HISTORICAL: "Historisch",
    REF_L0: "Referenz ohne Speicher",
    REF_L1: "Wechselrichter-Eigenverbrauch (L1)",
}
SERIES_LABELS = {
    SERIES_OWN: "Eigene Reihe des Szenarios",
    SERIES_LIVE: "Reihe von Live",
}
_BASELINE_KEY = "backtesting_baseline"
_SERIES_KEY = "backtesting_baseline_series"
NO_REFERENCES_INFO = (
    "Dieser Lauf ist älter als die Referenzauswahl: Die Vergleichsbasis lässt sich erst nach "
    "einer Neuberechnung wählen, die Spalte Δ bleibt leer."
)


@dataclass(frozen=True)
class SeBaseline:
    """What every scenario's Δ in the cost table is measured against."""

    kind: str
    series: str = SERIES_LIVE

    @property
    def column(self) -> str:
        label = BASELINE_LABELS[self.kind]
        if self.kind in PER_SCENARIO_BASELINES:
            label += " (eigene)" if self.series == SERIES_OWN else " von Live"
        return f"Δ vs {label} [€]"

    def result_id(self, meta: dict, scenario_id: str, live_id: str | None) -> str | None:
        """Result id the scenario is compared with; ``None`` when the log has none for it."""
        if self.kind == BASELINE_LIVE:
            return live_id
        if self.kind == REF_HISTORICAL:
            return HISTORICAL_REFERENCE_ID
        owner = scenario_id if self.series == SERIES_OWN else live_id
        by_scenario = meta.get("reference_by_scenario" if self.kind == REF_L0 else "l1_by_scenario")
        return (by_scenario or {}).get(owner) if owner else None


def baseline_options(meta: dict, totals: dict, live_id: str | None) -> list[str] | None:
    """Baselines this log offers; ``None`` for a log from before the reference selection."""
    references = meta.get("references")
    if references is None:
        return None
    options = [BASELINE_LIVE] if live_id and live_id in totals else []
    return options + [ref for ref in (REF_HISTORICAL, REF_L0, REF_L1) if ref in references]


def default_baseline(options: list[str]) -> SeBaseline:
    """Live's Referenz ohne Speicher when it ran (the comparison before 2.8), else the first.

    The series defaults to Live's for every baseline, so switching to L0 or L1 later starts
    on "Reihe von Live" as well.
    """
    if REF_L0 in options:
        return SeBaseline(REF_L0, SERIES_LIVE)
    return SeBaseline(options[0], SERIES_LIVE)


def render_baseline_selector(meta: dict, totals: dict, live_id: str | None) -> SeBaseline | None:
    """Selectors above the cost table; ``None`` when the log offers no baseline."""
    options = baseline_options(meta, totals, live_id)
    if options is None:
        st.info(NO_REFERENCES_INFO)
        return None
    if not options:
        return None
    default = default_baseline(options)
    if st.session_state.get(_BASELINE_KEY) not in options:
        st.session_state[_BASELINE_KEY] = default.kind
    if st.session_state.get(_SERIES_KEY) not in SERIES_LABELS:
        st.session_state[_SERIES_KEY] = default.series
    kind_col, series_col = st.columns(2)
    kind = kind_col.selectbox(
        "Vergleichsbasis",
        options=options,
        format_func=BASELINE_LABELS.__getitem__,
        key=_BASELINE_KEY,
        help=(
            "Womit die Spalte Δ jedes Szenario vergleicht. Zur Wahl stehen Live und die "
            "Referenzen, die dieser Lauf berechnet hat. Der Wechsel rechnet nichts neu."
        ),
    )
    if kind not in PER_SCENARIO_BASELINES:
        return SeBaseline(kind)
    series = series_col.radio(
        "Reihe",
        options=list(SERIES_LABELS),
        format_func=SERIES_LABELS.__getitem__,
        key=_SERIES_KEY,
        horizontal=True,
        help=(
            "Eigene Reihe: die Referenz mit Tarif, PV und Speicher des Szenarios. "
            "Reihe von Live: alle Szenarien gegen dieselbe Referenz von Live."
        ),
    )
    return SeBaseline(kind, series)

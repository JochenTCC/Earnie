"""SE headline against the standard rules and the reference ladder L0–L3 (RuleRef P4).

Spec: ``docs/dev/rule-based-reference.md`` § 7 O5. Amounts are those of the cost table: booked
costs with fees and fuel, and the end-SoC term of § 3.3 on L1 and L2, so the headline equals
the column ``Ersparnis vs. Standard-Regeln``.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from simulation.reference_costs import LADDER_L1, LADDER_L2
from simulation.reference_ladder import rule_share
from ui.backtesting_results_helpers import (
    _DASH,
    _annual_cost_row_order,
    _soc_correction_block,
    _totals_with_fuel,
)
from ui.number_format import format_euro
from ui.saving_text import saving_text

STEP_L0 = "l0"
STEP_L3 = "l3"
_STEPS = (STEP_L0, LADDER_L1, LADDER_L2, STEP_L3)
_STEP_NAMES = {
    STEP_L0: "Ohne Steuerung",
    LADDER_L1: "Wechselrichter-Eigenverbrauch",
    LADDER_L2: "Standard-Regeln",
    STEP_L3: "Earnie",
}
_STEP_CONTENT = {
    STEP_L0: "Keine Batterie, Verbraucher zu ihren üblichen Zeiten",
    LADDER_L1: "Batterie im Eigenverbrauchsmodus, Verbraucher zu ihren üblichen Zeiten",
    LADDER_L2: "Batterie im Eigenverbrauchsmodus, PV-Überschussladen, Preissperre, günstigste Stunden",
    STEP_L3: "Batterie und Verbraucher nach dem Plan von Earnie",
}
_METRICS_PER_ROW = 3
_HEADLINE_HELP = (
    "Kosten mit Standard-Regeln minus Kosten mit Earnie: das, was Earnie über Batterie und "
    "freie Regeln hinaus bringt. Der Anteil der Regeln sagt, wie viel der Gesamtersparnis "
    "gegen „Ohne Steuerung“ man auch ohne Earnie erreicht. Die Standard-Regeln ersetzen die "
    "frühere Referenz ohne Optimierung, deshalb ist dieser Wert kleiner als die frühere "
    "Ersparnis. Das liegt an der Methode, nicht an einer schlechteren Optimierung."
)
_HEADLINE_CAPTION = (
    "Earnie plant im Szenario-Explorer mit bekannten PV-, Last- und Preisverläufen, die "
    "Ersparnis ist deshalb eine Obergrenze. Ein Heizstab läuft in den Standard-Regeln nicht, "
    "bei Häusern mit Heizstab fällt sie dadurch etwas zu hoch aus."
)
_NO_LADDER_INFO = (
    "Dieser Lauf enthält noch keine Standard-Regeln. Für die Ersparnis gegen die "
    "Standard-Regeln bitte den Szenario-Explorer neu berechnen."
)
_NO_SOC_CAPTION = "Der Ladestand am Periodenende ist in diesem älteren Lauf nicht bewertet."


@dataclass(frozen=True)
class LadderSummary:
    """Ladder of one scenario. ``corrections`` holds the end-SoC term of L1 and L2, if valued."""

    scenario_id: str
    label: str
    costs: dict[str, float]
    corrections: dict[str, float]

    def adjusted(self, step: str) -> float:
        return self.costs[step] + self.corrections.get(step, 0.0)

    @property
    def saving_eur(self) -> float:
        return self.adjusted(LADDER_L2) - self.costs[STEP_L3]

    @property
    def rule_share(self) -> float | None:
        return rule_share(self.costs[STEP_L0], self.adjusted(LADDER_L2), self.costs[STEP_L3])


def build_ladder_summaries(meta: dict) -> list[LadderSummary]:
    """One summary per scenario with a ladder, in the order of the cost table."""
    ladder = meta.get("ladder_by_scenario") or {}
    if not ladder:
        return []
    totals = _totals_with_fuel(meta, meta.get("summary", {}).get("total_eur", {}))
    labels = meta.get("labels", {})
    ordered = [sid for sid in _annual_cost_row_order(meta, totals) if sid in ladder]
    missing = sorted(set(ladder) - set(ordered))
    if missing:
        raise ValueError(f"Backtesting-Log ohne Kosten für Szenarien: {', '.join(missing)}.")
    summaries: list[LadderSummary] = []
    for scenario_id in ordered:
        steps = ladder[scenario_id]
        block = _soc_correction_block(meta, scenario_id)
        summaries.append(
            LadderSummary(
                scenario_id=scenario_id,
                label=labels.get(scenario_id, scenario_id),
                costs={
                    STEP_L0: float(totals[meta["reference_by_scenario"][scenario_id]]),
                    LADDER_L1: float(totals[steps[LADDER_L1]]),
                    LADDER_L2: float(totals[steps[LADDER_L2]]),
                    STEP_L3: float(totals[scenario_id]),
                },
                corrections=(
                    {
                        step: float(block["steps"][step]["correction_eur"])
                        for step in (LADDER_L1, LADDER_L2)
                    }
                    if block
                    else {}
                ),
            )
        )
    return summaries


def rule_share_text(share: float | None) -> str:
    if share is None:
        return "Anteil der Regeln: — (keine Gesamtersparnis)"
    return f"Anteil der Regeln: {share * 100:.0f} %"


def ladder_table_rows(summaries: list[LadderSummary]) -> list[dict]:
    """Steps per scenario; the savings of a scenario's steps add up to L0 − L3."""
    rows: list[dict] = []
    for summary in summaries:
        previous: float | None = None
        for step in _STEPS:
            adjusted = summary.adjusted(step)
            correction = summary.corrections.get(step)
            rows.append(
                {
                    "Szenario": summary.label,
                    "Stufe": _STEP_NAMES[step],
                    "Inhalt": _STEP_CONTENT[step],
                    "Kosten [€]": format_euro(summary.costs[step]),
                    "Ladestand am Periodenende [€]": (
                        format_euro(correction, signed=True) if correction is not None else _DASH
                    ),
                    "Ersparnis zur Stufe davor [€]": (
                        saving_text(previous - adjusted) if previous is not None else _DASH
                    ),
                }
            )
            previous = adjusted
    return rows


def render_ladder_headline(meta: dict) -> None:
    """Saving L2 − L3 and rule share per scenario, the full ladder in an expander."""
    st.subheader("Ersparnis gegen Standard-Regeln")
    summaries = build_ladder_summaries(meta)
    if not summaries:
        st.info(_NO_LADDER_INFO)
        return
    for start in range(0, len(summaries), _METRICS_PER_ROW):
        chunk = summaries[start : start + _METRICS_PER_ROW]
        for column, summary in zip(st.columns(_METRICS_PER_ROW), chunk):
            column.metric(
                summary.label,
                saving_text(summary.saving_eur),
                delta=rule_share_text(summary.rule_share),
                delta_color="off",
                delta_arrow="off",
                help=_HEADLINE_HELP,
            )
    st.caption(_HEADLINE_CAPTION)
    if any(not summary.corrections for summary in summaries):
        st.caption(_NO_SOC_CAPTION)
    with st.expander("Alle Stufen: von „Ohne Steuerung“ bis Earnie"):
        st.dataframe(
            pd.DataFrame(ladder_table_rows(summaries)), width="stretch", hide_index=True
        )
        st.caption(
            "Jede Stufe ergänzt genau eine Sache. **Kosten** ist der gebuchte Betrag wie in der "
            "Tabelle unten. Die **Ersparnis zur Stufe davor** rechnet den Ladestand am "
            "Periodenende mit ein."
        )

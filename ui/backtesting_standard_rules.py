"""SE window view against the Standard-Regeln: booked L2 and L3 per slot (RuleRef P3b).

Both series come from the run's series file, so a chart's saving is the L2 − L3 of its
slots and adds up to the cost table. The window's first half (SA₀→SA₁) was booked by the
previous window, so the window's own rows would not match there. Spec:
``docs/dev/rule-based-reference.md`` § 5.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from optimizer.slot_duration import DEFAULT_DT_H
from optimizer.targets import consumer_column_name
from simulation.backtesting_horizon import naive_backtesting_slot
from simulation.reference_costs import LADDER_L2
from ui.number_format import format_general

STANDARD_RULES_LABEL = "Standard-Regeln"


@dataclass(frozen=True)
class StandardRulesSeries:
    """Booked series of one scenario (L3) and of its Standard-Regeln run (L2), by slot."""

    l2: pd.DataFrame
    l3: pd.DataFrame


def _booked_frame(hourly_df: pd.DataFrame, result_id: str) -> pd.DataFrame:
    part = hourly_df.loc[hourly_df["scenario_id"] == result_id]
    if part.empty:
        raise ValueError(
            f"Backtesting-Log ohne Reihe für {result_id!r}. Bitte Backtesting neu berechnen."
        )
    frame = part.set_index(pd.DatetimeIndex(part["ts"]))
    # A repeated hour at the clock change counts once, as in ``booked_consumption``.
    return frame.loc[~frame.index.duplicated(keep="first")]


def standard_rules_series(
    meta: dict,
    hourly_df: pd.DataFrame | None,
    scenario_id: str,
) -> StandardRulesSeries | None:
    """``None`` for a log without a ladder: its view keeps the baseline of its time."""
    steps = (meta.get("ladder_by_scenario") or {}).get(scenario_id)
    if not steps:
        return None
    if hourly_df is None:
        raise ValueError("Backtesting-Log ohne Stundenreihen, Standard-Regeln nicht verfügbar.")
    return StandardRulesSeries(
        l2=_booked_frame(hourly_df, steps[LADDER_L2]),
        l3=_booked_frame(hourly_df, scenario_id),
    )


def _column_per_slot(frame: pd.DataFrame, column: str, stamps: pd.DatetimeIndex) -> list[float]:
    """Slots outside the period were not booked, so they cost and consume nothing."""
    return frame[column].reindex(stamps).fillna(0.0).astype(float).tolist()


def _baseline_chart_rows(
    chart_rows: list[dict],
    l2: pd.DataFrame,
    stamps: pd.DatetimeIndex,
    flex_consumers: list[dict],
) -> list[dict]:
    """What Chart 1 draws of L2: SoC and flex per slot. No SoC outside the period."""
    aligned = l2.reindex(stamps)
    rows: list[dict] = []
    for position, source in enumerate(chart_rows):
        slot = aligned.iloc[position]
        row = {
            "slot_datetime": source["slot_datetime"],
            "Uhrzeit": source.get("Uhrzeit"),
            "Simulierter SoC (%)": slot["sim_soc"],
            "Geplante Batterie-Aktion (kW)": slot["batt_action_kw"],
        }
        for consumer in flex_consumers:
            row[consumer_column_name(consumer)] = slot.get(f"{consumer['id']}_kw", float("nan"))
        rows.append(row)
    return rows


def apply_standard_rules(
    savings_info: dict,
    chart_rows: list[dict],
    series: StandardRulesSeries,
    flex_consumers: list[dict],
) -> dict:
    """``savings_info`` with L2 as the baseline and the booked L3 as "optimiert"."""
    stamps = pd.DatetimeIndex([naive_backtesting_slot(row["slot_datetime"]) for row in chart_rows])
    dt_h = float(DEFAULT_DT_H)
    l2_cost = _column_per_slot(series.l2, "sim_cost", stamps)
    l3_cost = _column_per_slot(series.l3, "sim_cost", stamps)
    l2_kwh = [kw * dt_h for kw in _column_per_slot(series.l2, "consumption_kw", stamps)]
    l3_kwh = [kw * dt_h for kw in _column_per_slot(series.l3, "consumption_kw", stamps)]
    booked = stamps.isin(series.l2.index) & stamps.isin(series.l3.index)
    return {
        **savings_info,
        "matched_baseline_rows": _baseline_chart_rows(chart_rows, series.l2, stamps, flex_consumers),
        "matched_baseline_cost_euro": round(sum(l2_cost), 4),
        "optimized_cost_euro": round(sum(l3_cost), 4),
        "savings_matched_euro": round(sum(l2_cost) - sum(l3_cost), 4),
        "matched_baseline_consumption_kwh": round(sum(l2_kwh), 3),
        "optimized_consumption_kwh": round(sum(l3_kwh), 3),
        "hourly_matched_baseline_cost_euro": l2_cost,
        "hourly_optimized_cost_euro": l3_cost,
        "hourly_savings_euro": [a - b for a, b in zip(l2_cost, l3_cost)],
        "hourly_matched_baseline_consumption_kwh": l2_kwh,
        "hourly_optimized_consumption_kwh": l3_kwh,
        "standard_rules_slots_outside_period": int((~booked).sum()),
    }


def standard_rules_caption(savings_info: dict) -> str | None:
    """Text under the charts of a window compared with the Standard-Regeln."""
    if "standard_rules_slots_outside_period" not in savings_info:
        return None
    text = (
        "Vergleich mit den Standard-Regeln: Chart 2 zeigt je Slot die gebuchten Kosten beider "
        "Läufe, die Summe passt zur Kostentabelle. Chart 1 zeigt den Plan dieses Fensters; "
        "SA₀→SA₁ wurde vom Vorfenster gebucht und kann davon abweichen."
    )
    outside = int(savings_info["standard_rules_slots_outside_period"])
    if outside:
        text += (
            f" {format_general(outside * float(DEFAULT_DT_H))} h des Fensters liegen außerhalb des Zeitraums "
            "und zählen nicht mit."
        )
    return text

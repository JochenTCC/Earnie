"""Study export of the reference ladder: L0–L3 per day and scenario, rule sensitivity.

Spec: ``docs/dev/rule-based-reference.md`` §§ 4.7, 5. Reads a finished SE run (series file and
log). All amounts are booked electricity: no fixed fees, no fuel, and L3 plans with perfect
foresight (spec O1), so L2 − L3 is an upper bound.
"""
from __future__ import annotations

from typing import Iterable, NamedTuple

import pandas as pd

from optimizer.sim_baseline import (
    DEFAULT_RULE_PARAMS,
    SURPLUS_BATTERY_FIRST,
    SURPLUS_CONSUMER_FIRST,
)
from optimizer.thermal_flex_context import is_heating_rod_consumer
from simulation.reference_costs import LADDER_L1, LADDER_L2
from simulation.reference_ladder import rule_share, soc_correction_eur, soc_kwh_per_percent

DAILY_CSV = "reference_ladder_daily.csv"
SUMMARY_CSV = "reference_ladder_summary.csv"
SENSITIVITY_CSV = "reference_ladder_sensitivity.csv"
L3_FORESIGHT = "perfect"
SENSITIVITY_QUANTILES = (0.50, 0.66, 0.75, 0.90)
SENSITIVITY_PRIORITIES = (SURPLUS_CONSUMER_FIRST, SURPLUS_BATTERY_FIRST)


class SensitivityRun(NamedTuple):
    """One L2 run with other rule parameters, over the period."""

    cost_eur: float
    soc_end_percent: float
    plausibility_failed_windows: int


def rule_key(rule_params: dict) -> tuple[float, str]:
    return float(rule_params["lock_quantile"]), str(rule_params["surplus_priority"])


def sensitivity_grid() -> list[dict]:
    """All parameter sets of spec § 4.7, the default first: it wins a tie for "best"."""
    grid = [
        {"lock_quantile": quantile, "surplus_priority": priority}
        for quantile in SENSITIVITY_QUANTILES
        for priority in SENSITIVITY_PRIORITIES
    ]
    if DEFAULT_RULE_PARAMS not in grid:
        raise ValueError(f"Standard-Regeln {DEFAULT_RULE_PARAMS} fehlen im Sensitivitätsraster.")
    grid.remove(DEFAULT_RULE_PARAMS)
    return [dict(DEFAULT_RULE_PARAMS), *grid]


def has_heating_rod(scenario_params: dict) -> bool:
    """L1 and L2 run the rod at 0 kWh, so L2 − L3 is overstated for this house (spec § 3.1)."""
    from simulation.engine_scenario import _flexible_consumers_from_scenario

    return any(is_heating_rod_consumer(c) for c in _flexible_consumers_from_scenario(scenario_params))


def _series(hourly: pd.DataFrame, result_id: str) -> pd.DataFrame:
    part = hourly.loc[hourly["scenario_id"] == result_id]
    if part.empty:
        raise ValueError(f"Backtesting-Log ohne Reihe für {result_id!r}.")
    return part


def _cost_per_day(hourly: pd.DataFrame, result_id: str) -> pd.Series:
    part = _series(hourly, result_id)
    return part.groupby(pd.DatetimeIndex(part["ts"]).normalize())["sim_cost"].sum()


def _step_ids(meta: dict, scenario_id: str) -> dict[str, str]:
    steps = meta["ladder_by_scenario"][scenario_id]
    return {
        "l0": meta["reference_by_scenario"][scenario_id],
        "l1": steps[LADDER_L1],
        "l2": steps[LADDER_L2],
        "l3": scenario_id,
    }


def daily_ladder_frame(meta: dict, hourly: pd.DataFrame, scenarios: dict[str, dict]) -> pd.DataFrame:
    """One row per day and scenario; a day missing on one step fails loud."""
    frames: list[pd.DataFrame] = []
    labels = meta.get("labels", {})
    for scenario_id in meta["ladder_by_scenario"]:
        ids = _step_ids(meta, scenario_id)
        day = pd.DataFrame(
            {f"{step}_eur": _cost_per_day(hourly, result_id) for step, result_id in ids.items()}
        )
        missing = day[day.isna().any(axis=1)]
        if not missing.empty:
            raise ValueError(
                f"Szenario {scenario_id!r}: Stufen ohne Buchung am "
                f"{missing.index[0]:%Y-%m-%d} ({', '.join(missing.columns[missing.iloc[0].isna()])})."
            )
        day.insert(0, "scenario_label", labels.get(scenario_id, scenario_id))
        day.insert(0, "scenario_id", scenario_id)
        day["heating_rod"] = has_heating_rod(scenarios[scenario_id])
        day["l3_foresight"] = L3_FORESIGHT
        day.index = day.index.strftime("%Y-%m-%d")
        day.index.name = "date"
        frames.append(day.reset_index())
    return pd.concat(frames, ignore_index=True)


def _total(hourly: pd.DataFrame, result_id: str) -> float:
    return float(_series(hourly, result_id)["sim_cost"].sum())


def _plausibility_failed(meta: dict, result_id: str) -> int:
    return int((meta.get("ladder_report") or {}).get(result_id, {})["plausibility_failed_windows"])


def summary_frame(meta: dict, hourly: pd.DataFrame, scenarios: dict[str, dict]) -> pd.DataFrame:
    """One row per scenario. ``l2_adjusted`` carries the end-SoC term (spec § 3.3)."""
    rows: list[dict] = []
    for scenario_id in meta["ladder_by_scenario"]:
        ids = _step_ids(meta, scenario_id)
        totals = {step: _total(hourly, result_id) for step, result_id in ids.items()}
        block = meta["ladder_soc_correction"][scenario_id]
        l1_correction = float(block["steps"][LADDER_L1]["correction_eur"])
        l2_correction = float(block["steps"][LADDER_L2]["correction_eur"])
        l2_adjusted = totals["l2"] + l2_correction
        rows.append(
            {
                "scenario_id": scenario_id,
                "scenario_label": meta.get("labels", {}).get(scenario_id, scenario_id),
                "period_start": meta["period"]["start"],
                "period_end": meta["period"]["end"],
                "l0_eur": totals["l0"],
                "l1_eur": totals["l1"],
                "l2_eur": totals["l2"],
                "l3_eur": totals["l3"],
                "l1_soc_correction_eur": l1_correction,
                "l2_soc_correction_eur": l2_correction,
                "saving_l2_l3_eur": l2_adjusted - totals["l3"],
                "rule_share": rule_share(totals["l0"], l2_adjusted, totals["l3"]),
                "soc_end_percent_l1": block["steps"][LADDER_L1]["soc_end_percent"],
                "soc_end_percent_l2": block["steps"][LADDER_L2]["soc_end_percent"],
                "soc_end_percent_l3": block["soc_end_percent"],
                "p_ref_cent": block["p_ref_cent"],
                "p_ref_basis": block["p_ref_basis"],
                "plausibility_failed_windows_l1": _plausibility_failed(meta, ids["l1"]),
                "plausibility_failed_windows_l2": _plausibility_failed(meta, ids["l2"]),
                "heating_rod": has_heating_rod(scenarios[scenario_id]),
                "l3_foresight": L3_FORESIGHT,
            }
        )
    return pd.DataFrame(rows)


def sensitivity_frame(
    meta: dict,
    hourly: pd.DataFrame,
    scenarios: dict[str, dict],
    runs: dict[tuple[str, tuple[float, str]], SensitivityRun],
    grid: Iterable[dict],
) -> pd.DataFrame:
    """One row per scenario and parameter set; the default comes from the SE run itself.

    "Best in hindsight" is the set with the lowest L2 cost including the end-SoC term, so
    the smallest saving: the most generous reading for the rules.
    """
    rows: list[dict] = []
    default_key = rule_key(DEFAULT_RULE_PARAMS)
    grid_list = list(grid)
    for scenario_id, steps in meta["ladder_by_scenario"].items():
        ids = _step_ids(meta, scenario_id)
        l0, l3 = _total(hourly, ids["l0"]), _total(hourly, ids["l3"])
        block = meta["ladder_soc_correction"][scenario_id]
        kwh_per_percent = soc_kwh_per_percent(scenarios[scenario_id])
        scenario_rows: list[dict] = []
        for rule_params in grid_list:
            key = rule_key(rule_params)
            if key == default_key:
                run = SensitivityRun(
                    _total(hourly, steps[LADDER_L2]),
                    float(block["steps"][LADDER_L2]["soc_end_percent"]),
                    _plausibility_failed(meta, steps[LADDER_L2]),
                )
            else:
                run = runs[(steps[LADDER_L2], key)]
            correction = soc_correction_eur(
                float(block["soc_end_percent"]),
                run.soc_end_percent,
                kwh_per_percent,
                float(block["p_ref_cent"]),
            )
            adjusted = run.cost_eur + correction
            scenario_rows.append(
                {
                    "scenario_id": scenario_id,
                    "lock_quantile": key[0],
                    "surplus_priority": key[1],
                    "l2_eur": run.cost_eur,
                    "l2_soc_correction_eur": correction,
                    "l2_adjusted_eur": adjusted,
                    "saving_l2_l3_eur": adjusted - l3,
                    "rule_share": rule_share(l0, adjusted, l3),
                    "plausibility_failed_windows": run.plausibility_failed_windows,
                    "is_default": key == default_key,
                    "is_best_in_hindsight": False,
                    "l3_foresight": L3_FORESIGHT,
                }
            )
        min(scenario_rows, key=lambda row: row["l2_adjusted_eur"])["is_best_in_hindsight"] = True
        rows.extend(scenario_rows)
    return pd.DataFrame(rows)


def write_csv(frame: pd.DataFrame, path: str) -> None:
    """Same format as the SE series file."""
    frame.to_csv(path, index=False, sep=";", decimal=",", lineterminator="\n")

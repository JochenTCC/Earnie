"""Study export of the reference ladder: L0–L3 per day and scenario, rule sensitivity.

Spec: ``docs/dev/rule-based-reference.md`` §§ 4.7, 5. Reads a finished SE run (series file and
log). ``l*_eur`` is booked electricity without fixed fees, ``l*_fuel_eur`` the fuel from the log's
``heat_fuel`` block, ``l*_total_eur`` both; only ``*_with_fuel_*`` compares a saving including
fuel. L3 plans with perfect foresight (spec O1), so L2 − L3 is an upper bound. A second run in
forecast mode gives the other end of the range (``docs/dev/se-forecast-mode.md`` § 4): the
``*_forecast`` columns.
"""
from __future__ import annotations

from typing import Iterable, NamedTuple

import pandas as pd

from optimizer.sim_baseline import (
    DEFAULT_RULE_PARAMS,
    SURPLUS_BATTERY_FIRST,
    SURPLUS_CONSUMER_FIRST,
)
from optimizer.slot_duration import DEFAULT_DT_H
from optimizer.thermal_flex_context import is_heating_rod_consumer
from simulation.heat_fuel import HEAT_FUEL_DAILY_KEY, HEAT_FUEL_KEY
from simulation.reference_costs import LADDER_L1, LADDER_L2
from simulation.reference_ladder import rule_share, soc_correction_eur, soc_kwh_per_percent

DAILY_CSV = "reference_ladder_daily.csv"
SUMMARY_CSV = "reference_ladder_summary.csv"
SENSITIVITY_CSV = "reference_ladder_sensitivity.csv"
L3_FORESIGHT = "perfect"
SENSITIVITY_QUANTILES = (0.50, 0.66, 0.75, 0.90)
SENSITIVITY_PRIORITIES = (SURPLUS_CONSUMER_FIRST, SURPLUS_BATTERY_FIRST)
LADDER_STEPS = ("l0", "l1", "l2", "l3")


# Booked cents differ by the CSV's rounding only: L0–L2 do not depend on L3's plan.
REFERENCE_MATCH_TOLERANCE_EUR = 0.05


class ForecastRun(NamedTuple):
    """The log of the same period's SE run in forecast mode."""

    meta: dict
    hourly: pd.DataFrame


class SensitivityRun(NamedTuple):
    """One L2 run with other rule parameters, over the period."""

    cost_eur: float
    soc_end_percent: float
    plausibility_failed_windows: int
    fuel_eur: float


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
    """The rod has no energy target; only beside a fuel source does L2 run it (spec § 3.1)."""
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


def _fuel_block(meta: dict, result_id: str) -> dict:
    block = (meta.get(HEAT_FUEL_KEY) or {}).get(result_id)
    if block is None:
        raise ValueError(f"Backtesting-Log ohne Brennstoff-Block für {result_id!r}.")
    return block


def _fuel_per_day(meta: dict, result_id: str) -> pd.DataFrame:
    """Columns ``fuel_kwh``, ``fuel_eur``, ``rod_kwh`` per day; the period's totals are in the block."""
    days = _fuel_block(meta, result_id).get(HEAT_FUEL_DAILY_KEY)
    if days is None:
        raise ValueError(f"Backtesting-Log ohne Brennstoff je Tag für {result_id!r}: Lauf neu rechnen.")
    frame = pd.DataFrame.from_dict(days, orient="index")
    frame.index = pd.DatetimeIndex(frame.index)
    return frame


def _energy_columns(part: pd.DataFrame, group) -> pd.DataFrame:
    """Import, export and battery throughput (charged + discharged, AC side). L0 has no battery."""
    return pd.DataFrame(
        {
            "import_kwh": part["import_kwh"].groupby(group).sum(),
            "export_kwh": part["export_kwh"].groupby(group).sum(),
            "battery_throughput_kwh": part["batt_action_kw"].abs().groupby(group).sum() * DEFAULT_DT_H,
        }
    )


def _energy_per_day(hourly: pd.DataFrame, result_id: str) -> pd.DataFrame:
    part = _series(hourly, result_id)
    return _energy_columns(part, pd.DatetimeIndex(part["ts"]).normalize())


def _energy_total(hourly: pd.DataFrame, result_id: str) -> dict[str, float]:
    part = _series(hourly, result_id)
    return _energy_columns(part, [0] * len(part)).iloc[0].to_dict()


def _step_ids(meta: dict, scenario_id: str) -> dict[str, str]:
    steps = meta["ladder_by_scenario"][scenario_id]
    return {
        "l0": meta["reference_by_scenario"][scenario_id],
        "l1": steps[LADDER_L1],
        "l2": steps[LADDER_L2],
        "l3": scenario_id,
    }


def assert_references_match(meta: dict, hourly: pd.DataFrame, forecast: ForecastRun) -> None:
    """L0–L2 must be the same in both runs, or their L3 values are not one range."""
    for scenario_id in meta["ladder_by_scenario"]:
        ids = _step_ids(meta, scenario_id)
        forecast_ids = _step_ids(forecast.meta, scenario_id)
        for step in ("l0", "l1", "l2"):
            perfect_eur = _total(hourly, ids[step])
            forecast_eur = _total(forecast.hourly, forecast_ids[step])
            perfect_fuel = float(_fuel_block(meta, ids[step])["fuel_eur"])
            forecast_fuel = float(_fuel_block(forecast.meta, forecast_ids[step])["fuel_eur"])
            if (
                abs(perfect_eur - forecast_eur) > REFERENCE_MATCH_TOLERANCE_EUR
                or abs(perfect_fuel - forecast_fuel) > REFERENCE_MATCH_TOLERANCE_EUR
            ):
                raise ValueError(
                    f"Szenario {scenario_id!r}: {step.upper()} unterscheidet sich zwischen den Läufen "
                    f"(Strom {perfect_eur:.2f} € und {forecast_eur:.2f} €, Brennstoff {perfect_fuel:.2f} € "
                    f"und {forecast_fuel:.2f} € im Forecast-Modus)."
                )


def daily_ladder_frame(
    meta: dict,
    hourly: pd.DataFrame,
    scenarios: dict[str, dict],
    forecast: ForecastRun | None = None,
) -> pd.DataFrame:
    """One row per day and scenario; a day missing on one step fails loud."""
    frames: list[pd.DataFrame] = []
    labels = meta.get("labels", {})
    for scenario_id in meta["ladder_by_scenario"]:
        ids = _step_ids(meta, scenario_id)
        columns = {f"{step}_eur": _cost_per_day(hourly, result_id) for step, result_id in ids.items()}
        for step, result_id in ids.items():
            fuel = _fuel_per_day(meta, result_id)
            energy = _energy_per_day(hourly, result_id)
            columns[f"{step}_fuel_eur"] = fuel["fuel_eur"]
            columns[f"{step}_fuel_kwh"] = fuel["fuel_kwh"]
            columns[f"{step}_rod_kwh"] = fuel["rod_kwh"]
            for name in energy.columns:
                columns[f"{step}_{name}"] = energy[name]
        if forecast is not None:
            columns["l3_forecast_eur"] = _cost_per_day(forecast.hourly, scenario_id)
            columns["l3_fuel_forecast_eur"] = _fuel_per_day(forecast.meta, scenario_id)["fuel_eur"]
        day = pd.DataFrame(columns)
        missing = day[day.isna().any(axis=1)]
        if not missing.empty:
            raise ValueError(
                f"Szenario {scenario_id!r}: Stufen ohne Buchung am "
                f"{missing.index[0]:%Y-%m-%d} ({', '.join(missing.columns[missing.iloc[0].isna()])})."
            )
        for step in LADDER_STEPS:
            day[f"{step}_total_eur"] = day[f"{step}_eur"] + day[f"{step}_fuel_eur"]
        # Booked per day: the end-SoC term exists only for the period (summary).
        day["l2_l3_with_fuel_eur"] = day["l2_total_eur"] - day["l3_total_eur"]
        if forecast is not None:
            day["l3_total_forecast_eur"] = day["l3_forecast_eur"] + day["l3_fuel_forecast_eur"]
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


def _forecast_columns(scenario_id: str, l0_eur: float, l0_fuel_eur: float, forecast: ForecastRun) -> dict:
    """The range's other end; the end-SoC term is the forecast run's own (spec § 4)."""
    meta, hourly = forecast
    l2_id = _step_ids(meta, scenario_id)["l2"]
    l2_eur = _total(hourly, l2_id)
    l3_eur = _total(hourly, scenario_id)
    l2_fuel = float(_fuel_block(meta, l2_id)["fuel_eur"])
    l3_fuel = float(_fuel_block(meta, scenario_id)["fuel_eur"])
    block = meta["ladder_soc_correction"][scenario_id]
    correction = float(block["steps"][LADDER_L2]["correction_eur"])
    adjusted = l2_eur + correction
    plausibility = meta["plausibility"][scenario_id]
    period = meta["period"]
    return {
        "l3_forecast_eur": l3_eur,
        "l2_soc_correction_forecast_eur": correction,
        "saving_l2_l3_forecast_eur": adjusted - l3_eur,
        "rule_share_forecast": rule_share(l0_eur, adjusted, l3_eur),
        "l3_fuel_forecast_eur": l3_fuel,
        "l3_total_forecast_eur": l3_eur + l3_fuel,
        "saving_l2_l3_with_fuel_forecast_eur": adjusted + l2_fuel - l3_eur - l3_fuel,
        "rule_share_with_fuel_forecast": rule_share(
            l0_eur + l0_fuel_eur, adjusted + l2_fuel, l3_eur + l3_fuel
        ),
        "soc_end_percent_l3_forecast": block["soc_end_percent"],
        "plausibility_failed_windows_l3_forecast": int(plausibility["failed_count"]),
        "plan_forecast": ",".join(period["plan_forecast"]),
        "price_strategy": period["price_strategy"],
    }


def summary_frame(
    meta: dict,
    hourly: pd.DataFrame,
    scenarios: dict[str, dict],
    forecast: ForecastRun | None = None,
) -> pd.DataFrame:
    """One row per scenario. ``l2_adjusted`` carries the end-SoC term (spec § 3.3)."""
    rows: list[dict] = []
    for scenario_id in meta["ladder_by_scenario"]:
        ids = _step_ids(meta, scenario_id)
        totals = {step: _total(hourly, result_id) for step, result_id in ids.items()}
        block = meta["ladder_soc_correction"][scenario_id]
        l1_correction = float(block["steps"][LADDER_L1]["correction_eur"])
        l2_correction = float(block["steps"][LADDER_L2]["correction_eur"])
        l2_adjusted = totals["l2"] + l2_correction
        blocks = {step: _fuel_block(meta, result_id) for step, result_id in ids.items()}
        fuel = {step: float(block["fuel_eur"]) for step, block in blocks.items()}
        all_in = {step: totals[step] + fuel[step] for step in ids}
        l2_adjusted_all_in = all_in["l2"] + l2_correction
        step_columns: dict[str, float] = {}
        for step, result_id in ids.items():
            step_columns[f"{step}_fuel_eur"] = fuel[step]
            step_columns[f"{step}_total_eur"] = all_in[step]
            step_columns[f"{step}_fuel_kwh"] = float(blocks[step]["fuel_kwh"])
            step_columns[f"{step}_rod_kwh"] = float(blocks[step]["rod_kwh"])
            for name, value in _energy_total(hourly, result_id).items():
                step_columns[f"{step}_{name}"] = value
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
                "saving_l2_l3_with_fuel_eur": l2_adjusted_all_in - all_in["l3"],
                "rule_share_with_fuel": rule_share(all_in["l0"], l2_adjusted_all_in, all_in["l3"]),
                "fuel_carriers": ",".join(blocks["l3"]["carriers"]),
                **step_columns,
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
        if forecast is not None:
            rows[-1].update(_forecast_columns(scenario_id, totals["l0"], fuel["l0"], forecast))
    return pd.DataFrame(rows)


def sensitivity_frame(
    meta: dict,
    hourly: pd.DataFrame,
    scenarios: dict[str, dict],
    runs: dict[tuple[str, tuple[float, str]], SensitivityRun],
    grid: Iterable[dict],
) -> pd.DataFrame:
    """One row per scenario and parameter set; the default comes from the SE run itself.

    "Best in hindsight" is the set with the lowest L2 cost including fuel and the end-SoC
    term, so the smallest saving: the most generous reading for the rules.
    """
    rows: list[dict] = []
    default_key = rule_key(DEFAULT_RULE_PARAMS)
    grid_list = list(grid)
    for scenario_id, steps in meta["ladder_by_scenario"].items():
        ids = _step_ids(meta, scenario_id)
        l0, l3 = _total(hourly, ids["l0"]), _total(hourly, ids["l3"])
        l0_all_in = l0 + float(_fuel_block(meta, ids["l0"])["fuel_eur"])
        l3_all_in = l3 + float(_fuel_block(meta, ids["l3"])["fuel_eur"])
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
                    float(_fuel_block(meta, steps[LADDER_L2])["fuel_eur"]),
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
            adjusted_all_in = adjusted + run.fuel_eur
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
                    "l2_fuel_eur": run.fuel_eur,
                    "saving_l2_l3_with_fuel_eur": adjusted_all_in - l3_all_in,
                    "rule_share_with_fuel": rule_share(l0_all_in, adjusted_all_in, l3_all_in),
                    "plausibility_failed_windows": run.plausibility_failed_windows,
                    "is_default": key == default_key,
                    "is_best_in_hindsight": False,
                    "l3_foresight": L3_FORESIGHT,
                }
            )
        min(scenario_rows, key=lambda row: row["l2_adjusted_eur"] + row["l2_fuel_eur"])["is_best_in_hindsight"] = True
        rows.extend(scenario_rows)
    return pd.DataFrame(rows)


def write_csv(frame: pd.DataFrame, path: str) -> None:
    """Same format as the SE series file."""
    frame.to_csv(path, index=False, sep=";", decimal=",", lineterminator="\n")

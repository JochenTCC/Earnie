"""SE reference ladder: end-of-period SoC correction and the L1 / L2 sharing key.

Split from ``simulation.reference_ladder``, which re-exports every name here.
"""
from __future__ import annotations

import json

import pandas as pd

from optimizer.sim_baseline import _baseline_battery_params
from simulation.reference_costs import RUN_END_SOC_ATTR

P_REF_IMPORT_WEIGHTED = "import_weighted"
P_REF_TIME_MEAN = "time_mean"


def soc_kwh_per_percent(scenario_params: dict) -> float:
    """Usable energy of one SoC percent, as the ledger's correction counts it."""
    from simulation.engine_scenario import _scenario_to_battery_params

    battery = _baseline_battery_params(_scenario_to_battery_params(scenario_params))
    return float(battery["battery_capacity_kwh"]) * float(battery["efficiency"]) / 100.0


def soc_correction_eur(
    l3_soc: float, step_soc: float, kwh_per_percent: float, p_ref_cent: float
) -> float:
    """Positive when L3 ends fuller than the step: the step's cost is that much too low."""
    return (l3_soc - step_soc) * kwh_per_percent * p_ref_cent / 100.0


def rule_share(l0_eur: float, l2_eur: float, l3_eur: float) -> float | None:
    """Share of the rules in the total saving; ``None`` when Earnie saves nothing against L0."""
    total_saving = l0_eur - l3_eur
    return (l0_eur - l2_eur) / total_saving if total_saving > 0 else None


def period_end_exclusive(period_end: pd.Timestamp | str) -> pd.Timestamp:
    return pd.Timestamp(period_end).normalize() + pd.Timedelta(days=1)


def soc_at_period_end(frame: pd.DataFrame, end_exclusive: pd.Timestamp) -> float:
    """SoC where the booked period ends: the next slot's start SoC, else the run's end SoC."""
    index = pd.DatetimeIndex(frame.index)
    later = frame.loc[index >= end_exclusive]
    if not later.empty:
        return float(later.iloc[0]["sim_soc"])
    if RUN_END_SOC_ATTR not in frame.attrs:
        raise ValueError(f"Lauf ohne End-SoC, Periodenende {end_exclusive:%Y-%m-%d} nicht bewertbar.")
    return float(frame.attrs[RUN_END_SOC_ATTR])


def _reference_buy_price_cent(l3_frame: pd.DataFrame, end_exclusive: pd.Timestamp) -> tuple[float, str]:
    """``p_ref``: L3's import-weighted buy price of the period's last day, as the ledger does.

    A day without import takes the time mean, as an explicit rule (``savings-ledger.md`` § 3).
    """
    index = pd.DatetimeIndex(l3_frame.index)
    day = l3_frame.loc[(index >= end_exclusive - pd.Timedelta(days=1)) & (index < end_exclusive)]
    if day.empty:
        raise ValueError(f"Keine gebuchten Slots am letzten Tag vor {end_exclusive:%Y-%m-%d}.")
    import_kwh = float(day["import_kwh"].sum())
    if import_kwh > 0.0:
        return float((day["import_kwh"] * day["k_act"]).sum()) / import_kwh, P_REF_IMPORT_WEIGHTED
    return float(day["k_act"].mean()), P_REF_TIME_MEAN


def ladder_soc_correction(
    results: dict[str, pd.DataFrame],
    scenario_id: str,
    steps: dict[str, str],
    scenario_params: dict,
    period_end: pd.Timestamp | str,
) -> dict:
    """Value each step's end-of-period SoC difference to L3 (spec § 3.3, ledger formula).

    ``correction_eur`` is positive when L3 ends fuller than the step: the step's cost is
    that much too low for the comparison. ``results`` are not clipped to the period, since
    the SoC at the period's end is the start SoC of the slot behind it.
    """
    end_exclusive = period_end_exclusive(period_end)
    kwh_per_percent = soc_kwh_per_percent(scenario_params)
    l3_frame = results[scenario_id]
    l3_soc = soc_at_period_end(l3_frame, end_exclusive)
    p_ref_cent, basis = _reference_buy_price_cent(l3_frame, end_exclusive)
    block: dict = {
        "soc_end_percent": l3_soc,
        "p_ref_cent": p_ref_cent,
        "p_ref_basis": basis,
        "steps": {},
    }
    for step, ref_id in steps.items():
        step_soc = soc_at_period_end(results[ref_id], end_exclusive)
        block["steps"][step] = {
            "soc_end_percent": step_soc,
            "correction_eur": soc_correction_eur(l3_soc, step_soc, kwh_per_percent, p_ref_cent),
        }
    return block


def ladder_reference_fingerprint(scenario_params: dict) -> tuple:
    """Sharing key of L1 / L2 runs: L0's key plus the house, the battery and the flex consumers.

    L0 ignores storage and flex, so ``reference_fingerprint`` stays as it is; L1 and L2
    depend on them and may only be shared between identical setups.
    """
    from house_config.planning_flex_bridge import reference_fingerprint
    from simulation.engine_scenario import (
        _flexible_consumers_from_scenario,
        _scenario_to_battery_params,
    )

    def canonical(value) -> str:
        return json.dumps(value, sort_keys=True, default=str)

    return (
        reference_fingerprint(scenario_params),
        canonical(scenario_params.get("_house_profile")),
        canonical(_scenario_to_battery_params(scenario_params)),
        canonical(_flexible_consumers_from_scenario(scenario_params)),
    )

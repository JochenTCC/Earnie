"""Dataclasses of the horizon MILP model (split from milp_horizon)."""
from __future__ import annotations

from dataclasses import dataclass
import pulp


@dataclass
class MilpHorizonModel:
    prob: pulp.LpProblem
    horizon: int
    p_grid_buy: list
    p_grid_sell: list
    p_charge: list
    p_discharge: list
    e_batt: list
    consumer_on: dict[str, list]
    consumer_p: dict[str, list]
    consumer_p_fixed: dict[str, list]
    consumer_pv_follow: dict[str, list]
    planned_consumers: list
    consumer_milp_charge_kw: dict[str, float]
    dt_h: float
    ess_ids: list[str] | None = None
    p_charge_by_ess: dict[str, list] | None = None
    p_discharge_by_ess: dict[str, list] | None = None
    e_batt_by_ess: dict[str, list] | None = None
    battery_params_by_id: dict[str, dict] | None = None
    p_pv_curtail: list | None = None


@dataclass
class _GridBatteryVars:
    """Netz- und Batterievariablen eines Solve-Fensters inkl. Big-M-Schranke."""

    p_grid_buy: list
    p_grid_sell: list
    p_charge: list
    p_discharge: list
    p_pv_curtail: list
    e_batt: list
    delta_charge: list
    delta_import: list
    big_m_grid: float
    ess_ids: list[str]
    p_charge_by_ess: dict[str, list]
    p_discharge_by_ess: dict[str, list]
    e_batt_by_ess: dict[str, list]
    delta_charge_by_ess: dict[str, list]
    battery_params_by_id: dict[str, dict]


@dataclass
class _ConsumerVarBlock:
    """Verbrauchervariablen-Maps, wie sie MilpHorizonModel erwartet."""

    consumer_on: dict[str, list]
    consumer_p: dict[str, list]
    consumer_p_fixed: dict[str, list]
    consumer_pv_follow: dict[str, list]
    consumer_milp_charge_kw: dict[str, float]

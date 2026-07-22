"""MILP-Ergebnis: Plan-Extraktion und Entscheidungs-Logging."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from . import battery as bat
from .consumer_power import uses_pv_follow
from .milp_consumers import (
    _consumer_powers_at,
    _consumer_pv_follow_at_all,
    _planned_consumer_kwh,
)

if TYPE_CHECKING:
    from .milp_horizon import MilpHorizonModel

logger = logging.getLogger(__name__)


def _var_value_at(variables: list, hour_index: int) -> float:
    value = variables[hour_index].varValue
    return value if value is not None else 0.0


def _var_value_at_zero(variables: list) -> float:
    return _var_value_at(variables, 0)


def _extract_milp_plan_at(model: MilpHorizonModel, hour_index: int) -> dict[str, float]:
    return {
        "p_grid_buy": _var_value_at(model.p_grid_buy, hour_index),
        "p_grid_sell": _var_value_at(model.p_grid_sell, hour_index),
        "p_charge": _var_value_at(model.p_charge, hour_index),
        "p_discharge": _var_value_at(model.p_discharge, hour_index),
    }


def _extract_milp_plan(model: MilpHorizonModel) -> dict[str, float]:
    return _extract_milp_plan_at(model, 0)


def extract_horizon_schedule(
    model: MilpHorizonModel,
    battery_params: dict,
    preset_powers_t0: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """
    Extrahiert den vollen MILP-Stundenplan (Batterie + Flex) nach einem Solve.

    Slot 0 enthält optional EV-Preset-Leistungen (außerhalb der MILP-Variablen).
    """
    min_soc = float(battery_params["min_soc"])
    max_soc = float(battery_params["max_soc"])
    capacity = float(battery_params["battery_capacity_kwh"])
    presets = preset_powers_t0 or {}
    slots: list[dict[str, Any]] = []
    for t in range(model.horizon):
        milp_plan = _extract_milp_plan_at(model, t)
        consumer_powers, _ = _consumer_powers_at(model, t)
        if t == 0 and presets:
            consumer_powers = {**consumer_powers, **presets}
        e_val = model.e_batt[t].varValue
        planned_soc = bat.planned_soc_percent_from_energy(
            float(e_val) if e_val is not None else 0.0,
            capacity,
            min_soc,
            max_soc,
        )
        slots.append(
            {
                "milp_plan": milp_plan,
                "consumer_powers": consumer_powers,
                "consumer_pv_follow": _consumer_pv_follow_at_all(model, t),
                "planned_soc_percent": planned_soc,
            }
        )
    return slots


def _log_milp_decision(
    current_hour: int,
    matrix: list[dict[str, Any]],
    current_soc: float,
    milp_plan: dict[str, float],
    model: MilpHorizonModel,
    remaining: dict[str, float],
    consumer_powers: dict[str, float],
    consumer_pv_follow: dict[str, int],
    mode: int,
    target_power: float,
    target_soc: float,
) -> None:
    opt_charge = milp_plan["p_charge"]
    opt_discharge = milp_plan["p_discharge"]
    opt_grid_buy = milp_plan["p_grid_buy"]
    logger.info(
        "MILP-Entscheidung %s:00 | Preis=%.2f ct | SoC=%.1f%% | "
        "Ladung=%.2f kW | Entladung=%.2f kW | Netzbezug=%.2f kW",
        current_hour,
        matrix[0]["k_act"],
        current_soc,
        opt_charge,
        opt_discharge,
        opt_grid_buy,
    )
    for consumer in model.planned_consumers:
        cid = consumer["id"]
        power_now = consumer_powers.get(cid, 0.0)
        planned_kwh = _planned_consumer_kwh(model, consumer)
        pv_flag = consumer_pv_follow.get(cid, 0)
        mode_txt = f" pv_follow={pv_flag}" if uses_pv_follow(consumer) else ""
        logger.info(
            "MILP %s: jetzt=%s (%.2f kW)%s | Restziel=%.2f kWh | "
            "geplant=%.2f kWh | min_on=%s x 15min",
            consumer["name"],
            "AN" if power_now > 0 else "AUS",
            power_now,
            mode_txt,
            remaining.get(cid, 0.0),
            planned_kwh,
            consumer["min_on_quarterhours"],
        )
    modi_text = {
        bat.MODE_AUTOMATIK: "AUTOMATIK",
        bat.MODE_ZWANGS_LADEN: "ZWANGSLADEN",
        bat.MODE_ENTLADESPERRE: "ENTLADESPERRE",
        bat.MODE_ZWANGS_ENTLADEN: "ZWANGSENTLADEN",
    }
    logger.info(
        "MILP Steuerbefehl: %s (Leistung=%.2f kW, Ziel-SoC=%.1f%%)",
        modi_text[mode],
        target_power,
        target_soc,
    )

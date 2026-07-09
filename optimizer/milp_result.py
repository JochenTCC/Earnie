"""MILP-Ergebnis: Plan-Extraktion und Entscheidungs-Logging."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from . import battery as bat
from .consumer_power import uses_pv_follow
from .milp_consumers import _planned_consumer_kwh

if TYPE_CHECKING:
    from .milp_horizon import MilpHorizonModel

logger = logging.getLogger(__name__)


def _var_value_at_zero(variables: list) -> float:
    value = variables[0].varValue
    return value if value is not None else 0.0


def _extract_milp_plan(model: MilpHorizonModel) -> dict[str, float]:
    return {
        "p_grid_buy": _var_value_at_zero(model.p_grid_buy),
        "p_grid_sell": _var_value_at_zero(model.p_grid_sell),
        "p_charge": _var_value_at_zero(model.p_charge),
        "p_discharge": _var_value_at_zero(model.p_discharge),
    }


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

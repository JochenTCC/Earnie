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


def _extract_milp_plan_at(model: MilpHorizonModel, hour_index: int) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "p_grid_buy": _var_value_at(model.p_grid_buy, hour_index),
        "p_grid_sell": _var_value_at(model.p_grid_sell, hour_index),
        "p_charge": _var_value_at(model.p_charge, hour_index),
        "p_discharge": _var_value_at(model.p_discharge, hour_index),
    }
    ess_ids = getattr(model, "ess_ids", None) or []
    charge_by = getattr(model, "p_charge_by_ess", None) or {}
    discharge_by = getattr(model, "p_discharge_by_ess", None) or {}
    if ess_ids and charge_by and discharge_by:
        ess_map: dict[str, dict[str, float]] = {}
        for ess_id in ess_ids:
            c_vars = charge_by.get(ess_id)
            d_vars = discharge_by.get(ess_id)
            if not c_vars or not d_vars:
                continue
            ess_map[ess_id] = {
                "p_charge": _var_value_at(c_vars, hour_index),
                "p_discharge": _var_value_at(d_vars, hour_index),
            }
        if ess_map:
            plan["ess"] = ess_map
    return plan


def _extract_milp_plan(model: MilpHorizonModel) -> dict[str, float]:
    return _extract_milp_plan_at(model, 0)


def _normalize_preset_by_slot(
    preset_powers_t0_or_by_slot: dict[str, float] | dict[int, dict[str, float]] | None,
) -> dict[int, dict[str, float]]:
    """Legacy t0 map {cid: kW} or hour→{cid: kW}."""
    if not preset_powers_t0_or_by_slot:
        return {}
    sample_key = next(iter(preset_powers_t0_or_by_slot))
    sample_val = preset_powers_t0_or_by_slot[sample_key]
    if isinstance(sample_val, dict):
        return {
            int(slot): {str(cid): float(power) for cid, power in powers.items()}
            for slot, powers in preset_powers_t0_or_by_slot.items()
        }
    return {
        0: {
            str(cid): float(power)
            for cid, power in preset_powers_t0_or_by_slot.items()
        }
    }


def _planned_soc_by_ess_at(model: MilpHorizonModel, hour_index: int) -> dict[str, float]:
    """End-of-slot SoC (%) per ESS from ``e_batt_by_ess`` (empty when single/legacy)."""
    ess_ids = getattr(model, "ess_ids", None) or []
    e_by = getattr(model, "e_batt_by_ess", None) or {}
    params_by = getattr(model, "battery_params_by_id", None) or {}
    if len(ess_ids) < 2 or not e_by:
        return {}
    out: dict[str, float] = {}
    for ess_id in ess_ids:
        e_vars = e_by.get(ess_id)
        bat_params = params_by.get(ess_id) or {}
        if not e_vars or hour_index >= len(e_vars):
            continue
        e_val = e_vars[hour_index].varValue
        capacity = float(bat_params.get("battery_capacity_kwh") or 0.0)
        min_soc = float(bat_params.get("min_soc") or 0.0)
        max_soc = float(bat_params.get("max_soc") or 100.0)
        out[str(ess_id)] = bat.planned_soc_percent_from_energy(
            float(e_val) if e_val is not None else 0.0,
            capacity,
            min_soc,
            max_soc,
        )
    return out


def extract_horizon_schedule(
    model: MilpHorizonModel,
    battery_params: dict,
    preset_powers_t0_or_by_slot: dict[str, float] | dict[int, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """
    Extrahiert den vollen MILP-Stundenplan (Batterie + Flex) nach einem Solve.

    EV-Preset-Leistungen (außerhalb der MILP-Variablen) werden je Slot gemerged —
    Live meist nur Slot 0; SE open-loop am günstigsten eligible Slot.
    """
    min_soc = float(battery_params["min_soc"])
    max_soc = float(battery_params["max_soc"])
    capacity = float(battery_params["battery_capacity_kwh"])
    presets_by_slot = _normalize_preset_by_slot(preset_powers_t0_or_by_slot)
    slots: list[dict[str, Any]] = []
    for t in range(model.horizon):
        milp_plan = _extract_milp_plan_at(model, t)
        consumer_powers, _ = _consumer_powers_at(model, t)
        slot_presets = presets_by_slot.get(t)
        if slot_presets:
            consumer_powers = {**consumer_powers, **slot_presets}
        e_val = model.e_batt[t].varValue
        planned_soc = bat.planned_soc_percent_from_energy(
            float(e_val) if e_val is not None else 0.0,
            capacity,
            min_soc,
            max_soc,
        )
        slot: dict[str, Any] = {
            "milp_plan": milp_plan,
            "consumer_powers": consumer_powers,
            "consumer_pv_follow": _consumer_pv_follow_at_all(model, t),
            "planned_soc_percent": planned_soc,
        }
        by_ess = _planned_soc_by_ess_at(model, t)
        if by_ess:
            slot["planned_soc_by_ess"] = by_ess
        slots.append(slot)
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
        logger.debug(
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

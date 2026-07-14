"""Batterie-Steuerung, SoC-Berechnung und Loxone-Modi."""
from __future__ import annotations

import config

MODE_AUTOMATIK = 0
MODE_ZWANGS_LADEN = 1
MODE_ENTLADESPERRE = 2
MODE_ZWANGS_ENTLADEN = 3
SOC_DELTA_THRESHOLD = 0.05


def clamp_power(value: float, max_power: float) -> float:
    return max(-max_power, min(value, max_power))


def power_threshold_kw(max_power_kw: float) -> float:
    """Mindestleistung (kW) aus relativem Schwellenwert und max. Batterieleistung."""
    return max_power_kw * config.get_threshold_power()


def steuerbefehl_for_mode(mode: int, target_power_kw: float = 0.0) -> str:
    """Steuerbefehl-Text für Chart und Simulations-Tabelle."""
    if mode == MODE_ZWANGS_LADEN:
        return f"Zwangsladen ({target_power_kw} kW)"
    if mode == MODE_ENTLADESPERRE:
        return "Entladesperre aktiv"
    if mode == MODE_ZWANGS_ENTLADEN:
        return f"Zwangsentladen ({target_power_kw} kW)"
    return "Automatikbetrieb"


def battery_plan_kw_from_control(
    mode: int,
    target_power_kw: float,
    p_pv: float,
    p_con: float,
    total_flex_power: float,
    max_power_kw: float,
) -> float:
    """Batterieplan für run_state – abgeleitet aus Steuermodus (Huawei-Logik vereinfacht)."""
    net_pv_surplus = p_pv - p_con - total_flex_power
    if mode == MODE_ZWANGS_LADEN:
        return round(clamp_power(target_power_kw, max_power_kw), 3)
    if mode == MODE_ZWANGS_ENTLADEN:
        return round(-clamp_power(target_power_kw, max_power_kw), 3)
    if mode == MODE_ENTLADESPERRE:
        if net_pv_surplus > power_threshold_kw(max_power_kw):
            return round(clamp_power(net_pv_surplus, max_power_kw), 3)
        return 0.0
    return round(clamp_power(net_pv_surplus, max_power_kw), 3)


def automatik_discharge_kw(net_pv_surplus: float, max_power_kw: float) -> float:
    """Entladeleistung (kW, positiv) im Automatikmodus bei Lastdefizit ohne PV-Überschuss."""
    if net_pv_surplus >= -power_threshold_kw(max_power_kw):
        return 0.0
    return round(min(-net_pv_surplus, max_power_kw), 3)


def apply_soc_change(
    old_soc: float,
    batt_action: float,
    battery_capacity_kwh: float,
    efficiency: float,
    min_soc_limit: float,
    max_soc_limit: float,
) -> tuple[float, float]:
    if battery_capacity_kwh <= 0.0:
        return old_soc, 0.0
    if batt_action >= 0:
        energy_change = batt_action * efficiency
    else:
        energy_change = batt_action / efficiency
    soc_change = (energy_change / battery_capacity_kwh) * 100
    new_soc = old_soc + soc_change
    if new_soc > max_soc_limit:
        new_soc = max_soc_limit
        actual_energy = ((max_soc_limit - old_soc) / 100) * battery_capacity_kwh
        batt_action = actual_energy / efficiency if actual_energy >= 0 else actual_energy * efficiency
    elif new_soc < min_soc_limit:
        new_soc = min_soc_limit
        actual_energy = ((min_soc_limit - old_soc) / 100) * battery_capacity_kwh
        batt_action = actual_energy * efficiency if actual_energy < 0 else actual_energy / efficiency
    return new_soc, batt_action


def charge_kw_for_hourly_soc(
    current_soc: float,
    planned_soc: float,
    battery_capacity_kwh: float,
    efficiency: float,
    max_power_kw: float,
    min_soc: float,
    max_soc: float,
) -> float:
    """Ladeleistung (kW) für geplanten SoC nach 1 h (konsistent zu apply_soc_change)."""
    if battery_capacity_kwh <= 0.0:
        return 0.0
    planned = max(min_soc, min(max_soc, planned_soc))
    delta_soc = planned - current_soc
    if delta_soc <= SOC_DELTA_THRESHOLD:
        return 0.0
    energy_kwh = (delta_soc / 100.0) * battery_capacity_kwh
    return round(clamp_power(energy_kwh / efficiency, max_power_kw), 3)


def discharge_kw_for_hourly_soc(
    current_soc: float,
    planned_soc: float,
    battery_capacity_kwh: float,
    efficiency: float,
    max_power_kw: float,
    min_soc: float,
    max_soc: float,
) -> float:
    """Entladeleistung (kW, positiv) für geplanten SoC nach 1 h (konsistent zu apply_soc_change)."""
    if battery_capacity_kwh <= 0.0:
        return 0.0
    planned = max(min_soc, min(max_soc, planned_soc))
    delta_soc = current_soc - planned
    if delta_soc <= SOC_DELTA_THRESHOLD:
        return 0.0
    energy_kwh = (delta_soc / 100.0) * battery_capacity_kwh
    return round(clamp_power(energy_kwh * efficiency, max_power_kw), 3)


def _derive_control_from_milp(
    model,
    matrix: list,
    milp_plan: dict[str, float],
    consumer_powers: dict[str, float],
    total_flex_power: float,
    current_soc: float,
    battery_params: dict,
) -> tuple[int, float, float]:
    min_soc = battery_params["min_soc"]
    max_soc = battery_params["max_soc"]
    max_power = battery_params["max_power_kw"]
    battery_capacity = battery_params["battery_capacity_kwh"]
    efficiency = battery_params["efficiency"]

    if battery_capacity <= 0.0:
        return MODE_AUTOMATIK, 0.0, round(float(current_soc), 1)

    opt_charge = milp_plan["p_charge"]
    opt_discharge = milp_plan["p_discharge"]
    opt_grid_buy = milp_plan["p_grid_buy"]
    p_pv_0 = matrix[0]["expected_p_pv"]
    p_con_0 = matrix[0]["expected_p_act"]
    net_pv_surplus = p_pv_0 - p_con_0 - total_flex_power
    planned_soc = round(
        max(
            min_soc,
            min(max_soc, (model.e_batt[0].varValue / battery_capacity) * 100.0),
        ),
        1,
    )

    mode = MODE_AUTOMATIK
    target_power = 0.0
    target_soc = 99.0
    threshold = power_threshold_kw(max_power)

    if opt_charge > threshold and opt_grid_buy > threshold:
        mode = MODE_ZWANGS_LADEN
        target_soc = round(max(current_soc, planned_soc), 1)
        target_power = charge_kw_for_hourly_soc(
            current_soc,
            target_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
        )
    elif opt_discharge > threshold:
        candidate_soc = round(min(current_soc, planned_soc), 1)
        candidate_power = discharge_kw_for_hourly_soc(
            current_soc,
            candidate_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
        )
        automatik_power = automatik_discharge_kw(net_pv_surplus, max_power)
        if candidate_power > automatik_power + threshold:
            mode = MODE_ZWANGS_ENTLADEN
            target_soc = candidate_soc
            target_power = candidate_power
    elif (
        net_pv_surplus < -threshold
        and opt_discharge < threshold
        and current_soc > (min_soc + 2.0)
    ):
        mode = MODE_ENTLADESPERRE
        target_power = 0.0
        # Ist-SOC: Huawei Register 47100=1 + Ziel 100 % würde sonst Netz-Trickelladen auslösen.
        target_soc = round(current_soc, 1)

    return mode, target_power, target_soc

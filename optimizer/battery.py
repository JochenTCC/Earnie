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


def standby_power_kw(battery_params: dict) -> float:
    """Dauerhafte AC-Standby-Leistung der Hausbatterie (kW)."""
    return max(0.0, float(battery_params.get("standby_power_kw") or 0.0))


def effective_p_act(matrix_row: dict, battery_params: dict) -> float:
    """Grundlast inkl. Batterie-Standby (AC-Verbrauch)."""
    return float(matrix_row["expected_p_act"]) + standby_power_kw(battery_params)


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
    *,
    dt_h: float,
) -> tuple[float, float]:
    if battery_capacity_kwh <= 0.0:
        return old_soc, 0.0
    if batt_action >= 0:
        energy_change = batt_action * efficiency * dt_h
    else:
        energy_change = batt_action / efficiency * dt_h
    soc_change = (energy_change / battery_capacity_kwh) * 100
    new_soc = old_soc + soc_change
    if new_soc > max_soc_limit:
        new_soc = max_soc_limit
        actual_energy = ((max_soc_limit - old_soc) / 100) * battery_capacity_kwh
        # Reverse: energy = p * η * dt_h  →  p = energy / (η * dt_h)
        batt_action = (
            actual_energy / (efficiency * dt_h)
            if actual_energy >= 0
            else actual_energy * efficiency / dt_h
        )
    elif new_soc < min_soc_limit:
        new_soc = min_soc_limit
        actual_energy = ((min_soc_limit - old_soc) / 100) * battery_capacity_kwh
        batt_action = (
            actual_energy * efficiency / dt_h
            if actual_energy < 0
            else actual_energy / (efficiency * dt_h)
        )
    return new_soc, batt_action


def charge_kw_for_hourly_soc(
    current_soc: float,
    planned_soc: float,
    battery_capacity_kwh: float,
    efficiency: float,
    max_power_kw: float,
    min_soc: float,
    max_soc: float,
    *,
    dt_h: float,
) -> float:
    """Ladeleistung (kW) für geplanten SoC nach einem Slot der Länge ``dt_h``."""
    if battery_capacity_kwh <= 0.0:
        return 0.0
    planned = max(min_soc, min(max_soc, planned_soc))
    delta_soc = planned - current_soc
    if delta_soc <= SOC_DELTA_THRESHOLD:
        return 0.0
    energy_kwh = (delta_soc / 100.0) * battery_capacity_kwh
    return round(clamp_power(energy_kwh / (efficiency * dt_h), max_power_kw), 3)


def discharge_kw_for_hourly_soc(
    current_soc: float,
    planned_soc: float,
    battery_capacity_kwh: float,
    efficiency: float,
    max_power_kw: float,
    min_soc: float,
    max_soc: float,
    *,
    dt_h: float,
) -> float:
    """Entladeleistung (kW, positiv) für geplanten SoC nach einem Slot der Länge ``dt_h``."""
    if battery_capacity_kwh <= 0.0:
        return 0.0
    planned = max(min_soc, min(max_soc, planned_soc))
    delta_soc = current_soc - planned
    if delta_soc <= SOC_DELTA_THRESHOLD:
        return 0.0
    energy_kwh = (delta_soc / 100.0) * battery_capacity_kwh
    return round(clamp_power(energy_kwh * efficiency / dt_h, max_power_kw), 3)


def planned_soc_percent_from_energy(
    e_batt_kwh: float,
    battery_capacity_kwh: float,
    min_soc: float,
    max_soc: float,
) -> float:
    """SoC (%) aus MILP-Energiezustand, geclampt auf Batteriegrenzen."""
    if battery_capacity_kwh <= 0.0:
        return round(float(min_soc), 1)
    return round(
        max(min_soc, min(max_soc, (e_batt_kwh / battery_capacity_kwh) * 100.0)),
        1,
    )


def _milp_full_control_setpoint(
    *,
    opt_charge: float,
    opt_discharge: float,
    opt_grid_buy: float,
    net_pv_surplus: float,
    current_soc: float,
    planned_soc: float,
    battery_capacity: float,
    efficiency: float,
    max_power: float,
    min_soc: float,
    max_soc: float,
    dt_h: float,
    threshold: float,
) -> tuple[int, float, float]:
    """Pick forced charge / discharge / Entladesperre for ``control=full``."""
    if opt_charge > threshold and opt_grid_buy > threshold:
        target_soc = round(max(current_soc, planned_soc), 1)
        target_power = charge_kw_for_hourly_soc(
            current_soc,
            target_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
            dt_h=dt_h,
        )
        return MODE_ZWANGS_LADEN, target_power, target_soc

    if opt_discharge > threshold:
        candidate_soc = round(min(current_soc, planned_soc), 1)
        candidate_power = discharge_kw_for_hourly_soc(
            current_soc,
            candidate_soc,
            battery_capacity,
            efficiency,
            max_power,
            min_soc,
            max_soc,
            dt_h=dt_h,
        )
        automatik_power = automatik_discharge_kw(net_pv_surplus, max_power)
        if candidate_power > automatik_power + threshold:
            return MODE_ZWANGS_ENTLADEN, candidate_power, candidate_soc

    if (
        net_pv_surplus < -threshold
        and opt_discharge < threshold
        and current_soc > (min_soc + 2.0)
    ):
        # Ist-SOC: Huawei Register 47100=1 + Ziel 100 % würde sonst Netz-Trickelladen auslösen.
        return MODE_ENTLADESPERRE, 0.0, round(current_soc, 1)

    return MODE_AUTOMATIK, 0.0, 99.0


def derive_control_from_milp_plan(
    milp_plan: dict[str, float],
    matrix_row: dict,
    total_flex_power: float,
    current_soc: float,
    planned_soc: float,
    battery_params: dict,
    *,
    dt_h: float,
) -> tuple[int, float, float]:
    """Leitet Loxone-Modus/Leistung aus MILP-Planwerten einer Stunde ab."""
    from house_config.battery_control import (
        BATTERY_CONTROL_FULL,
        BATTERY_CONTROL_LIMITS_ONLY,
        BATTERY_CONTROL_READ_ONLY,
        control_from_battery_params,
    )
    from .slot_duration import validate_dt_h

    dt_h = validate_dt_h(dt_h)
    min_soc = battery_params["min_soc"]
    max_soc = battery_params["max_soc"]
    max_power = battery_params["max_power_kw"]
    battery_capacity = battery_params["battery_capacity_kwh"]
    efficiency = battery_params["efficiency"]
    control = control_from_battery_params(battery_params)

    if battery_capacity <= 0.0 or control == BATTERY_CONTROL_READ_ONLY:
        return MODE_AUTOMATIK, 0.0, round(float(current_soc), 1)

    net_pv_surplus = (
        matrix_row["expected_p_pv"]
        - effective_p_act(matrix_row, battery_params)
        - total_flex_power
    )
    threshold = power_threshold_kw(max_power)
    mode, target_power, target_soc = MODE_AUTOMATIK, 0.0, 99.0
    if control == BATTERY_CONTROL_FULL:
        mode, target_power, target_soc = _milp_full_control_setpoint(
            opt_charge=milp_plan["p_charge"],
            opt_discharge=milp_plan["p_discharge"],
            opt_grid_buy=milp_plan["p_grid_buy"],
            net_pv_surplus=net_pv_surplus,
            current_soc=current_soc,
            planned_soc=planned_soc,
            battery_capacity=battery_capacity,
            efficiency=efficiency,
            max_power=max_power,
            min_soc=min_soc,
            max_soc=max_soc,
            dt_h=dt_h,
            threshold=threshold,
        )
    elif (
        net_pv_surplus < -threshold
        and milp_plan["p_discharge"] < threshold
        and current_soc > (min_soc + 2.0)
    ):
        # Same Entladesperre path as full-control fallthrough (limits_only etc.).
        mode, target_power, target_soc = (
            MODE_ENTLADESPERRE,
            0.0,
            round(current_soc, 1),
        )

    if control == BATTERY_CONTROL_LIMITS_ONLY and mode in (
        MODE_ZWANGS_LADEN,
        MODE_ZWANGS_ENTLADEN,
    ):
        return MODE_AUTOMATIK, 0.0, round(float(current_soc), 1)

    return mode, target_power, target_soc


def _derive_control_from_milp(
    model,
    matrix: list,
    milp_plan: dict[str, float],
    consumer_powers: dict[str, float],
    total_flex_power: float,
    current_soc: float,
    battery_params: dict,
    hour_index: int = 0,
) -> tuple[int, float, float]:
    min_soc = battery_params["min_soc"]
    max_soc = battery_params["max_soc"]
    battery_capacity = battery_params["battery_capacity_kwh"]
    e_val = model.e_batt[hour_index].varValue
    planned_soc = planned_soc_percent_from_energy(
        float(e_val) if e_val is not None else 0.0,
        battery_capacity,
        min_soc,
        max_soc,
    )
    return derive_control_from_milp_plan(
        milp_plan,
        matrix[hour_index],
        total_flex_power,
        current_soc,
        planned_soc,
        battery_params,
        dt_h=float(model.dt_h),
    )

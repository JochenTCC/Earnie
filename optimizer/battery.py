"""Batterie-Steuerung, SoC-Berechnung und Loxone-Modi."""
from __future__ import annotations

import config

MODE_AUTOMATIK = 0
MODE_ZWANGS_LADEN = 1
MODE_ENTLADESPERRE = 2
MODE_ZWANGS_ENTLADEN = 3
SOC_DELTA_THRESHOLD = 0.05
# Battery key of the DC self-drain (kW) in optimizer params and components.json (Reserve P4).
IDLE_DRAIN_KEY = "idle_drain_kw"


def clamp_power(value: float, max_power: float) -> float:
    return max(-max_power, min(value, max_power))


def power_threshold_kw(max_power_kw: float) -> float:
    """Mindestleistung (kW) aus relativem Schwellenwert und max. Batterieleistung."""
    return max_power_kw * config.get_threshold_power()


def standby_power_kw(battery_params: dict) -> float:
    """Dauerhafte AC-Standby-Leistung der Hausbatterie (kW)."""
    return max(0.0, float(battery_params.get("standby_power_kw") or 0.0))


def idle_drain_kw(battery_params: dict) -> float:
    """DC self-drain of the house battery (kW taken from the stored energy, Reserve P4).

    Not an AC load: it lowers the stored energy, not the house balance. It applies while the
    SoC is above ``idle_drain_floor_soc``. Default 0 (key missing).
    """
    value = float(battery_params.get(IDLE_DRAIN_KEY) or 0.0)
    if value < 0.0:
        raise ValueError(f"{IDLE_DRAIN_KEY} must be >= 0 (got {value!r}).")
    return value


def idle_drain_floor_soc(battery_params: dict) -> float:
    """SoC (%) down to which the idle drain applies: the configured ``min_soc``.

    A virtual reserve raises ``min_soc`` to its floor; the battery drains through that floor
    down to the configured minimum (stored under the reserve's base key).
    """
    from .powerstation_reserve import VIRTUAL_RESERVE_BASE_MIN_SOC_KEY

    base = battery_params.get(VIRTUAL_RESERVE_BASE_MIN_SOC_KEY)
    if base is not None:
        return float(base)
    return float(battery_params["min_soc"])


def idle_drain_soc_pct(soc: float, battery_params: dict, *, dt_h: float) -> float:
    """SoC points the idle drain takes in one slot from ``soc`` (never below its floor)."""
    drain_kw = idle_drain_kw(battery_params)
    capacity = float(battery_params.get("battery_capacity_kwh") or 0.0)
    if drain_kw <= 0.0 or capacity <= 0.0:
        return 0.0
    room = float(soc) - idle_drain_floor_soc(battery_params)
    if room <= 0.0:
        return 0.0
    return min(drain_kw * dt_h / capacity * 100.0, room)


def idle_drain_hold_kwh(battery_params: dict, hold_hours: float) -> float:
    """Energy (kWh) the idle drain takes from a battery held above its floor for ``hold_hours``.

    The hold cost of a reserve (Reserve P2) and the refill band (Reserve P3) read the drain
    through this function. It is the value the plan and the simulation use
    (``idle_drain_kw``); a learned value (``runtime_store.idle_drain_learner``) is only a
    suggestion until it is configured.
    """
    if hold_hours < 0.0:
        raise ValueError(f"hold_hours must be >= 0 (got {hold_hours!r}).")
    return idle_drain_kw(battery_params) * float(hold_hours)


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
    *,
    automatik_discharge_cap_kw: float | None = None,
) -> float:
    """Batterieplan für run_state – abgeleitet aus Steuermodus (Huawei-Logik vereinfacht).

    ``automatik_discharge_cap_kw`` limits the discharge in Automatik (import cap, the plan's
    partial discharge); the inverter gets the same value as its discharge limit.
    """
    net_pv_surplus = p_pv - p_con - total_flex_power
    if mode == MODE_ZWANGS_LADEN:
        return round(clamp_power(target_power_kw, max_power_kw), 3)
    if mode == MODE_ZWANGS_ENTLADEN:
        return round(-clamp_power(target_power_kw, max_power_kw), 3)
    if mode == MODE_ENTLADESPERRE:
        if net_pv_surplus > power_threshold_kw(max_power_kw):
            return round(clamp_power(net_pv_surplus, max_power_kw), 3)
        return 0.0
    action = clamp_power(net_pv_surplus, max_power_kw)
    if automatik_discharge_cap_kw is not None:
        action = max(action, -max(0.0, float(automatik_discharge_cap_kw)))
    return round(action, 3)


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
    idle_drain_kw: float = 0.0,
    idle_drain_floor_soc: float | None = None,
) -> tuple[float, float]:
    """SoC after one slot of ``batt_action`` (kW, charging positive) and the power that fits.

    The SoC limits cut the action, they never add to it: the returned power has the sign of
    ``batt_action`` and at most its size. A start outside the limits (measured SoC below
    ``min_soc`` or above ``max_soc``) stays where it is until an action moves it back in; it
    does not jump to the limit, and an action that would move it further out is dropped.

    ``idle_drain_kw`` (Reserve P4): DC self-drain taken from the stored energy after the
    action, down to ``idle_drain_floor_soc`` at most; it does not change the returned power.
    Pass both with ``idle_drain_kwargs(battery_params)``.
    """
    if battery_capacity_kwh <= 0.0:
        return old_soc, 0.0
    if batt_action >= 0:
        energy_change = batt_action * efficiency * dt_h
    else:
        energy_change = batt_action / efficiency * dt_h
    soc_change = (energy_change / battery_capacity_kwh) * 100
    new_soc = old_soc + soc_change
    upper = max(max_soc_limit, old_soc)
    lower = min(min_soc_limit, old_soc)
    if new_soc > upper:
        new_soc = upper
        charged_kwh = ((upper - old_soc) / 100) * battery_capacity_kwh
        # Reverse: energy = p * η * dt_h  →  p = energy / (η * dt_h)
        batt_action = charged_kwh / (efficiency * dt_h)
    elif new_soc < lower:
        new_soc = lower
        discharged_kwh = ((lower - old_soc) / 100) * battery_capacity_kwh
        batt_action = discharged_kwh * efficiency / dt_h
    if idle_drain_kw > 0.0:
        if idle_drain_floor_soc is None:
            raise ValueError("apply_soc_change: idle_drain_kw needs idle_drain_floor_soc.")
        room = new_soc - float(idle_drain_floor_soc)
        if room > 0.0:
            new_soc -= min(idle_drain_kw * dt_h / battery_capacity_kwh * 100.0, room)
    return new_soc, batt_action


def idle_drain_kwargs(battery_params: dict) -> dict[str, float | None]:
    """``apply_soc_change`` keywords of the idle drain of ``battery_params`` (empty without)."""
    drain_kw = idle_drain_kw(battery_params)
    if drain_kw <= 0.0:
        return {}
    return {
        "idle_drain_kw": drain_kw,
        "idle_drain_floor_soc": idle_drain_floor_soc(battery_params),
    }


def vendor_mode_step(
    sim_soc: float,
    net_pv_surplus_kw: float,
    battery_params: dict,
    *,
    dt_h: float,
) -> tuple[float, float]:
    """One slot of the battery in vendor mode (self-consumption, no grid charging).

    Charges the PV surplus and discharges on deficit, clamped to ``max_power_kw``
    and to ``min_soc`` / ``max_soc``. ``net_pv_surplus_kw`` is PV minus the load the
    battery sees (standby included by the caller). Returns ``(soc_next, batt_kw)``
    with ``batt_kw`` positive while charging.
    """
    batt_action = clamp_power(net_pv_surplus_kw, battery_params["max_power_kw"])
    return apply_soc_change(
        sim_soc,
        batt_action,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["min_soc"],
        battery_params["max_soc"],
        dt_h=dt_h,
        **idle_drain_kwargs(battery_params),
    )


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
    opt_grid_sell: float,
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
    drain_soc_pct: float = 0.0,
) -> tuple[int, float, float]:
    """Pick forced charge / discharge / Entladesperre for ``control=full``.

    The setpoint follows the plan's SoC also while the battery is outside its limits
    (``milp_soc_recovery``): the limits are widened to the current SoC, so the power is the
    plan's and not what would reach the limit within this slot.

    ``drain_soc_pct``: SoC points the idle drain takes in this slot (Reserve P4). The plan has
    no drain (the MILP leaves it out); the power is that of the plan's SoC plus the drain, so
    the battery lands on the plan's SoC after the drain of the slot.
    """
    soc_floor = min(min_soc, current_soc)
    soc_ceiling = max(max_soc, current_soc) + drain_soc_pct
    if opt_charge > threshold and opt_grid_buy > threshold:
        target_soc = round(max(current_soc, planned_soc), 1)
        target_power = charge_kw_for_hourly_soc(
            current_soc,
            round(max(current_soc, planned_soc + drain_soc_pct), 1),
            battery_capacity,
            efficiency,
            max_power,
            soc_floor,
            soc_ceiling,
            dt_h=dt_h,
        )
        return MODE_ZWANGS_LADEN, target_power, target_soc

    if opt_discharge > threshold:
        candidate_soc = round(min(current_soc, planned_soc), 1)
        candidate_power = discharge_kw_for_hourly_soc(
            current_soc,
            round(min(current_soc, planned_soc + drain_soc_pct), 1),
            battery_capacity,
            efficiency,
            max_power,
            soc_floor,
            soc_ceiling,
            dt_h=dt_h,
        )
        automatik_power = automatik_discharge_kw(net_pv_surplus, max_power)
        # Above the deficit the extra power is export: only when the plan sells. A SoC above plan
        # (flex delivered less than the plan's on-slots) stays in the battery.
        if candidate_power > automatik_power + threshold and opt_grid_sell > threshold:
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

    from house_config.inverter import AC_GRID_TIED

    ac_connection = str(
        battery_params.get("ac_connection") or AC_GRID_TIED
    ).strip().lower()
    ess_plan = _ess_plan_for_battery(milp_plan, battery_params)

    net_pv_surplus = (
        matrix_row["expected_p_pv"]
        - effective_p_act(matrix_row, battery_params)
        - total_flex_power
    )
    threshold = power_threshold_kw(max_power)
    mode, target_power, target_soc = MODE_AUTOMATIK, 0.0, 99.0
    if control == BATTERY_CONTROL_FULL:
        mode, target_power, target_soc = _milp_full_control_setpoint(
            opt_charge=float(ess_plan.get("p_charge") or 0.0),
            opt_discharge=float(ess_plan.get("p_discharge") or 0.0),
            opt_grid_buy=float(milp_plan.get("p_grid_buy") or 0.0),
            opt_grid_sell=float(milp_plan.get("p_grid_sell") or 0.0),
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
            drain_soc_pct=idle_drain_soc_pct(current_soc, battery_params, dt_h=dt_h),
        )
    elif (
        net_pv_surplus < -threshold
        and float(ess_plan.get("p_discharge") or 0.0) < threshold
        and current_soc > (min_soc + 2.0)
    ):
        # Same Entladesperre path as full-control fallthrough (limits_only etc.).
        mode, target_power, target_soc = (
            MODE_ENTLADESPERRE,
            0.0,
            round(current_soc, 1),
        )

    if mode == MODE_ZWANGS_LADEN:
        target_power = _charge_within_import_cap(
            target_power, milp_plan, ess_plan, -net_pv_surplus
        )
    return _apply_control_overrides(
        control, ac_connection, (mode, target_power, target_soc), current_soc
    )


def _planned_import_kw(milp_plan: dict) -> float | None:
    """Import the plan allows in this slot: its limit plus its slack; ``None`` without a limit.

    Only a plan solved with the limit (``import_cap_mode: optimize``) carries it; observe mode
    executes a plan without.
    """
    limit = milp_plan.get("import_cap_limit_kw")
    if limit is None:
        return None
    return float(limit) + max(0.0, float(milp_plan.get("import_cap_slack_kw") or 0.0))


def _charge_within_import_cap(
    target_power: float, milp_plan: dict, ess_plan: dict, deficit_kw: float
) -> float:
    """Forced charge chasing the plan's SoC: no more than the limit leaves, never below the plan."""
    allowed = _planned_import_kw(milp_plan)
    if allowed is None:
        return target_power
    headroom = allowed - deficit_kw
    planned = max(0.0, float(ess_plan.get("p_charge") or 0.0))
    return round(min(target_power, max(planned, headroom)), 3)


def import_cap_discharge_cap_kw(
    milp_plan: dict,
    matrix_row: dict,
    total_flex_power: float,
    battery_params: dict,
) -> float | None:
    """Discharge limit for Automatik in a slot with an import limit; ``None`` without one.

    Under a limit the plan spreads the battery over the slots; Automatik alone would cover the
    whole deficit and empty the battery early. The limit is the plan's discharge, raised to what
    keeps the import at the plan's level when the load is above the forecast.
    """
    allowed = _planned_import_kw(milp_plan)
    if allowed is None:
        return None
    ess_plan = _ess_plan_for_battery(milp_plan, battery_params)
    planned = max(0.0, float(ess_plan.get("p_discharge") or 0.0))
    deficit = (
        effective_p_act(matrix_row, battery_params)
        + total_flex_power
        - float(matrix_row["expected_p_pv"])
    )
    return round(max(planned, deficit - allowed), 3)


def _apply_control_overrides(
    control: str,
    ac_connection: str,
    setpoint: tuple[int, float, float],
    current_soc: float,
) -> tuple[int, float, float]:
    """limits_only drops forced modes; island inverters never stay in Automatik."""
    from house_config.battery_control import BATTERY_CONTROL_LIMITS_ONLY
    from house_config.inverter import allows_automatik

    mode, target_power, target_soc = setpoint
    if control == BATTERY_CONTROL_LIMITS_ONLY and mode in (
        MODE_ZWANGS_LADEN,
        MODE_ZWANGS_ENTLADEN,
    ):
        mode, target_power, target_soc = (
            MODE_AUTOMATIK,
            0.0,
            round(float(current_soc), 1),
        )

    # Island inverter: never Automatik — map hold to standby (Entladesperre).
    if not allows_automatik(ac_connection) and mode == MODE_AUTOMATIK:
        mode, target_power, target_soc = (
            MODE_ENTLADESPERRE,
            0.0,
            round(float(current_soc), 1),
        )

    return mode, target_power, target_soc


def _ess_plan_for_battery(
    milp_plan: dict[str, float], battery_params: dict
) -> dict[str, float]:
    """Plan values of this battery: merge ``milp_plan['ess'][id]`` over the plant plan."""
    if isinstance(milp_plan.get("ess"), dict):
        ess_id = str(battery_params.get("id") or "").strip()
        if ess_id and ess_id in milp_plan["ess"]:
            return {**milp_plan, **milp_plan["ess"][ess_id]}
    return milp_plan


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
        min(min_soc, current_soc),
        max(max_soc, current_soc),
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

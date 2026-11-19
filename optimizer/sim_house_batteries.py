"""Per-battery SoC step of the horizon simulation with several house batteries.

With one house battery the simulation books that battery (``sim_chart_rows``). With several it
keeps a SoC per house battery: each battery gets its own control from its part of the MILP plan
(``milp_plan["ess"][id]`` and its planned SoC), forced charge or discharge runs at that battery's
power, and the batteries in Automatik or Entladesperre take the house residual (PV − load − flex)
one after the other in configuration order, each up to its power and SoC limits. The chart row
books the sum of their actions and, as its SoC, the plant SoC (stored energy over capacity,
``plant_soc_percent``). The ``Steuerbefehl`` column is the first battery's command, the one the
live cycle writes.
"""
from __future__ import annotations

from dataclasses import dataclass

from optimizer import battery as bat
from optimizer.milp_horizon import plant_soc_percent
from optimizer.sim_chart_rows import (
    COL_PV_PROGNOSE,
    COL_VERBRAUCH_PROGNOSE,
    chart_row_layout,
    flexible_consumer_power_kw,
    set_chart_row_battery_action,
)
from optimizer.slot_duration import DEFAULT_DT_H

_FORCED_MODES = (bat.MODE_ZWANGS_LADEN, bat.MODE_ZWANGS_ENTLADEN)


@dataclass(frozen=True)
class HouseBatteryControl:
    """Control of one house battery in one slot."""

    ess_id: str
    mode: int
    target_power: float


def battery_id(battery: dict, index: int) -> str:
    """Id of a battery as the MILP names it (``_create_grid_battery_vars``)."""
    return str(battery.get("id") or f"ess_{index}").strip() or f"ess_{index}"


def house_battery_start_socs(
    house: list[dict], current_soc_by_id: dict[str, float] | None
) -> dict[str, float]:
    """Start SoC of each house battery; ``ValueError`` when one with capacity has none."""
    by_id = current_soc_by_id or {}
    out: dict[str, float] = {}
    missing: list[str] = []
    for index, battery in enumerate(house):
        ess_id = battery_id(battery, index)
        if ess_id in by_id:
            out[ess_id] = float(by_id[ess_id])
        elif float(battery.get("battery_capacity_kwh") or 0.0) > 0.0:
            missing.append(ess_id)
    if missing:
        raise ValueError(
            f"Horizon simulation: no start SoC for house battery {missing} "
            f"(have: {sorted(by_id)})."
        )
    return out


def stepping_batteries(house: list[dict]) -> list[tuple[str, dict]]:
    """(id, params) of the house batteries that store energy, in configuration order."""
    return [
        (battery_id(battery, index), battery)
        for index, battery in enumerate(house)
        if float(battery.get("battery_capacity_kwh") or 0.0) > 0.0
    ]


def house_plant_soc(house: list[dict], soc_by_house: dict[str, float]) -> float:
    """Plant SoC of the house batteries (energy-weighted)."""
    return plant_soc_percent(house, soc_by_house)


def house_battery_controls(
    milp_plan: dict,
    planned_soc_by_ess: dict[str, float] | None,
    row: dict,
    total_flex: float,
    soc_by_house: dict[str, float],
    house: list[dict],
    plant: dict,
) -> tuple[HouseBatteryControl, ...]:
    """Control of each house battery from its part of the plan.

    A slot without a per-battery plan (Automatik fallback, trivial window) plans each battery to
    stay where it is, as a slot without ``planned_soc_percent`` does with one battery. A plan
    that lacks a battery raises.
    """
    controls: list[HouseBatteryControl] = []
    for ess_id, params in stepping_batteries(house):
        soc = soc_by_house[ess_id]
        if planned_soc_by_ess:
            if ess_id not in planned_soc_by_ess:
                raise ValueError(
                    f"MILP plan without planned SoC for house battery '{ess_id}' "
                    f"(have: {sorted(planned_soc_by_ess)})."
                )
            planned = float(planned_soc_by_ess[ess_id])
        else:
            planned = soc
        # The house load of the plant row carries the standby of all batteries.
        view = {**params, "standby_power_kw": float(plant.get("standby_power_kw") or 0.0)}
        mode, target_power, _ = bat.derive_control_from_milp_plan(
            milp_plan, row, total_flex, soc, planned, view, dt_h=DEFAULT_DT_H
        )
        controls.append(HouseBatteryControl(ess_id, mode, target_power))
    return tuple(controls)


def step_house_batteries(
    controls: tuple[HouseBatteryControl, ...],
    house: list[dict],
    soc_by_house: dict[str, float],
    *,
    pv: float,
    con: float,
    total_flex: float,
) -> tuple[dict[str, float], float]:
    """End SoC of each house battery after one slot and the summed battery action [kW].

    Forced charge or discharge runs at the battery's target power. The other batteries take the
    house residual one after the other, each as far as its power and SoC limits allow.
    """
    params_by_id = dict(stepping_batteries(house))
    residual = pv - con - total_flex
    end: dict[str, float] = dict(soc_by_house)
    total = 0.0
    for control in controls:
        params = params_by_id[control.ess_id]
        max_power = float(params["max_power_kw"])
        if control.mode in _FORCED_MODES:
            action = bat.battery_plan_kw_from_control(
                control.mode, control.target_power, pv, con, total_flex, max_power
            )
        else:
            action = bat.battery_plan_kw_from_control(
                control.mode, control.target_power, residual, 0.0, 0.0, max_power
            )
        new_soc, action = bat.apply_soc_change(
            soc_by_house[control.ess_id],
            action,
            float(params["battery_capacity_kwh"]),
            float(params["efficiency"]),
            float(params["min_soc"]),
            float(params["max_soc"]),
            dt_h=DEFAULT_DT_H,
        )
        if control.mode not in _FORCED_MODES:
            residual -= action
        end[control.ess_id] = new_soc
        total += action
    return end, total


def house_chart_row(
    row: dict,
    soc_by_house: dict[str, float],
    house: list[dict],
    plant: dict,
    consumers_cfg: list,
    milp_plan: dict,
    planned_soc_by_ess: dict[str, float] | None,
    consumer_powers: dict[str, float],
    consumer_pv_follow: dict[str, int],
) -> tuple[dict, tuple[HouseBatteryControl, ...]]:
    """Chart row of one slot with several house batteries and the controls of the batteries."""
    pv = row["expected_p_pv"]
    con = bat.effective_p_act(row, plant)
    total_flex = sum(consumer_powers.values())
    controls = house_battery_controls(
        milp_plan, planned_soc_by_ess, row, total_flex, soc_by_house, house, plant
    )
    _, total = step_house_batteries(
        controls, house, soc_by_house, pv=pv, con=con, total_flex=total_flex
    )
    first = controls[0] if controls else HouseBatteryControl("", bat.MODE_AUTOMATIK, 0.0)
    chart_row = chart_row_layout(
        row,
        pv=pv,
        con=con,
        total_flex_power=total_flex,
        batt_action=total,
        start_soc=house_plant_soc(house, soc_by_house),
        action_text=bat.steuerbefehl_for_mode(first.mode, first.target_power),
        consumers_cfg=consumers_cfg,
        consumer_powers=consumer_powers,
        consumer_pv_follow=consumer_pv_follow,
    )
    return chart_row, controls


def finalize_house_row_energy(
    chart_row: dict,
    controls: tuple[HouseBatteryControl, ...],
    house: list[dict],
    soc_by_house: dict[str, float],
) -> dict[str, float]:
    """Battery action and grid power of the final row (flex capped); returns the end SoCs."""
    end, total = step_house_batteries(
        controls,
        house,
        soc_by_house,
        pv=float(chart_row[COL_PV_PROGNOSE]),
        con=float(chart_row[COL_VERBRAUCH_PROGNOSE]),
        total_flex=flexible_consumer_power_kw(chart_row),
    )
    set_chart_row_battery_action(chart_row, total)
    return end

"""House battery params for the MILP: list coercion and the plant battery over several batteries.

Split out of ``optimizer.milp_horizon`` (still re-exported there).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .battery import IDLE_DRAIN_KEY, idle_drain_kw

if TYPE_CHECKING:
    from .milp_horizon_types import MilpHorizonModel


def coerce_battery_params_list(
    battery_params: dict | list[dict] | None,
) -> list[dict]:
    """Normalize singular or list battery params for multi-ESS MILP (2.7.c)."""
    if battery_params is None:
        return []
    if isinstance(battery_params, list):
        return [dict(item) for item in battery_params if isinstance(item, dict)]
    if isinstance(battery_params, dict):
        return [dict(battery_params)]
    return []


def primary_battery_with_plant_power(batteries: list[dict]) -> dict:
    """The first battery with the charge, discharge and standby power of all batteries.

    Capacity, SoC limits, efficiency, ``control`` and the virtual reserve keys are those of the
    first battery. The MILP's grid balance needs the power of all; the virtual reserve and the
    trivial-window check refer to the first battery. It is not a model of the whole plant: the
    plan's SoC (``model.e_batt``) is the plant's (``plant_soc_view``), and the simulation and the
    charts use ``plant_battery_params``.
    """
    if not batteries:
        return {
            "battery_capacity_kwh": 0.0,
            "min_soc": 0.0,
            "max_soc": 100.0,
            "max_charge_power_kw": 0.0,
            "max_discharge_power_kw": 0.0,
            "max_power_kw": 0.0,
            "efficiency": 1.0,
            "standby_power_kw": 0.0,
            "control": "full",
        }
    agg = dict(batteries[0])
    agg["standby_power_kw"] = sum(
        float(b.get("standby_power_kw") or 0.0) for b in batteries
    )
    if any(IDLE_DRAIN_KEY in b for b in batteries):
        agg[IDLE_DRAIN_KEY] = sum(idle_drain_kw(b) for b in batteries)
    agg["max_charge_power_kw"] = sum(
        float(b.get("max_charge_power_kw", b.get("max_power_kw") or 0.0) or 0.0)
        for b in batteries
    )
    agg["max_discharge_power_kw"] = sum(
        float(b.get("max_discharge_power_kw", b.get("max_power_kw") or 0.0) or 0.0)
        for b in batteries
    )
    agg["max_power_kw"] = max(agg["max_charge_power_kw"], agg["max_discharge_power_kw"])
    return agg


def plant_battery_params(batteries: list[dict]) -> dict:
    """One battery that stands for all of ``batteries`` (simulation and charts).

    Power and standby are summed and the capacity is the sum. The SoC limits are the summed
    energy limits as a share of that capacity, so the usable energy equals that of the single
    batteries. The efficiency is capacity-weighted. With one battery the result is that of
    ``primary_battery_with_plant_power``. Keys that describe one battery (``id``, ``label``,
    virtual reserve) stay those of the first.

    Raises ``ValueError`` when the batteries have different ``control`` modes: one battery
    cannot stand for a plant that is only partly controllable.
    """
    if len(batteries) >= 2:
        from house_config.battery_control import control_from_battery_params

        controls = {str(b.get("id") or "?"): control_from_battery_params(b) for b in batteries}
        if len(set(controls.values())) > 1:
            raise ValueError(
                "House batteries with different control modes cannot be simulated as one plant "
                f"battery: {controls}."
            )
    return plant_energy_params(batteries)


def plant_energy_params(batteries: list[dict]) -> dict:
    """``plant_battery_params`` without the check of the control modes (``control`` of the first)."""
    agg = primary_battery_with_plant_power(batteries)
    if len(batteries) < 2:
        return agg
    capacities = [float(b.get("battery_capacity_kwh") or 0.0) for b in batteries]
    total = sum(capacities)
    agg["battery_capacity_kwh"] = total
    if total <= 0.0:
        # No energy to weight by: the limits of the first battery stay, they bound nothing.
        return agg
    for key in ("min_soc", "max_soc", "efficiency"):
        agg[key] = sum(cap * float(b[key]) for cap, b in zip(capacities, batteries)) / total
    return agg


def plant_soc_percent(batteries: list[dict], soc_by_id: dict[str, float]) -> float:
    """SoC of the plant battery (``plant_battery_params``): stored energy over total capacity.

    Raises ``ValueError`` when a battery with capacity has no SoC in ``soc_by_id`` or the
    batteries have no capacity at all.
    """
    energy = 0.0
    total = 0.0
    for index, battery in enumerate(batteries):
        capacity = float(battery.get("battery_capacity_kwh") or 0.0)
        if capacity <= 0.0:
            continue
        ess_id = str(battery.get("id") or f"ess_{index}").strip() or f"ess_{index}"
        if ess_id not in soc_by_id:
            raise ValueError(
                f"Plant SoC: no SoC for house battery '{ess_id}' (have: {sorted(soc_by_id)})."
            )
        energy += capacity * float(soc_by_id[ess_id])
        total += capacity
    if total <= 0.0:
        raise ValueError("Plant SoC: the house batteries have no capacity.")
    return energy / total


def plant_soc_params(model: MilpHorizonModel, battery_params: dict) -> dict:
    """Battery that the plan's SoC (``model.e_batt``) refers to.

    ``battery_params`` with one house battery in the model. With several, ``model.e_batt`` is the
    energy of all house batteries and the battery is the plant battery over the house batteries
    of the model (``plant_battery_params`` without ``id`` and ``label``, so the plan values are
    those of the plant; ``control``, ``ac_connection`` and the virtual reserve keys are those of
    the first battery, the one the live cycle commands).
    """
    ess_ids = list(model.ess_ids or [])
    if len(ess_ids) < 2:
        return battery_params
    params_by_id = model.battery_params_by_id or {}
    params = plant_energy_params([params_by_id[eid] for eid in ess_ids])
    params.pop("id", None)
    params.pop("label", None)
    return params


def plant_soc_view(
    model: MilpHorizonModel, current_soc: float, battery_params: dict
) -> tuple[float, dict]:
    """Start SoC and battery that the plan's SoC (``model.e_batt``) refers to.

    With one house battery in the model these are ``current_soc`` and ``battery_params``. With
    several, the plant SoC at the plan start (from each battery's own start SoC; ``current_soc``
    is not used) and ``plant_soc_params``.
    """
    params = plant_soc_params(model, battery_params)
    if params is battery_params:
        return float(current_soc), battery_params
    capacity = float(params.get("battery_capacity_kwh") or 0.0)
    if capacity <= 0.0:
        raise ValueError(f"MILP: the house batteries {model.ess_ids} have no capacity.")
    if model.plant_start_energy_kwh is None:
        raise ValueError("MILP model without plant start energy (plant_start_energy_kwh).")
    return float(model.plant_start_energy_kwh) / capacity * 100.0, params

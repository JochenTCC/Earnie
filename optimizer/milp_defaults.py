"""Default battery / inverter / PV params for MILP entry points."""
from __future__ import annotations

import config


def _default_battery_params() -> dict | list[dict]:
    """Prefer multi-ESS list (2.7.c); fall back to singular snapshot."""
    get_list = getattr(config, "get_battery_params_list", None)
    if callable(get_list):
        batteries = get_list()
        if batteries:
            return batteries
    return config.get_battery_params()


def _default_inverter_params() -> list[dict]:
    get_list = getattr(config, "get_planning_inverters", None)
    if callable(get_list):
        return list(get_list() or [])
    return list(getattr(config, "_planning_inverters", None) or [])


def _default_pv_systems() -> list[dict]:
    get_list = getattr(config, "get_planning_pv_systems", None)
    if callable(get_list):
        return list(get_list() or [])
    return list(getattr(config, "_planning_pv_systems", None) or [])


def _primary_battery_params(battery_params: dict | list[dict]) -> dict:
    from .milp_horizon import aggregate_battery_params_for_load, coerce_battery_params_list

    batteries = coerce_battery_params_list(battery_params)
    if not batteries:
        return {}
    return aggregate_battery_params_for_load(batteries)

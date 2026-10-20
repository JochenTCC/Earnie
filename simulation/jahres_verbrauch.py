"""Jahres Verbrauch [kWh] — shared SE Gesamtkosten / Fake-Jahresrechnung source.

All rows (Historisch, ``ref:*``, optimized) read the booked series totals from
``simulation.booked_consumption`` (``backtesting_log.json`` → ``booked_consumption``):
each slot once, battery standby reported separately.
"""
from __future__ import annotations


def _booked_value(booked_consumption: dict, scenario_id: str, key: str) -> float | None:
    block = (booked_consumption or {}).get(scenario_id)
    if not block:
        return None
    value = block.get(key)
    return None if value is None else float(value)


def jahres_verbrauch_kwh(scenario_id: str, *, booked_consumption: dict) -> float | None:
    """Booked consumption (kWh, without battery standby) of one result series."""
    return _booked_value(booked_consumption, scenario_id, "consumption_kwh")


def jahres_standby_kwh(scenario_id: str, *, booked_consumption: dict) -> float | None:
    """Battery standby (kWh) booked alongside the consumption of one result series."""
    return _booked_value(booked_consumption, scenario_id, "standby_kwh")


def jahres_verbrauch_map(
    scenario_ids: list[str],
    *,
    booked_consumption: dict,
) -> dict[str, float]:
    """Non-null Jahres Verbrauch values keyed by result scenario id."""
    out: dict[str, float] = {}
    for scenario_id in scenario_ids:
        value = jahres_verbrauch_kwh(scenario_id, booked_consumption=booked_consumption)
        if value is not None:
            out[scenario_id] = float(value)
    return out

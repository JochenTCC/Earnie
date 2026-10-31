"""Fuel demand, fuel cost and CO2 per SE result series (SUSI P1).

A fuel heat source (gas, oil, pellets, district heat, wood) draws no power, so its energy
is not in the booked electricity series. Per result: fuel kWh = modeled daily fuel of the
house profile's ``thermal_annual`` consumer over the booked slots (each day weighted by the
share of its slots that were booked) minus the heat the heating rod delivered (η = 1,
rod kWh / efficiency of the fuel source). CO2 = grid import × electricity factor + fuel ×
carrier factor (``share/config/heat_source_defaults.json``). Results without a house
profile (no model) get only the electricity part.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

import pandas as pd

from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h

HEAT_FUEL_KEY = "heat_fuel"


def _unique_slots(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    index = pd.DatetimeIndex(frame.index)
    frame.index = index.tz_localize(None) if index.tz is not None else index
    return frame.loc[~frame.index.duplicated(keep="last")]


def _fuel_consumers(profile: dict) -> list[tuple[dict, dict]]:
    from house_config.heat_source import consumer_heat_source, heat_source_is_electric

    out: list[tuple[dict, dict]] = []
    for consumer in profile.get("consumers") or []:
        if consumer.get("type") != "thermal_annual":
            continue
        heat_source = consumer_heat_source(consumer)
        if not heat_source_is_electric(heat_source):
            out.append((consumer, heat_source))
    return out


def _booked_fuel_kwh(
    consumer: dict,
    profile: dict,
    slots_per_day: Counter,
    *,
    climate,
    dt_h: float,
) -> float:
    from optimizer.thermal_flex_context import thermal_daily_fuel_kwh_for_date

    total = 0.0
    for day, slots in slots_per_day.items():
        share = min(1.0, slots * dt_h / 24.0)
        total += share * thermal_daily_fuel_kwh_for_date(
            consumer, profile, day, climate=climate
        )
    return total


def _rod_kwh(unique: pd.DataFrame, consumer: dict, dt_h: float) -> float:
    from house_config.heat_source import heating_rod_part, part_kennung

    part = heating_rod_part(consumer)
    if part is None:
        return 0.0
    column = f"{part_kennung(str(consumer['id']), str(part['id']))}_kw"
    if column not in unique.columns:
        return 0.0
    return float(unique[column].fillna(0.0).sum()) * dt_h


def heat_fuel_for_result(df: pd.DataFrame, scenario_params: dict | None) -> dict:
    """Fuel / CO2 block of one result series (clipped to the reporting period)."""
    from data.modeled_climate import ModeledClimateContext
    from house_config.heat_source import (
        electricity_co2_g_per_kwh,
        fuel_co2_g_per_kwh,
        fuel_price_eur_per_kwh,
        heat_source_efficiency,
    )

    dt_h = validate_dt_h(DEFAULT_DT_H)
    unique = _unique_slots(df)
    import_kwh = float(unique["import_kwh"].fillna(0.0).sum()) if "import_kwh" in unique else 0.0
    co2_g = import_kwh * electricity_co2_g_per_kwh()
    fuel_kwh = 0.0
    fuel_eur = 0.0
    carriers: list[str] = []
    profile = (scenario_params or {}).get("_house_profile")
    if isinstance(profile, dict):
        consumers = _fuel_consumers(profile)
        if consumers:
            climate = ModeledClimateContext.from_scenario(scenario_params or {})
            slots_per_day: Counter = Counter(
                ts.date() for ts in unique.index if isinstance(ts.date(), date)
            )
            for consumer, heat_source in consumers:
                modeled = _booked_fuel_kwh(
                    consumer, profile, slots_per_day, climate=climate, dt_h=dt_h
                )
                rod_heat = _rod_kwh(unique, consumer, dt_h)
                kwh = max(0.0, modeled - rod_heat / heat_source_efficiency(heat_source))
                fuel_kwh += kwh
                fuel_eur += kwh * float(fuel_price_eur_per_kwh(heat_source))
                co2_g += kwh * float(fuel_co2_g_per_kwh(heat_source))
                carriers.append(str(heat_source["type"]))
    return {
        "fuel_kwh": round(fuel_kwh, 1),
        "fuel_eur": round(fuel_eur, 2),
        "co2_kg": round(co2_g / 1000.0, 1),
        "import_kwh": round(import_kwh, 1),
        "carriers": carriers,
    }


def heat_fuel_by_result(
    results: dict[str, pd.DataFrame],
    params_by_result: dict[str, dict | None],
) -> dict[str, dict]:
    return {
        sid: heat_fuel_for_result(df, params_by_result.get(sid))
        for sid, df in results.items()
        if df is not None and not df.empty
    }

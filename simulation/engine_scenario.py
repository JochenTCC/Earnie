"""Scenario-derived consumers, battery params and slot helpers of the simulation engine (split from engine)."""
from __future__ import annotations

from datetime import datetime
import pandas as pd
import config
from data.market_prices import epex_prices_for_slots


def _flexible_consumers_from_scenario(scenario_params: dict | None) -> list:
    from house_config.planning_flex_bridge import merge_flexible_consumers

    base = config.get_flexible_consumers(optimizer_only=True)
    if not scenario_params:
        return base
    planning = scenario_params.get("_planning_flex_consumers") or []
    return merge_flexible_consumers(base, planning)


def resolved_flexible_consumers(
    scenario_params: dict | None = None,
    *,
    optimizer_only: bool = False,
) -> list:
    """Unified flex registry: config.json + planning merge (Chart 1 / Sankey / MILP)."""
    if scenario_params is None:
        return config.get_flexible_consumers(optimizer_only=optimizer_only)
    if optimizer_only:
        return _flexible_consumers_from_scenario(scenario_params)
    base = config.get_flexible_consumers(optimizer_only=False)
    planning = scenario_params.get("_planning_flex_consumers") or []
    if not planning:
        return base
    from house_config.planning_flex_bridge import merge_flexible_consumers

    return merge_flexible_consumers(base, planning)


def flex_consumers_for_backtesting_scenario(scenario_id: str) -> list:
    """Resolved flex list for a backtesting scenario_id (Chart 1 / Sankey)."""
    scenarios = config.get_backtesting_scenarios()
    scenario_params = scenarios.get(scenario_id)
    if not scenario_params:
        return resolved_flexible_consumers(None, optimizer_only=False)
    return resolved_flexible_consumers(scenario_params, optimizer_only=False)


def flex_consumers_from_snapshot(snapshot: dict) -> list:
    """
    Flex registry for backtesting display: MILP meta snapshot first, else scenario resolve.
    """
    meta = snapshot.get("meta") or {}
    stored = meta.get("_flexible_consumers")
    if isinstance(stored, list) and stored:
        return stored
    scenario_id = str(snapshot.get("scenario_id", "") or "").strip()
    if scenario_id:
        return flex_consumers_for_backtesting_scenario(scenario_id)
    return resolved_flexible_consumers(
        config.get_resolved_runtime_settings(),
        optimizer_only=False,
    )


def _charging_schedule_consumer() -> dict | None:
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        sched = consumer.get("charging_schedule")
        if sched and sched.get("enabled"):
            return consumer
    return None


def _scenario_to_battery_params(scenario_params: dict) -> dict | list[dict]:
    """Übersetzt JSON-Szenario-Parameter in das Format des Optimizers.

    Multi-ESS (2.7.c): when ``_planning_batteries`` has 2+ entries, return a list
    so SE/MILP/chart SoC keep per-battery identity. Singular scenarios stay a dict.
    """
    from house_config.battery_control import DEFAULT_BATTERY_CONTROL, control_from_battery_params
    from house_config.entity_resolution import (
        battery_params_from_planning,
        split_battery_max_power_kw,
    )

    planning = scenario_params.get("_planning_batteries")
    planning_list = (
        [entry for entry in planning if isinstance(entry, dict)]
        if isinstance(planning, list)
        else []
    )
    if len(planning_list) >= 2:
        return [battery_params_from_planning(entry) for entry in planning_list]
    if len(planning_list) == 1:
        return battery_params_from_planning(planning_list[0])

    control_raw = scenario_params.get("battery_control", scenario_params.get("control"))
    charge_kw, discharge_kw = split_battery_max_power_kw(scenario_params)
    # Inline flat scenarios without planning entries: treat battery_efficiency
    # as full path η (no separate η_inv available).
    return {
        "battery_capacity_kwh": float(scenario_params["battery_capacity_kwh"]),
        "min_soc": float(scenario_params["battery_min_soc"]),
        "max_soc": float(scenario_params["battery_max_soc"]),
        "max_charge_power_kw": charge_kw,
        "max_discharge_power_kw": discharge_kw,
        "max_power_kw": max(charge_kw, discharge_kw),
        "efficiency": float(scenario_params["battery_efficiency"]),
        "standby_power_kw": max(
            0.0, float(scenario_params.get("standby_power_kw") or 0.0)
        ),
        "control": control_from_battery_params(
            {"control": control_raw or DEFAULT_BATTERY_CONTROL}
        ),
        "limits_from_live": bool(scenario_params.get("limits_from_live", False)),
    }


def _brutto_prices_for_slots(
    prices_df: pd.DataFrame,
    slot_datetimes: list[datetime],
    *,
    scenario_params: dict | None = None,
) -> list[float]:
    from data.backtesting_prices import import_brutto_cent_for_slots, pricing_kwargs_from_resolved

    epex = epex_prices_for_slots(prices_df, slot_datetimes)
    return import_brutto_cent_for_slots(
        [float(p) for p in epex],
        slot_datetimes,
        **pricing_kwargs_from_resolved(scenario_params),
    )


def _consumption_kw_columns_from_chart_rows(
    chart_rows: list[dict],
    flexible_consumers: list,
) -> dict[str, list[float]]:
    """Extrahiert optimierte Stundenleistungen (Basislast + Flex je ID) aus Chart-Zeilen.

    Fixed load (native filter run, continuous loads) sits inside
    ``Verbrauch-Prognose`` (see ``simulation.matrix_builder.fixed_load_kw_by_slot``);
    it is booked on the consumer's column, not as Grundlast.
    """
    from optimizer.fixed_load import fixed_load_kw_at, resolve_fixed_load_windows
    from optimizer.simulation import flexible_consumer_power_kw
    from optimizer.targets import consumer_column_name

    flex_keys = [f"{consumer['id']}_kw" for consumer in flexible_consumers]
    columns: dict[str, list[float]] = {
        "consumption_kw": [],
        "baseload_kw": [],
        **{key: [] for key in flex_keys},
    }
    native_windows = resolve_fixed_load_windows(flexible_consumers)
    for row in chart_rows:
        prognose = float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
        native = (
            fixed_load_kw_at(native_windows, row["slot_datetime"])
            if native_windows
            else {}
        )
        native_sum = sum(native.values())
        if native_sum > prognose + 1e-6:
            raise ValueError(
                f"Slot {row.get('slot_datetime')}: Verbrauch-Prognose {prognose:.3f} kW "
                f"enthält die feste Last ({native_sum:.3f} kW: nativer Filterlauf / "
                "Dauerlast) nicht."
            )
        baseload = prognose - native_sum
        columns["baseload_kw"].append(round(baseload, 4))
        for consumer in flexible_consumers:
            col = consumer_column_name(consumer)
            key = f"{consumer['id']}_kw"
            columns[key].append(
                round(
                    float(row.get(col, 0.0) or 0.0)
                    + native.get(str(consumer["id"]), 0.0),
                    4,
                )
            )
        columns["consumption_kw"].append(
            round(prognose + flexible_consumer_power_kw(row), 4)
        )
    return columns


def scenario_standby_power_kw(scenario_params: dict) -> float:
    """Battery AC standby (kW) the MILP adds to every slot's Verbrauch-Prognose."""
    battery_params = _scenario_to_battery_params(scenario_params)
    if isinstance(battery_params, list):
        return float(
            sum(max(0.0, float(b.get("standby_power_kw") or 0.0)) for b in battery_params)
        )
    return max(0.0, float(battery_params.get("standby_power_kw") or 0.0))


def _critical_snapshot_kind(
    plausibility_ok: bool,
    new_cbc_events: list[dict],
) -> str:
    if not plausibility_ok:
        return "consumption_tolerance"
    if new_cbc_events:
        return str(new_cbc_events[-1].get("event", "cbc_unknown"))
    return "unknown"

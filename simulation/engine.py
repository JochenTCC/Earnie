# simulation_engine.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd
import config
from data import profile_manager
from data import feed_in_prices
from data.backtesting_prices import BacktestingPriceResources, matrix_prices_from_context
from data.planning_window import normalize_hour_slot
from data.market_prices import epex_prices_for_slots
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h, wall_hours_from_slots
from optimizer import (
    simulate_horizon,
    horizon_end_soc_from_chart_rows,
    horizon_end_soc_percent,
    _calculate_step_cost_parts_from_row,
    _delivered_flex_kwh_from_rows,
    _total_consumption_kwh_from_rows,
)
from optimizer.targets import consumer_column_name
from simulation.baseload_validation import (
    baseload_kwh_from_chart_rows,
    derive_historical_baseload_kwh,
    resolve_hourly_baseload_kw,
)
from simulation.backtesting_horizon import (
    compute_sunrise_planning_at_anchor,
    effective_sunrise_soc_min_index,
    geo_params_from_scenario,
    naive_backtesting_slot,
    overlay_step_consumption_on_matrix,
    resolve_sunrise_book_step_for_scenario,
    step_slot_datetimes,
    truncate_matrix_for_step_simulation,
    window_start_before_anchor,
)
from simulation.horizon_mode import (
    BACKTESTING_STEP_HOURS,
    DEFAULT_HORIZON_MODE,
    FIXED_24H,
    SUNRISE_WINDOW,
    parse_horizon_mode,
)
from optimizer.cbc_solver import (
    reset_cbc_gap_rel_override,
    reset_cbc_strict_time_limit_override,
    reset_milp_solver_override,
    set_cbc_gap_rel_override,
    set_cbc_strict_time_limit_override,
    set_milp_solver_override,
)
from optimizer.cbc_events import (
    begin_cbc_event_collection,
    clear_cbc_milp_context,
    count_cbc_events,
    list_cbc_events,
    set_cbc_milp_context,
    take_cbc_events,
)
from simulation.backtesting_snapshots import build_window_snapshot


from simulation.historical_cache import HistoricalDataCache, _hour_hold_reindex
from simulation.matrix_builder import (
    build_historical_matrix_for_slots,
    build_historical_window_matrix,
    build_sunrise_window_matrix,
    collect_imported_pv_scenario_meta,
    scenario_uses_imported_pv,
    _imported_pv_kw_for_slots,
)
from simulation.reference_costs import (
    HISTORICAL_REFERENCE_ID,
    SCENARIO_REFERENCE_PREFIX,
    build_per_scenario_reference_costs,
    compute_historical_reference_costs,
    default_own_reference,
    is_scenario_reference_id,
    plan_per_scenario_reference_tasks,
    resolve_reference_hourly_load,
    scenario_reference_id,
    scenario_reference_label,
    _ensure_live_ref_spec,
)
from simulation.plausibility import (
    CONSUMPTION_TOLERANCE_KWH,
    CONSUMPTION_TOLERANCE_REL,
    PlausibilityReport,
    PlausibilityResult,
    print_plausibility_report,
    validate_window_consumption,
    _consumption_within_tolerance,
    _plausibility_reference_values,
    _standby_kwh_in_rows,
)
from simulation.anchor_step import (
    _apply_backtesting_step,
    _hour_cost_parts_without_optimization,
    _hour_cost_without_optimization,
    _merge_foresight_flex_into_series,
    _simulate_anchor_step,
    _stash_sunrise_full_horizon_flex,
)

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


def _ready_hour_for_date(target_date: date) -> int:
    """ready_by_hour am Fenster-Ende (Wochentag/Wochenende des Abfahrtstags)."""
    consumer = _charging_schedule_consumer()
    if not consumer:
        return 0
    sched = consumer["charging_schedule"]
    day_key = "weekend" if target_date.weekday() >= 5 else "weekday"
    day_sched = sched.get(day_key, {})
    return int(day_sched.get("ready_by_hour", 0)) % 24


def window_anchor_for_date(target_date: date) -> datetime:
    """
    Endzeitpunkt des 24h-Optimierungsfensters.
    Mit E-Auto-Ladeplan: ready_by_hour am Abfahrtstag (z. B. 07:00).
    Ohne Ladeplan: Mitternacht des Folgetags (= Kalendertag 00–23 Uhr).
    """
    if _charging_schedule_consumer():
        ready_h = _ready_hour_for_date(target_date)
        return datetime.combine(target_date, time(hour=ready_h))
    return datetime.combine(target_date + timedelta(days=1), time(0))


def window_slot_datetimes(anchor: datetime) -> list[datetime]:
    """24 wall-clock hours before anchor as QH slots (anchor exclusive)."""
    from optimizer.slot_duration import DEFAULT_DT_H, slots_for_wall_hours

    start = anchor - timedelta(hours=24)
    n = slots_for_wall_hours(24.0, DEFAULT_DT_H)
    step = timedelta(hours=DEFAULT_DT_H)
    return [start + step * i for i in range(n)]


def _scenario_to_battery_params(scenario_params: dict) -> dict:
    """Übersetzt JSON-Szenario-Parameter in das Format des Optimizers."""
    return {
        "battery_capacity_kwh": float(scenario_params["battery_capacity_kwh"]),
        "min_soc": float(scenario_params["battery_min_soc"]),
        "max_soc": float(scenario_params["battery_max_soc"]),
        "max_power_kw": float(scenario_params["battery_max_power_kw"]),
        "efficiency": float(scenario_params["battery_efficiency"]),
        "standby_power_kw": max(
            0.0, float(scenario_params.get("standby_power_kw") or 0.0)
        ),
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


def list_simulation_anchors(
    start: pd.Timestamp,
    end: pd.Timestamp,
    cache: HistoricalDataCache,
) -> list[datetime]:
    """Fertigstellungs-Anker im Simulationszeitraum (je Kalendertag ein 24h-Fenster)."""
    cache.load()
    anchors: list[datetime] = []
    for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
        anchor = window_anchor_for_date(day.date())
        slots = window_slot_datetimes(anchor)
        _, _, total_load, _ = cache.get_window_consumption(slots)
        if sum(total_load) <= 0:
            continue
        anchors.append(anchor)
    return anchors


def _consumption_kw_columns_from_chart_rows(
    chart_rows: list[dict],
    flexible_consumers: list,
) -> dict[str, list[float]]:
    """Extrahiert optimierte Stundenleistungen (Basislast + Flex je ID) aus Chart-Zeilen."""
    from optimizer.simulation import flexible_consumer_power_kw
    from optimizer.targets import consumer_column_name

    flex_keys = [f"{consumer['id']}_kw" for consumer in flexible_consumers]
    columns: dict[str, list[float]] = {
        "consumption_kw": [],
        "baseload_kw": [],
        **{key: [] for key in flex_keys},
    }
    for row in chart_rows:
        baseload = float(row.get("Verbrauch-Prognose (kW)", 0.0) or 0.0)
        columns["baseload_kw"].append(round(baseload, 4))
        for consumer in flexible_consumers:
            col = consumer_column_name(consumer)
            key = f"{consumer['id']}_kw"
            columns[key].append(round(float(row.get(col, 0.0) or 0.0), 4))
        columns["consumption_kw"].append(
            round(baseload + flexible_consumer_power_kw(row), 4)
        )
    return columns


def _critical_snapshot_kind(
    plausibility_ok: bool,
    new_cbc_events: list[dict],
) -> str:
    if not plausibility_ok:
        return "consumption_tolerance"
    if new_cbc_events:
        return str(new_cbc_events[-1].get("event", "cbc_unknown"))
    return "unknown"


def run_simulation(
    start: pd.Timestamp,
    end: pd.Timestamp,
    scenario_params: dict,
    prices_df: pd.DataFrame,
    cache: HistoricalDataCache | None = None,
    initial_soc: float = 50.0,
    on_progress=None,
    scenario_id: str | None = None,
    horizon_mode: str = DEFAULT_HORIZON_MODE,
    price_resources: BacktestingPriceResources | None = None,
    snapshot_collector: list[dict] | None = None,
) -> tuple[pd.DataFrame, PlausibilityReport, list[dict]]:
    """
    Simuliert historische Verbrauchsdaten mit Flex-Optimierung.

    horizon_mode:
      - fixed_24h: [Anker−24h, Anker), SOC frei am Fensterende (E-Auto-Anker)
      - sunrise_window: MILP SA_0-->SA_2, SOC_min am Sonnenaufgang; Output weiter 24h/Schritt
    """
    horizon_mode = parse_horizon_mode(horizon_mode)
    if horizon_mode == SUNRISE_WINDOW:
        geo_params_from_scenario(scenario_params)

    cache = cache or HistoricalDataCache()
    cache.load()

    anchors = list_simulation_anchors(start, end, cache)
    if not anchors:
        raise ValueError(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )

    battery_params = _scenario_to_battery_params(scenario_params)
    flexible_consumers = _flexible_consumers_from_scenario(scenario_params)
    feed_in_settings = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)
    gap_token = set_cbc_gap_rel_override(config.get_backtesting_cbc_gap_rel())
    limit_token = set_cbc_strict_time_limit_override(
        config.get_backtesting_cbc_strict_time_limit_sec()
    )
    solver_token = set_milp_solver_override(config.get_backtesting_milp_solver())
    if horizon_mode == SUNRISE_WINDOW:
        total_hours = wall_hours_from_slots(
            sum(
                resolve_sunrise_book_step_for_scenario(
                    anchor, scenario_params
                ).book_hours
                for anchor in anchors
            )
        )
    else:
        total_hours = len(anchors) * BACKTESTING_STEP_HOURS
    hours_done = 0
    sim_soc = initial_soc

    all_chart_rows: list[dict] = []
    all_timestamps: list[datetime] = []
    plausibility = PlausibilityReport()
    collect_cbc = scenario_id is not None
    if collect_cbc:
        begin_cbc_event_collection()
        set_cbc_milp_context(scenario_id=scenario_id)

    collect_snapshots = snapshot_collector is not None and scenario_id is not None

    try:
        for anchor in anchors:
            if collect_cbc:
                set_cbc_milp_context(
                    window_anchor=pd.Timestamp(anchor).isoformat(),
                )
            window_initial_soc = sim_soc
            events_before = count_cbc_events() if collect_cbc else 0
            (
                chart_rows,
                matrix,
                meta,
                sim_soc,
                chart_rows_full,
                matrix_full,
                sunrise_soc_min_index,
            ) = _simulate_anchor_step(
                anchor,
                sim_soc,
                horizon_mode=horizon_mode,
                cache=cache,
                prices_df=prices_df,
                scenario_params=scenario_params,
                battery_params=battery_params,
                feed_in_settings=feed_in_settings,
                hours_done=hours_done,
                collect_cbc=collect_cbc,
                price_resources=price_resources,
                collect_full_horizon=collect_snapshots,
            )
            if collect_cbc:
                set_cbc_milp_context(
                    consumer_targets_kwh=dict(meta["consumer_daily_targets_kwh"]),
                )
            meta["standby_power_kw"] = float(
                battery_params.get("standby_power_kw") or 0.0
            )
            plausibility_result = validate_window_consumption(chart_rows, meta)
            plausibility.add(plausibility_result)

            if snapshot_collector is not None and scenario_id is not None:
                events_after = count_cbc_events() if collect_cbc else 0
                new_cbc_events = (
                    list_cbc_events()[events_before:events_after]
                    if collect_cbc and events_after > events_before
                    else []
                )
                is_critical = (not plausibility_result.ok) or bool(new_cbc_events)
                if is_critical:
                    snapshot_collector.append(
                        build_window_snapshot(
                            window_anchor=anchor,
                            scenario_id=scenario_id,
                            horizon_mode=horizon_mode,
                            kind=_critical_snapshot_kind(
                                plausibility_result.ok,
                                new_cbc_events,
                            ),
                            initial_soc=window_initial_soc,
                            meta=meta,
                            chart_rows_24h=chart_rows,
                            matrix_24h=matrix,
                            chart_rows_full=chart_rows_full,
                            matrix_full=matrix_full,
                            sunrise_soc_min_index=sunrise_soc_min_index,
                            scenario_params=scenario_params,
                            battery_params=battery_params,
                        )
                    )

            foresight_flex = list(meta.pop("foresight_flex_rows", []) or [])
            if foresight_flex:
                _merge_foresight_flex_into_series(
                    all_chart_rows, all_timestamps, foresight_flex
                )
            all_chart_rows.extend(chart_rows)
            all_timestamps.extend(row["slot_datetime"] for row in matrix)

            hours_done += len(chart_rows)
            if on_progress is not None:
                on_progress(wall_hours_from_slots(hours_done), total_hours)
    finally:
        reset_cbc_gap_rel_override(gap_token)
        reset_cbc_strict_time_limit_override(limit_token)
        reset_milp_solver_override(solver_token)
        if collect_cbc:
            clear_cbc_milp_context()

    consumption_columns = _consumption_kw_columns_from_chart_rows(
        all_chart_rows,
        flexible_consumers,
    )
    cost_parts = [
        _calculate_step_cost_parts_from_row(row) for row in all_chart_rows
    ]
    df_res = pd.DataFrame(
        {
            **consumption_columns,
            "sim_cost": [parts[2] for parts in cost_parts],
            "import_cost_eur": [parts[0] for parts in cost_parts],
            "export_earn_eur": [parts[1] for parts in cost_parts],
            "import_kwh": [parts[3] for parts in cost_parts],
            "export_kwh": [parts[4] for parts in cost_parts],
            "k_act": [
                float(row["Strompreis (Cent/kWh)"]) for row in all_chart_rows
            ],
            "k_push_act": [
                float(row["Einspeisevergütung (Cent/kWh)"])
                if "Einspeisevergütung (Cent/kWh)" in row
                else float("nan")
                for row in all_chart_rows
            ],
            "sim_soc": [row["Simulierter SoC (%)"] for row in all_chart_rows],
            "batt_action_kw": [row["Geplante Batterie-Aktion (kW)"] for row in all_chart_rows],
            "steuerbefehl": [row["Steuerbefehl"] for row in all_chart_rows],
        },
        index=pd.DatetimeIndex(all_timestamps),
    )
    df_res.index.name = "ts"
    cbc_events = take_cbc_events() if collect_cbc else []
    return df_res, plausibility, cbc_events


# Re-Exports für API-Stabilität (from simulation.engine import ...)
__all__ = [
    "CONSUMPTION_TOLERANCE_KWH",
    "CONSUMPTION_TOLERANCE_REL",
    "HISTORICAL_REFERENCE_ID",
    "HistoricalDataCache",
    "PlausibilityReport",
    "PlausibilityResult",
    "SCENARIO_REFERENCE_PREFIX",
    "_apply_backtesting_step",
    "_brutto_prices_for_slots",
    "_charging_schedule_consumer",
    "_consumption_kw_columns_from_chart_rows",
    "_consumption_within_tolerance",
    "_critical_snapshot_kind",
    "_ensure_live_ref_spec",
    "_flexible_consumers_from_scenario",
    "_hour_cost_parts_without_optimization",
    "_hour_cost_without_optimization",
    "_hour_hold_reindex",
    "_imported_pv_kw_for_slots",
    "_merge_foresight_flex_into_series",
    "_plausibility_reference_values",
    "_pricing_kwargs_from_scenario",
    "_ready_hour_for_date",
    "_scenario_to_battery_params",
    "_simulate_anchor_step",
    "_standby_kwh_in_rows",
    "_stash_sunrise_full_horizon_flex",
    "build_historical_matrix_for_slots",
    "build_historical_window_matrix",
    "build_per_scenario_reference_costs",
    "build_sunrise_window_matrix",
    "collect_imported_pv_scenario_meta",
    "compute_historical_reference_costs",
    "default_own_reference",
    "flex_consumers_for_backtesting_scenario",
    "flex_consumers_from_snapshot",
    "is_scenario_reference_id",
    "list_simulation_anchors",
    "plan_per_scenario_reference_tasks",
    "print_plausibility_report",
    "resolve_reference_hourly_load",
    "resolved_flexible_consumers",
    "run_simulation",
    "scenario_reference_id",
    "scenario_reference_label",
    "scenario_uses_imported_pv",
    "validate_window_consumption",
    "window_anchor_for_date",
    "window_slot_datetimes",
]

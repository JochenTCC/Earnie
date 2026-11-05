"""SE reference ladder: L1 = battery in vendor mode, flex at real timing, one SoC chain.

Spec: ``docs/dev/rule-based-reference.md`` §§ 2, 3, 4.1. L1 runs on the windows, targets
and flex windows of the optimized run and always books actual prices.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from optimizer.charging_schedule import contexts_within_book
from optimizer.milp_consumer_delivery import consumer_delivery_eligible_indices
from optimizer.scenario_planning_scope import planning_scenario_scope
from optimizer.sim_baseline import (
    _baseline_battery_params,
    _simulate_single_hour_baseline,
    build_shaped_flex_kw_per_slot,
)
from optimizer.sim_chart_rows import COL_EINSPEISEVERGUETUNG
from optimizer.sim_costs import calculate_step_cost_parts_from_row
from optimizer.sim_horizon_types import _HorizonOptions
from optimizer.thermal_flex_context import (
    consumer_thermal_eligible_indices,
    is_heating_rod_consumer,
    is_thermal_flex_consumer,
)
from simulation.historical_cache import HistoricalDataCache
from simulation.horizon_mode import SUNRISE_WINDOW, parse_horizon_mode
from simulation.plausibility import PlausibilityReport, validate_window_consumption
from simulation.reference_costs import _REFERENCE_COST_COLUMNS, _empty_reference_series

L1_STEUERBEFEHL = "Referenz L1"


@dataclass(frozen=True)
class LadderReferenceResult:
    """One ladder step over the period.

    ``frame``: ``_REFERENCE_COST_COLUMNS`` plus ``sim_soc`` (start of slot). ``end_soc``: SoC
    after the last slot. ``no_shape_windows``: per consumer, the windows without a shape.
    """

    frame: pd.DataFrame
    plausibility: PlausibilityReport
    end_soc: float
    no_shape_windows: dict[str, int]


@dataclass(frozen=True)
class _ShapeSource:
    """Where a run reads consumer shapes from, resolved once per run."""

    cache: HistoricalDataCache
    profile_consumers: dict[str, dict]
    climate: object | None


def _shape_source(cache: HistoricalDataCache, scenario_params: dict) -> _ShapeSource:
    from data.modeled_climate import ModeledClimateContext
    from house_config.planning_flex_bridge import PROFILE_SPEC, resolve_consumption_source

    if resolve_consumption_source(scenario_params) != PROFILE_SPEC:
        return _ShapeSource(cache, {}, None)
    profile = scenario_params["_house_profile"]
    return _ShapeSource(
        cache,
        {str(c["id"]): c for c in profile.get("consumers", []) if c.get("id")},
        ModeledClimateContext.from_scenario(scenario_params),
    )


def reference_flex_shapes_kw(
    slot_datetimes: list[datetime],
    consumers: list[dict],
    source: _ShapeSource,
) -> dict[str, list[float]]:
    """Real timing per consumer: the profile model (source of the L0 load), else cons_data."""
    from data.consumption_profiles import modeled_consumer_kw_for_slots

    shapes: dict[str, list[float]] = {}
    from_cons_data: list[str] = []
    for consumer in consumers:
        cid = str(consumer["id"])
        profile_consumer = source.profile_consumers.get(cid)
        if profile_consumer is not None:
            shapes[cid] = modeled_consumer_kw_for_slots(
                profile_consumer, slot_datetimes, climate=source.climate
            )
        else:
            from_cons_data.append(cid)
    if from_cons_data:
        shapes.update(source.cache.get_consumer_kw_for_slots(slot_datetimes, from_cons_data))
    return shapes


def _eligible_slots(setup, consumer: dict, book_indices: list[int]) -> list[int]:
    """The consumer's flex slots inside the book: the same windows as the MILP."""
    matrix = setup.matrix
    contexts = contexts_within_book(setup.charging_contexts or {}, book_indices)
    cid = consumer["id"]
    _, eligible = consumer_delivery_eligible_indices(
        matrix,
        len(matrix),
        consumer,
        book_indices,
        contexts.get(cid),
        (setup.filters or {}).get(cid),
    )
    if is_thermal_flex_consumer(consumer):
        return consumer_thermal_eligible_indices(matrix, consumer, eligible)
    return eligible


def _book_indices(plan) -> list[int]:
    if plan.flex_book_hours is None:
        return list(range(len(plan.matrix)))
    return list(range(plan.flex_book_start, plan.flex_book_start + plan.flex_book_hours))


def _window_rows(
    anchor: datetime,
    sim_soc: float,
    *,
    scenario_params: dict,
    consumers: list[dict],
    battery_params: dict | list[dict],
    feed_in_settings,
    prices_df: pd.DataFrame,
    horizon_mode: str,
    shape_source: _ShapeSource,
) -> tuple[list[dict], dict, float, list[str]]:
    """One window: ``(book chart rows, meta, end SoC, consumers without a shape)``."""
    from optimizer.simulation import _prepare_horizon_state
    from simulation.anchor_step import _build_anchor_window_plan

    with planning_scenario_scope(scenario_params):
        plan = _build_anchor_window_plan(
            anchor,
            sim_soc,
            horizon_mode=horizon_mode,
            cache=shape_source.cache,
            prices_df=prices_df,
            scenario_params=scenario_params,
            feed_in_settings=feed_in_settings,
            price_resources=None,
        )
        # The MILP's own preparation: its targets (fixed load credited) and flex windows.
        setup = _prepare_horizon_state(
            plan.matrix,
            sim_soc,
            _HorizonOptions(
                k_push=None,
                verbose=False,
                commit_hours=1,
                flex_book_hours=plan.flex_book_hours,
                flex_book_start=plan.flex_book_start,
                sunrise_soc_min_index=None,
                soc_hold_index=None,
                soc_hold_percent=None,
            ),
            battery_params=battery_params,
            consumer_daily_targets_kwh=plan.meta["consumer_daily_targets_kwh"],
            charging_contexts=None,
            filter_contexts=None,
            matrix_prepared=False,
            disable_horizon_soc_anchor=True,
            flexible_consumers=consumers,
        )
        book = _book_indices(plan)
        planned = [c for c in consumers if not is_heating_rod_consumer(c)]
        shaped = build_shaped_flex_kw_per_slot(
            len(setup.matrix),
            planned,
            setup.horizon_limits,
            reference_flex_shapes_kw(
                [row["slot_datetime"] for row in setup.matrix], planned, shape_source
            ),
            {c["id"]: _eligible_slots(setup, c, book) for c in planned},
        )
        battery = _baseline_battery_params(battery_params)
        rows: list[dict] = []
        soc = float(sim_soc)
        for t in book:
            flex_kw = {str(c["id"]): 0.0 for c in consumers} | shaped.per_slot[t]
            soc, row = _simulate_single_hour_baseline(
                setup.matrix[t],
                soc,
                battery,
                flex_kw_override=flex_kw,
                steuerbefehl=L1_STEUERBEFEHL,
                consumers=consumers,
            )
            rows.append(row)
    return rows, plan.meta, soc, shaped.no_shape_ids


def compute_l1_reference_costs(
    start: pd.Timestamp,
    end: pd.Timestamp,
    scenario_params: dict,
    prices_df: pd.DataFrame,
    cache: HistoricalDataCache,
    *,
    initial_soc: float,
    horizon_mode: str,
) -> LadderReferenceResult:
    """L1 over the period, same anchors and same start SoC as the optimized run."""
    import config
    from simulation.engine import (
        list_simulation_anchors,
        list_sunrise_step_anchors,
    )
    from simulation.engine_scenario import (
        _flexible_consumers_from_scenario,
        _scenario_to_battery_params,
        scenario_standby_power_kw,
    )

    horizon_mode = parse_horizon_mode(horizon_mode)
    cache.load()
    anchors = (
        list_sunrise_step_anchors(start, end, cache, scenario_params)
        if horizon_mode == SUNRISE_WINDOW
        else list_simulation_anchors(start, end, cache)
    )
    if not anchors:
        raise ValueError(
            f"Keine historischen Verbrauchsfenster zwischen {start.date()} und {end.date()}."
        )
    consumers = _flexible_consumers_from_scenario(scenario_params)
    battery_params = _scenario_to_battery_params(scenario_params)
    feed_in_settings = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)
    standby_kw = scenario_standby_power_kw(scenario_params)
    shape_source = _shape_source(cache, scenario_params)

    series = _empty_reference_series()
    series["sim_soc"] = []
    timestamps: list[datetime] = []
    plausibility = PlausibilityReport()
    no_shape_windows: dict[str, int] = {}
    soc = float(initial_soc)
    for anchor in anchors:
        rows, meta, soc, no_shape_ids = _window_rows(
            anchor,
            soc,
            scenario_params=scenario_params,
            consumers=consumers,
            battery_params=battery_params,
            feed_in_settings=feed_in_settings,
            prices_df=prices_df,
            horizon_mode=horizon_mode,
            shape_source=shape_source,
        )
        meta["standby_power_kw"] = standby_kw
        meta["reference_no_shape_consumers"] = no_shape_ids
        plausibility.add(validate_window_consumption(rows, meta))
        for cid in no_shape_ids:
            no_shape_windows[cid] = no_shape_windows.get(cid, 0) + 1
        for row in rows:
            _append_l1_slot(series, row)
            timestamps.append(row["slot_datetime"])

    frame = pd.DataFrame(
        {name: series[name] for name in (*_REFERENCE_COST_COLUMNS, "sim_soc")},
        index=pd.DatetimeIndex(timestamps),
    )
    frame.index.name = "ts"
    return LadderReferenceResult(frame, plausibility, soc, no_shape_windows)


def _append_l1_slot(series: dict[str, list[float]], row: dict) -> None:
    from optimizer.sim_chart_rows import flexible_consumer_power_kw

    import_eur, export_eur, net_eur, import_kwh, export_kwh = (
        calculate_step_cost_parts_from_row(row)
    )
    series["sim_cost"].append(net_eur)
    series["import_cost_eur"].append(import_eur)
    series["export_earn_eur"].append(export_eur)
    series["import_kwh"].append(import_kwh)
    series["export_kwh"].append(export_kwh)
    series["consumption_kw"].append(
        float(row["Verbrauch-Prognose (kW)"]) + flexible_consumer_power_kw(row)
    )
    series["k_act"].append(float(row["Strompreis (Cent/kWh)"]))
    series["k_push_act"].append(float(row[COL_EINSPEISEVERGUETUNG]))
    series["sim_soc"].append(float(row["Simulierter SoC (%)"]))


def ladder_reference_fingerprint(scenario_params: dict) -> tuple:
    """Sharing key of L1 / L2 runs: L0's key plus the house, the battery and the flex consumers.

    L0 ignores storage and flex, so ``reference_fingerprint`` stays as it is; L1 and L2
    depend on them and may only be shared between identical setups.
    """
    from house_config.planning_flex_bridge import reference_fingerprint
    from simulation.engine_scenario import (
        _flexible_consumers_from_scenario,
        _scenario_to_battery_params,
    )

    def canonical(value) -> str:
        return json.dumps(value, sort_keys=True, default=str)

    return (
        reference_fingerprint(scenario_params),
        canonical(scenario_params.get("_house_profile")),
        canonical(_scenario_to_battery_params(scenario_params)),
        canonical(_flexible_consumers_from_scenario(scenario_params)),
    )

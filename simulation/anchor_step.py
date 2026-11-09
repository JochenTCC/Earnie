"""Per-anchor backtesting simulation step helpers."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import config
from data import feed_in_prices
from data.backtesting_prices import BacktestingPriceResources
from house_config.import_cap import parse_import_cap
from optimizer import (
    horizon_end_soc_from_chart_rows,
    horizon_end_soc_percent,
    _delivered_flex_kwh_from_rows,
)
from optimizer.hp_store import HP_STORE_CONTEXT_KEY, HP_STORE_START_KEY, next_hp_level_kwh
from optimizer.import_power_limit import ImportCaps, import_caps_from_params
from optimizer.milp_inputs import _resolve_thermal_flex_contexts
from optimizer.rod_store import ROD_STORE_START_KEY, STORE_BALANCE_CONTEXT_KEY, next_level_kwh
from optimizer.scenario_planning_scope import planning_scenario_scope
from optimizer.sim_costs import _grid_kw_from_row
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h
from optimizer.targets import consumer_column_name
from optimizer.thermal_flex_context import is_heating_rod_consumer, is_thermal_flex_consumer
from simulation.backtesting_horizon import naive_backtesting_slot
from simulation.historical_cache import HistoricalDataCache
from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW
from simulation.matrix_builder import (
    build_historical_window_matrix,
    build_sunrise_window_matrix,
)


def _flexible_consumers_from_scenario(scenario_params: dict | None) -> list:
    from simulation.engine import _flexible_consumers_from_scenario as _impl

    return _impl(scenario_params)


def _simulate_horizon(*args, **kwargs):
    """Resolve via engine facade so tests can patch ``simulation.engine.simulate_horizon``."""
    from simulation import engine as eng

    return eng.simulate_horizon(*args, **kwargs)


def _apply_backtesting_step(
    chart_rows: list[dict],
    matrix: list[dict],
    meta: dict,
    *,
    horizon_mode: str,
) -> tuple[list[dict], list[dict]]:
    """Schneidet Chart-Zeilen auf den gebuchten Sunrise-/fixed-Schritt zu."""
    if horizon_mode == FIXED_24H:
        return chart_rows, matrix
    raw_slots = meta.get("step_slot_datetimes", [])
    step_slots = {naive_backtesting_slot(slot) for slot in raw_slots}
    if not step_slots:
        raise ValueError("Sunset-Backtesting: step_slot_datetimes fehlen in meta.")

    indices = [
        index
        for index, row in enumerate(matrix)
        if naive_backtesting_slot(row["slot_datetime"]) in step_slots
    ]
    if len(indices) != len(step_slots):
        raise ValueError(
            f"Sunrise-Schritt: erwartet {len(step_slots)} Slots, gefunden {len(indices)}."
        )
    return [chart_rows[i] for i in indices], [matrix[i] for i in indices]


_UNBOOKED_FLEX_TOLERANCE_KW = 1e-6


def _stash_sunrise_full_horizon_flex(
    meta: dict,
    full_chart_rows: list[dict],
    flexible_consumers: list,
) -> None:
    """
    Stash full-horizon flex for plausibility; fail loud on flex outside the book.

    The MILP binds every flex consumer to the book [SA₁, SA₂) (explicit
    ``flex_indices``), so the SA₀→SA₁ part and the trailing SA₂ slot carry no
    flex. Energy there would never reach the booked series.
    """
    from simulation.plausibility import plausibility_flex_kwh

    delivered = plausibility_flex_kwh(
        _delivered_flex_kwh_from_rows(full_chart_rows, flexible_consumers=flexible_consumers),
        flexible_consumers,
    )
    meta["plausibility_optimized_flex_kwh"] = round(
        sum(float(v) for v in delivered.values()), 3
    )
    book = {naive_backtesting_slot(slot) for slot in meta["step_slot_datetimes"]}
    unbooked: list[str] = []
    for row in full_chart_rows:
        slot = naive_backtesting_slot(row["slot_datetime"])
        if slot in book:
            continue
        for consumer in flexible_consumers:
            column = consumer_column_name(consumer)
            power = float(row.get(column, 0.0) or 0.0)
            if power > _UNBOOKED_FLEX_TOLERANCE_KW:
                unbooked.append(f"{slot.isoformat()} {column}={power:g}")
    if unbooked:
        raise ValueError(
            f"Sunrise-Fenster ready_by {meta['ready_by']}: Flex außerhalb des "
            f"Buchungsfensters [{meta['sa1']}, {meta['sa2']}) geplant: "
            + ", ".join(unbooked[:5])
            + ("…" if len(unbooked) > 5 else "")
        )


@dataclass
class _AnchorWindowPlan:
    """Fenster-Matrix plus MILP-Anker- und Book-Parameter eines Backtesting-Schritts."""

    matrix: list[dict]
    meta: dict
    matrix_full: list[dict] | None
    sunrise_soc_min_index: int | None
    disable_soc_anchor: bool
    soc_hold_index: int | None
    soc_hold_percent: float | None
    flex_book_hours: int | None
    flex_book_start: int
    commit_hours: int | None


def _build_anchor_window_plan(
    anchor: datetime,
    step_start_soc: float,
    *,
    horizon_mode: str,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
    feed_in_settings: feed_in_prices.FeedInSettings,
    price_resources: BacktestingPriceResources | None,
) -> _AnchorWindowPlan:
    """Fenstermatrix und Ankerparameter für fixed_24h bzw. sunrise_window."""
    disable_soc_anchor = config.get_backtesting_disable_horizon_soc_anchor()
    commit_hours = config.get_backtesting_commit_hours()
    if horizon_mode != SUNRISE_WINDOW:
        matrix, meta = build_historical_window_matrix(
            anchor,
            cache,
            prices_df,
            feed_in_settings=feed_in_settings,
            scenario_params=scenario_params,
        )
        return _AnchorWindowPlan(
            matrix=matrix,
            meta=meta,
            matrix_full=None,
            sunrise_soc_min_index=None,
            disable_soc_anchor=disable_soc_anchor,
            soc_hold_index=None,
            soc_hold_percent=None,
            flex_book_hours=None,
            flex_book_start=0,
            commit_hours=commit_hours,
        )
    book_matrix, meta, sa1_index, matrix_full = build_sunrise_window_matrix(
        anchor,
        cache,
        prices_df,
        scenario_params,
        feed_in_settings,
        price_resources=price_resources,
    )
    matrix = list(matrix_full)
    # Product path: full SA₀→SA₂ MILP, book [SA₁, SA₂), SoC hold at SA₁ start.
    # Initial SoC at SA₀: use carry-in (equality at SA₁ keeps night net-neutral).
    soc_hold_index = int(sa1_index) - 1 if sa1_index > 0 else None
    return _AnchorWindowPlan(
        matrix=matrix,
        meta=meta,
        matrix_full=matrix_full,
        sunrise_soc_min_index=None,
        disable_soc_anchor=True,
        soc_hold_index=soc_hold_index,
        soc_hold_percent=step_start_soc if soc_hold_index is not None else None,
        flex_book_hours=int(meta["book_hours"]),
        flex_book_start=int(sa1_index),
        commit_hours=len(matrix),
    )


def _sunrise_book_end_soc(full_chart_rows: list[dict], meta: dict) -> float:
    """SoC at SA₂: start SoC of the MILP slot right after the book.

    Chart rows carry their start-of-slot SoC; chaining the last book row would
    drop the battery action of the last book slot in every window.
    """
    from optimizer.slot_duration import slot_step

    book_end = naive_backtesting_slot(meta["step_slot_datetimes"][-1]) + slot_step()
    for row in full_chart_rows:
        if naive_backtesting_slot(row["slot_datetime"]) == book_end:
            return float(row["Simulierter SoC (%)"])
    raise ValueError(
        f"Sunrise-Fenster ready_by {meta['ready_by']}: MILP-Slot {book_end.isoformat()} "
        "nach dem Buchungsfenster fehlt (End-SoC an SA₂ nicht bestimmbar)."
    )


def _anchor_step_end_soc(
    chart_rows: list[dict],
    step_start_soc: float,
    battery_params: dict | list[dict],
) -> float:
    """End-SoC eines fixed_24h-Schritts (Horizontende); Sunrise: ``_sunrise_book_end_soc``."""
    end_soc = horizon_end_soc_from_chart_rows(chart_rows)
    if end_soc is None:
        end_soc = horizon_end_soc_percent(
            chart_rows, step_start_soc, battery_params
        )
    return (
        end_soc
        if end_soc is not None
        else float(chart_rows[-1]["Simulierter SoC (%)"])
    )


def _window_import_caps(
    plan: _AnchorWindowPlan,
    scenario_params: dict,
    peak_by_month: Mapping[str, float],
) -> ImportCaps | None:
    """Limits of the booked slots only.

    The SA₀→SA₁ part was booked by the previous window and is never billed from this plan. A limit
    there would only make its overshoot variable free for the slots that do count.
    """
    if parse_import_cap(scenario_params) is None:
        return None
    caps = import_caps_from_params(
        scenario_params,
        [naive_backtesting_slot(row["slot_datetime"]) for row in plan.matrix],
        peak_by_month,
    )
    if caps is None or plan.flex_book_hours is None:
        return caps
    return caps.only_at(range(plan.flex_book_start, plan.flex_book_start + plan.flex_book_hours))


def import_peaks_after_window(
    book_rows: list[dict],
    peak_by_month: Mapping[str, float],
) -> dict[str, float]:
    """Month peaks after a booked window, like the bill from what was booked; the next window plans with them."""
    peaks = dict(peak_by_month)
    for row in book_rows:
        month = f"{naive_backtesting_slot(row['slot_datetime']):%Y-%m}"
        peaks[month] = max(peaks.get(month, 0.0), _grid_kw_from_row(row))
    return peaks


def _simulate_plan_horizon(
    plan,
    sim_soc: float,
    *,
    battery_params: dict | list[dict],
    hours_done: int,
    collect_cbc: bool,
    scenario_params: dict,
    forecast_planner=None,
    import_peak_by_month: Mapping[str, float] | None = None,
) -> list[dict]:
    matrix = plan.matrix
    extra_kwargs: dict = {}
    if forecast_planner is not None:
        # Forecast mode: the MILP sees the plan matrix, the window's own matrix books.
        matrix = forecast_planner.plan_matrix(plan.matrix, plan.meta["sa1"])
        extra_kwargs["booking_matrix"] = plan.matrix
    import_caps = _window_import_caps(plan, scenario_params, import_peak_by_month or {})
    if import_caps is not None:
        extra_kwargs["import_caps"] = import_caps
    return _simulate_horizon(
        matrix,
        sim_soc,
        battery_params=battery_params,
        verbose=False,
        consumer_daily_targets_kwh=plan.meta["consumer_daily_targets_kwh"],
        simulation_hour_offset=hours_done if collect_cbc else None,
        sunrise_soc_min_index=plan.sunrise_soc_min_index,
        flexible_consumers=_flexible_consumers_from_scenario(scenario_params),
        commit_hours=plan.commit_hours,
        disable_horizon_soc_anchor=plan.disable_soc_anchor,
        flex_book_hours=plan.flex_book_hours,
        flex_book_start=plan.flex_book_start,
        soc_hold_index=plan.soc_hold_index,
        soc_hold_percent=plan.soc_hold_percent,
        **extra_kwargs,
    )


def _optional_full_horizon_snapshot(
    plan,
    chart_rows: list[dict],
    *,
    collect_full_horizon: bool,
) -> tuple[list[dict] | None, list[dict] | None]:
    if collect_full_horizon and plan.matrix_full is not None:
        return list(chart_rows), plan.matrix_full
    return None, None


def rod_store_levels_after_window(
    book_matrix: list[dict],
    book_rows: list[dict],
    consumers: list[dict],
    scenario_params: dict,
    levels_kwh: dict[str, float],
) -> dict[str, float]:
    """Store level per heating rod after a booked window: the next window starts from it, like the SoC."""
    rods = [consumer for consumer in consumers if is_heating_rod_consumer(consumer)]
    if not rods:
        return {}
    with planning_scenario_scope({**scenario_params, ROD_STORE_START_KEY: levels_kwh}):
        contexts = _resolve_thermal_flex_contexts(book_matrix, rods, None)
    dt_h = validate_dt_h(DEFAULT_DT_H)
    after: dict[str, float] = {}
    for rod in rods:
        balance = contexts[str(rod["id"])][STORE_BALANCE_CONTEXT_KEY]
        column = consumer_column_name(rod)
        level = balance.start_kwh
        for slot, row in enumerate(book_rows):
            heat_kwh = float(row.get(column, 0.0) or 0.0) * dt_h
            level = next_level_kwh(level, heat_kwh, balance.drain_kwh[slot], balance.capacity_kwh)
        after[str(rod["id"])] = level
    return after


def hp_store_levels_after_window(
    book_matrix: list[dict],
    book_rows: list[dict],
    consumers: list[dict],
    scenario_params: dict,
    levels_kwh: dict[str, float],
) -> dict[str, float]:
    """Band level per heat pump after a booked window (``optimizer.hp_store``), like the SoC.

    The booked heat (pump × JAZ plus its rods) fills the level, the year model's heat empties it.
    """
    pumps = [consumer for consumer in consumers if is_thermal_flex_consumer(consumer)]
    if not pumps:
        return {}
    rods = [consumer for consumer in consumers if is_heating_rod_consumer(consumer)]
    with planning_scenario_scope({**scenario_params, HP_STORE_START_KEY: levels_kwh}):
        contexts = _resolve_thermal_flex_contexts(book_matrix, pumps, None)
    dt_h = validate_dt_h(DEFAULT_DT_H)
    after: dict[str, float] = {}
    for pump in pumps:
        balance = (contexts.get(str(pump["id"])) or {}).get(HP_STORE_CONTEXT_KEY)
        if balance is None:
            continue
        columns = [consumer_column_name(pump)]
        rod_columns = [
            consumer_column_name(rod) for rod in rods if str(rod.get("parent_id")) == str(pump["id"])
        ]
        level = balance.start_kwh
        for slot, row in enumerate(book_rows):
            heat_kwh = sum(float(row.get(column, 0.0) or 0.0) for column in columns) * dt_h * balance.efficiency
            heat_kwh += sum(float(row.get(column, 0.0) or 0.0) for column in rod_columns) * dt_h
            level = next_hp_level_kwh(level, heat_kwh, balance.drain_kwh[slot], balance.capacity_kwh)
        after[str(pump["id"])] = level
    return after


def _simulate_anchor_step(
    anchor: datetime,
    sim_soc: float,
    *,
    horizon_mode: str,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
    battery_params: dict | list[dict],
    feed_in_settings: feed_in_prices.FeedInSettings,
    hours_done: int,
    collect_cbc: bool,
    price_resources: BacktestingPriceResources | None = None,
    collect_full_horizon: bool = False,
    forecast_planner=None,
    rod_store_kwh: dict[str, float] | None = None,
    import_peak_by_month: Mapping[str, float] | None = None,
    hp_store_kwh: dict[str, float] | None = None,
) -> tuple[
    list[dict],
    list[dict],
    dict,
    float,
    list[dict] | None,
    list[dict] | None,
    int | None,
]:
    """Ein Backtesting-Schritt für fixed_24h oder sunrise_window (Book [SA₁, SA₂) je ready_by-Tag)."""
    step_start_soc = float(sim_soc)
    # Rod bound and thermal contexts read this scenario's house profile, not the Live one.
    with planning_scenario_scope(
        {**scenario_params, ROD_STORE_START_KEY: rod_store_kwh, HP_STORE_START_KEY: hp_store_kwh}
    ):
        plan = _build_anchor_window_plan(
            anchor,
            step_start_soc,
            horizon_mode=horizon_mode,
            cache=cache,
            prices_df=prices_df,
            scenario_params=scenario_params,
            feed_in_settings=feed_in_settings,
            price_resources=price_resources,
        )
        chart_rows = _simulate_plan_horizon(
            plan,
            sim_soc,
            battery_params=battery_params,
            hours_done=hours_done,
            collect_cbc=collect_cbc,
            scenario_params=scenario_params,
            forecast_planner=forecast_planner,
            import_peak_by_month=import_peak_by_month,
        )
    flexible_consumers = _flexible_consumers_from_scenario(scenario_params)
    if horizon_mode == SUNRISE_WINDOW:
        _stash_sunrise_full_horizon_flex(plan.meta, chart_rows, flexible_consumers)
        new_soc = _sunrise_book_end_soc(chart_rows, plan.meta)
    full_rows, full_matrix = _optional_full_horizon_snapshot(
        plan, chart_rows, collect_full_horizon=collect_full_horizon
    )
    chart_rows, matrix = _apply_backtesting_step(
        chart_rows, plan.matrix, plan.meta, horizon_mode=horizon_mode
    )
    if horizon_mode != SUNRISE_WINDOW:
        new_soc = _anchor_step_end_soc(chart_rows, step_start_soc, battery_params)
    return (
        chart_rows,
        matrix,
        plan.meta,
        new_soc,
        full_rows,
        full_matrix,
        plan.sunrise_soc_min_index,
    )


def _hour_cost_parts_without_optimization(
    load_kw: float,
    pv_kw: float,
    price_cent: float,
    k_push_cent: float,
) -> tuple[float, float, float, float, float]:
    """Import/export split without optimization (no battery, no flex).

    Returns ``(import_cost_eur, export_earn_eur, net_eur, import_kwh, export_kwh)``.
    Energy is ``kW * dt_h`` (QH slots after 2.5).
    """
    dt_h = validate_dt_h(DEFAULT_DT_H)
    p_grid = float(load_kw) - float(pv_kw)
    if p_grid >= 0:
        import_kwh = float(p_grid) * dt_h
        import_eur = import_kwh * float(price_cent) / 100.0
        return import_eur, 0.0, import_eur, import_kwh, 0.0
    export_kwh = float(-p_grid) * dt_h
    export_eur = export_kwh * float(k_push_cent) / 100.0
    return 0.0, export_eur, -export_eur, 0.0, export_kwh


def _hour_cost_without_optimization(
    load_kw: float,
    pv_kw: float,
    price_cent: float,
    k_push_cent: float,
) -> float:
    """
    Stromkosten eines Slots ohne Optimierung:
    historischer Verbrauch minus PV, keine Batterie, kein Flex-Scheduling.
    """
    return _hour_cost_parts_without_optimization(
        load_kw, pv_kw, price_cent, k_push_cent
    )[2]



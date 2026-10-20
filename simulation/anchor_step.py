"""Per-anchor backtesting simulation step helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import config
from data import feed_in_prices
from data.backtesting_prices import BacktestingPriceResources
from optimizer import (
    horizon_end_soc_from_chart_rows,
    horizon_end_soc_percent,
    _delivered_flex_kwh_from_rows,
)
from optimizer.slot_duration import DEFAULT_DT_H, validate_dt_h
from optimizer.targets import consumer_column_name
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
    delivered = _delivered_flex_kwh_from_rows(
        full_chart_rows,
        flexible_consumers=flexible_consumers,
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


def _simulate_plan_horizon(
    plan,
    sim_soc: float,
    *,
    battery_params: dict | list[dict],
    hours_done: int,
    collect_cbc: bool,
    scenario_params: dict,
) -> list[dict]:
    return _simulate_horizon(
        plan.matrix,
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



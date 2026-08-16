"""Per-anchor backtesting simulation step helpers."""
from __future__ import annotations

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


def _stash_sunrise_full_horizon_flex(
    meta: dict,
    full_chart_rows: list[dict],
    flexible_consumers: list,
) -> None:
    """
    Deadline-Flex (EV) may land in SA₀→SA₁ foresight; book cut drops those hours.

    Stash full-horizon flex for plausibility and foresight rows for CSV merge.
    """
    delivered = _delivered_flex_kwh_from_rows(
        full_chart_rows,
        flexible_consumers=flexible_consumers,
    )
    meta["plausibility_optimized_flex_kwh"] = round(
        sum(float(v) for v in delivered.values()), 3
    )
    sa1 = naive_backtesting_slot(meta["sa1"])
    foresight: list[dict] = []
    for row in full_chart_rows:
        slot = naive_backtesting_slot(row["slot_datetime"])
        if slot >= sa1:
            continue
        flex_kw = sum(
            float(row.get(consumer_column_name(consumer), 0.0) or 0.0)
            for consumer in flexible_consumers
        )
        if flex_kw > 1e-6:
            foresight.append(row)
    meta["foresight_flex_rows"] = foresight


def _merge_foresight_flex_into_series(
    all_chart_rows: list[dict],
    all_timestamps: list,
    foresight_rows: list[dict],
) -> None:
    """Overwrite prior book hours with foresight flex (same slot) so EV energy is kept."""
    if not foresight_rows:
        return
    by_ts = {
        naive_backtesting_slot(ts): index for index, ts in enumerate(all_timestamps)
    }
    for row in foresight_rows:
        slot = naive_backtesting_slot(row["slot_datetime"])
        index = by_ts.get(slot)
        if index is None:
            all_chart_rows.append(row)
            all_timestamps.append(row["slot_datetime"])
            by_ts[slot] = len(all_timestamps) - 1
        else:
            all_chart_rows[index] = row
            all_timestamps[index] = row["slot_datetime"]


def _simulate_anchor_step(
    anchor: datetime,
    sim_soc: float,
    *,
    horizon_mode: str,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
    battery_params: dict,
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
    """Ein Backtesting-Schritt für fixed_24h oder sunrise_window (ready_by → SA₂ book)."""
    sunrise_soc_min_index = None
    matrix_full: list[dict] | None = None
    disable_soc_anchor = config.get_backtesting_disable_horizon_soc_anchor()
    step_start_soc = float(sim_soc)
    soc_hold_index: int | None = None
    soc_hold_percent: float | None = None
    flex_book_hours: int | None = None
    flex_book_start = 0
    commit_hours = config.get_backtesting_commit_hours()

    if horizon_mode == SUNRISE_WINDOW:
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
        disable_soc_anchor = True
        sunrise_soc_min_index = None
        flex_book_start = int(sa1_index)
        flex_book_hours = int(meta["book_hours"])
        commit_hours = len(matrix)
        if sa1_index > 0:
            soc_hold_index = int(sa1_index) - 1
            soc_hold_percent = step_start_soc
        # Initial SoC at SA₀: use carry-in (equality at SA₁ keeps night net-neutral).
    else:
        matrix, meta = build_historical_window_matrix(
            anchor,
            cache,
            prices_df,
            feed_in_settings=feed_in_settings,
            scenario_params=scenario_params,
        )

    chart_rows = _simulate_horizon(
        matrix,
        sim_soc,
        battery_params=battery_params,
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
        simulation_hour_offset=hours_done if collect_cbc else None,
        sunrise_soc_min_index=sunrise_soc_min_index,
        flexible_consumers=_flexible_consumers_from_scenario(scenario_params),
        commit_hours=commit_hours,
        disable_horizon_soc_anchor=disable_soc_anchor,
        flex_book_hours=flex_book_hours,
        flex_book_start=flex_book_start,
        soc_hold_index=soc_hold_index,
        soc_hold_percent=soc_hold_percent,
    )
    flexible_consumers = _flexible_consumers_from_scenario(scenario_params)
    if horizon_mode == SUNRISE_WINDOW:
        _stash_sunrise_full_horizon_flex(meta, chart_rows, flexible_consumers)
    full_rows: list[dict] | None = None
    full_matrix: list[dict] | None = None
    if collect_full_horizon and matrix_full is not None:
        full_rows = list(chart_rows)
        full_matrix = matrix_full
    chart_rows, matrix = _apply_backtesting_step(
        chart_rows, matrix, meta, horizon_mode=horizon_mode
    )
    if horizon_mode == SUNRISE_WINDOW and chart_rows:
        new_soc = float(chart_rows[-1]["Simulierter SoC (%)"])
    else:
        end_soc = horizon_end_soc_from_chart_rows(chart_rows)
        if end_soc is None:
            end_soc = horizon_end_soc_percent(
                chart_rows, step_start_soc, battery_params
            )
        new_soc = (
            end_soc
            if end_soc is not None
            else float(chart_rows[-1]["Simulierter SoC (%)"])
        )
    return (
        chart_rows,
        matrix,
        meta,
        new_soc,
        full_rows,
        full_matrix,
        sunrise_soc_min_index,
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



"""OptimizationDisplayBundle für Backtesting-Abweichungsfenster (1.25.f)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import os

import pandas as pd
import streamlit as st

import config
from optimizer.charge_immediate import prepare_optimization_matrix
from optimizer.charging_context import serialize_charging_contexts
from optimizer.filter_context import resolve_filter_contexts
from optimizer.simulation import (
    apply_horizon_charging_limits,
    calculate_cost_euro_from_rows,
    hourly_consumption_kwh_from_rows,
    hourly_cost_euro_from_rows,
    hourly_savings_euro_from_rows,
    resolve_horizon_consumer_targets_kwh,
    simulate_baseline_horizon,
    simulate_baseline_with_optimized_flex,
    simulate_matched_baseline_horizon,
    total_consumption_kwh_from_rows,
)
from data.planning_window import (
    UiChartWindow,
    align_to_planning_timezone,
    compute_planning_window,
    compute_sunrise_anchors,
    hourly_slots_inclusive,
    normalize_hour_slot,
    ui_chart_zones,
)
from simulation.backtesting_horizon import window_start_before_anchor
from simulation.backtesting_snapshots import (
    load_window_snapshot,
    snapshot_supports_sunrise_view,
)
from simulation.engine import _scenario_to_battery_params, flex_consumers_from_snapshot
from simulation.horizon_mode import BACKTESTING_STEP_HOURS, FIXED_24H, SUNRISE_WINDOW
from ui.chart_context import LiveChartContext
from ui.history_navigation import s2_zone_help_text
from ui.simulation_results import (
    OptimizationDisplayBundle,
    build_optimization_display_bundle,
)
from ui.backtesting_chart_context import (
    VIEW_MODE_24H,
    VIEW_MODE_SUNRISE,
    _SA_SEGMENT_BOOK,
    _SA_SEGMENT_FORESIGHT,
    _SUNRISE_SEGMENT_LABELS,
    _backtesting_24h_header_label,
    _backtesting_24h_slots_from_anchor,
    _backtesting_sunrise_header_label,
    _backtesting_sunrise_segment_window,
    _battery_params_from_snapshot,
    _build_backtesting_24h_chart_context,
    _build_backtesting_sunrise_chart_context,
    _geo_from_snapshot,
    _parse_slot_datetime,
    _parse_window_anchor,
    _planning_moment,
    _rows_with_parsed_slots,
    _slot_datetimes_from_sim_rows,
    build_backtesting_chart_context,
    format_backtesting_window_range,
    preferred_sa_segment_toggle,
    sa_segment_date_overlap_hours,
)







































def _select_snapshot_rows(
    snapshot: dict,
    *,
    view_mode: str,
    tz_name: str,
) -> tuple[list[dict], list[dict]]:
    if view_mode == VIEW_MODE_SUNRISE and snapshot_supports_sunrise_view(snapshot):
        return (
            _rows_with_parsed_slots(snapshot["chart_rows_full"], tz_name),
            _rows_with_parsed_slots(snapshot["matrix_full"], tz_name),
        )
    return (
        _rows_with_parsed_slots(snapshot["chart_rows_24h"], tz_name),
        _rows_with_parsed_slots(snapshot["matrix_24h"], tz_name),
    )


def _build_backtesting_savings_info(
    matrix: list[dict],
    chart_rows: list[dict],
    *,
    initial_soc: float,
    consumer_daily_targets_kwh: dict[str, float] | None,
    sunrise_soc_min_index: int | None,
    battery_params: dict,
) -> dict:
    """Savings-Dict für Charts aus persistierten Backtesting-Zeilen (ohne Legacy-Profile)."""
    matrix_prep, charging_contexts, targets = prepare_optimization_matrix(
        matrix,
        consumer_daily_targets_kwh,
    )
    filters = resolve_filter_contexts(matrix_prep)
    optimized_rows = chart_rows
    baseline_rows = simulate_baseline_horizon(
        matrix_prep,
        initial_soc,
        charging_contexts=charging_contexts,
        battery_params=battery_params,
    )
    horizon_targets = resolve_horizon_consumer_targets_kwh(matrix_prep, targets)
    horizon_targets = apply_horizon_charging_limits(horizon_targets, charging_contexts)
    matched_baseline_rows = simulate_matched_baseline_horizon(
        matrix_prep,
        initial_soc,
        horizon_targets,
        charging_contexts,
        battery_params=battery_params,
    )
    baseline_same_flex_rows = simulate_baseline_with_optimized_flex(
        matrix_prep,
        optimized_rows,
        initial_soc,
        battery_params=battery_params,
    )
    optimized_cost = calculate_cost_euro_from_rows(optimized_rows, None)
    baseline_cost = calculate_cost_euro_from_rows(baseline_rows, None)
    matched_baseline_cost = calculate_cost_euro_from_rows(matched_baseline_rows, None)
    hourly_matched_cost = hourly_cost_euro_from_rows(matched_baseline_rows, None)
    hourly_optimized_cost = hourly_cost_euro_from_rows(optimized_rows, None)
    hourly_savings = hourly_savings_euro_from_rows(
        matched_baseline_rows,
        optimized_rows,
        None,
    )
    hourly_battery_only_cost = hourly_cost_euro_from_rows(baseline_same_flex_rows, None)
    hourly_matched_consumption = hourly_consumption_kwh_from_rows(matched_baseline_rows)
    hourly_optimized_consumption = hourly_consumption_kwh_from_rows(optimized_rows)
    return {
        "baseline_cost_euro": round(baseline_cost, 4),
        "matched_baseline_cost_euro": round(matched_baseline_cost, 4),
        "optimized_cost_euro": round(optimized_cost, 4),
        "savings_euro": round(baseline_cost - optimized_cost, 4),
        "savings_matched_euro": round(matched_baseline_cost - optimized_cost, 4),
        "baseline_consumption_kwh": round(total_consumption_kwh_from_rows(baseline_rows), 3),
        "matched_baseline_consumption_kwh": round(
            total_consumption_kwh_from_rows(matched_baseline_rows), 3
        ),
        "optimized_consumption_kwh": round(
            total_consumption_kwh_from_rows(optimized_rows), 3
        ),
        "charging_contexts": serialize_charging_contexts(charging_contexts),
        "optimized_rows": optimized_rows,
        "baseline_rows": baseline_rows,
        "matched_baseline_rows": matched_baseline_rows,
        "baseline_same_flex_rows": baseline_same_flex_rows,
        "hourly_matched_baseline_cost_euro": hourly_matched_cost,
        "hourly_optimized_cost_euro": hourly_optimized_cost,
        "hourly_battery_only_baseline_cost_euro": hourly_battery_only_cost,
        "hourly_savings_euro": hourly_savings,
        "hourly_matched_baseline_consumption_kwh": hourly_matched_consumption,
        "hourly_optimized_consumption_kwh": hourly_optimized_consumption,
    }


def build_backtesting_display_bundle(
    snapshot: dict,
    *,
    view_mode: str = VIEW_MODE_24H,
    segment_index: int = 0,
) -> OptimizationDisplayBundle:
    geo = _geo_from_snapshot(snapshot)
    _, _, tz_name = geo
    chart_rows, matrix = _select_snapshot_rows(
        snapshot,
        view_mode=view_mode,
        tz_name=tz_name,
    )
    initial_soc = float(snapshot.get("initial_soc", 50.0))
    meta = snapshot.get("meta") or {}
    targets_raw = meta.get("consumer_daily_targets_kwh")
    if targets_raw is None:
        targets_raw = meta.get("historical_totals")
    targets = dict(targets_raw) if targets_raw is not None else None
    sunrise_soc_min_index = snapshot.get("sunrise_soc_min_index")
    if view_mode == VIEW_MODE_24H:
        sunrise_soc_min_index = None

    battery_params = _battery_params_from_snapshot(snapshot)
    savings_info = _build_backtesting_savings_info(
        matrix,
        chart_rows,
        initial_soc=initial_soc,
        consumer_daily_targets_kwh=targets,
        sunrise_soc_min_index=sunrise_soc_min_index,
        battery_params=battery_params,
    )
    optimized_df = pd.DataFrame(chart_rows)
    baseline_df = pd.DataFrame(savings_info.get("baseline_rows") or [])
    matched_rows = savings_info.get("matched_baseline_rows")
    matched_df = pd.DataFrame(matched_rows) if matched_rows else None

    geo = _geo_from_snapshot(snapshot)
    window_anchor = str(snapshot["window_anchor"])
    chart_context = build_backtesting_chart_context(
        window_anchor,
        view_mode=view_mode,
        segment_index=segment_index,
        sim_rows=chart_rows,
        geo=geo,
    )
    header_label = None
    header_help = None
    if view_mode == VIEW_MODE_24H:
        header_label = _backtesting_24h_header_label(window_anchor, tz_name)
    elif view_mode == VIEW_MODE_SUNRISE:
        header_label = _backtesting_sunrise_header_label(
            window_anchor,
            tz_name,
            segment_index,
        )
        header_help = s2_zone_help_text()
    flex = flex_consumers_from_snapshot(snapshot)
    return build_optimization_display_bundle(
        savings_info,
        optimized_df,
        baseline_df,
        matched_df,
        chart_context=chart_context,
        optimization_matrix=matrix,
        simulation_table_title=None,
        battery_params=battery_params,
        chart_header_label=header_label,
        chart_header_help=header_help,
        backtesting_chart=True,
        flex_consumers=tuple(flex),
    )


def snapshot_horizon_matches_log(snapshot: dict, log_horizon_mode: str) -> bool:
    return snapshot.get("horizon_mode") == log_horizon_mode


def load_backtesting_display_bundle(
    log_dir: str,
    window_anchor: str,
    scenario_id: str,
    *,
    view_mode: str = VIEW_MODE_24H,
    segment_index: int = 0,
    log_horizon_mode: str | None = None,
) -> OptimizationDisplayBundle | None:
    snapshot = load_window_snapshot(log_dir, window_anchor, scenario_id)
    if snapshot is None:
        return None
    if log_horizon_mode is not None and not snapshot_horizon_matches_log(
        snapshot,
        log_horizon_mode,
    ):
        raise ValueError(
            f"Fenster-Snapshot gehört zu Horizont {snapshot.get('horizon_mode')!r}, "
            f"Backtesting-Log zu {log_horizon_mode!r}. "
            "Bitte Backtesting neu berechnen."
        )
    return build_backtesting_display_bundle(
        snapshot,
        view_mode=view_mode,
        segment_index=segment_index,
    )


def log_supports_sunrise_chart_view(meta: dict) -> bool:
    return meta.get("period", {}).get("horizon_mode") == SUNRISE_WINDOW


_ON_DEMAND_CACHE_KEY = "backtesting_on_demand_snapshots"
_BUNDLE_CACHE_KEY = "backtesting_display_bundle_cache"


def _on_demand_snapshot_cache() -> dict[tuple[str, str, str], dict]:
    cache = st.session_state.get(_ON_DEMAND_CACHE_KEY)
    if not isinstance(cache, dict):
        cache = {}
        st.session_state[_ON_DEMAND_CACHE_KEY] = cache
    return cache


def _display_bundle_cache() -> dict[tuple, OptimizationDisplayBundle]:
    cache = st.session_state.get(_BUNDLE_CACHE_KEY)
    if not isinstance(cache, dict):
        cache = {}
        st.session_state[_BUNDLE_CACHE_KEY] = cache
    return cache


def resolve_backtesting_display_bundle(
    log_dir: str,
    window_anchor: str,
    scenario_id: str,
    meta: dict,
    hourly_df: pd.DataFrame,
    *,
    view_mode: str = VIEW_MODE_24H,
    segment_index: int = 0,
) -> OptimizationDisplayBundle | None:
    """
    Snapshot aus JSONL, sonst on-demand Einzelfenster-Simulation (Session-Cache).
    """
    log_horizon = meta.get("period", {}).get("horizon_mode", FIXED_24H)
    bundle_key = (
        os.path.abspath(log_dir),
        str(window_anchor),
        str(scenario_id),
        str(view_mode),
        int(segment_index),
        str(log_horizon),
    )
    bundle_cache = _display_bundle_cache()
    cached = bundle_cache.get(bundle_key)
    if cached is not None:
        return cached

    bundle = load_backtesting_display_bundle(
        log_dir,
        window_anchor,
        scenario_id,
        view_mode=view_mode,
        segment_index=segment_index,
        log_horizon_mode=log_horizon,
    )
    if bundle is None:
        from simulation.backtesting_single_window import (
            cache_key_for_window,
            initial_soc_for_anchor,
            simulate_window_snapshot,
        )

        cache_key = cache_key_for_window(window_anchor, scenario_id, log_horizon)
        snapshot_cache = _on_demand_snapshot_cache()
        snapshot = snapshot_cache.get(cache_key)
        if snapshot is None:
            anchor_dt = pd.Timestamp(window_anchor).to_pydatetime()
            initial_soc = initial_soc_for_anchor(anchor_dt, scenario_id, hourly_df)
            with st.spinner("Fenster wird berechnet…"):
                snapshot = simulate_window_snapshot(
                    anchor_dt,
                    scenario_id,
                    meta,
                    initial_soc=initial_soc,
                    horizon_mode=log_horizon,
                )
            snapshot_cache[cache_key] = snapshot
            from simulation.backtesting_snapshots import append_window_snapshot

            append_window_snapshot(log_dir, snapshot)
        bundle = build_backtesting_display_bundle(
            snapshot,
            view_mode=view_mode,
            segment_index=segment_index,
        )
    if bundle is not None:
        bundle_cache[bundle_key] = bundle
    return bundle

# Re-Exports für API-Stabilität (from ui.backtesting_display_bundle import ...)
__all__ = [
    "VIEW_MODE_24H",
    "VIEW_MODE_SUNRISE",
    "build_backtesting_chart_context",
    "build_backtesting_display_bundle",
    "format_backtesting_window_range",
    "load_backtesting_display_bundle",
    "log_supports_sunrise_chart_view",
    "preferred_sa_segment_toggle",
    "resolve_backtesting_display_bundle",
    "sa_segment_date_overlap_hours",
    "snapshot_horizon_matches_log",
]

"""Build historical / sunrise optimization matrices for backtesting."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import config
from data import feed_in_prices
from data.backtesting_prices import BacktestingPriceResources, matrix_prices_from_context
from optimizer.slot_duration import DEFAULT_DT_H
from simulation.baseload_validation import resolve_hourly_baseload_kw
from simulation.backtesting_horizon import (
    naive_backtesting_slot,
    overlay_step_consumption_on_matrix,
    resolve_sunrise_book_step_for_scenario,
)
from simulation.historical_cache import HistoricalDataCache


def _pricing_kwargs_from_scenario(scenario_params):
    from simulation.engine import _pricing_kwargs_from_scenario as _impl

    return _impl(scenario_params)


def scenario_uses_imported_pv(scenario_params: dict | None) -> bool:
    """True when scenario requests house-profile PV CSV and a path is configured.

    Short PV CSVs (< ``MIN_HOURS_FULL_YEAR`` span) do not qualify — SE stays
    on synthetic Open-Meteo PV.
    """
    if not isinstance(scenario_params, dict):
        return False
    if not scenario_params.get("use_imported_pv"):
        return False
    profile = scenario_params.get("_house_profile")
    if not isinstance(profile, dict):
        return False
    path = str(profile.get("pv_profile_csv", "") or "").strip()
    if not path:
        return False
    from house_config.consumption_csv import profile_csv_adequate_for_se

    return profile_csv_adequate_for_se(path)


def _imported_pv_kw_for_slots(
    slot_datetimes: list[datetime],
    scenario_params: dict,
) -> list[float] | None:
    """Return imported PV kW series, or None to fall back to weather PV."""
    if not scenario_uses_imported_pv(scenario_params):
        return None
    profile = scenario_params.get("_house_profile")
    if not isinstance(profile, dict):
        return None
    path = str(profile.get("pv_profile_csv", "") or "").strip()
    if not path:
        return None
    from data.consumption_profiles import csv_kw_at_datetime

    return [round(csv_kw_at_datetime(path, slot_dt), 3) for slot_dt in slot_datetimes]


def collect_imported_pv_scenario_meta(
    scenarios: dict[str, dict],
) -> tuple[list[str], list[str]]:
    """Return (used_ids, missing_csv_ids) for scenarios with use_imported_pv."""
    used: list[str] = []
    missing: list[str] = []
    for scenario_id, params in scenarios.items():
        if not isinstance(params, dict) or not params.get("use_imported_pv"):
            continue
        if scenario_uses_imported_pv(params):
            used.append(str(scenario_id))
        else:
            missing.append(str(scenario_id))
    return used, missing


def _pricing_kwargs_from_scenario(scenario_params: dict | None) -> dict:
    if not scenario_params:
        return {}
    from data.backtesting_prices import pricing_kwargs_from_resolved

    return pricing_kwargs_from_resolved(scenario_params)


def build_historical_matrix_for_slots(
    slot_datetimes: list[datetime],
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    *,
    window_end: datetime,
    feed_in_settings: feed_in_prices.FeedInSettings | None = None,
    charging_anchor: datetime | None = None,
    price_resources: BacktestingPriceResources | None = None,
    planning_moment: datetime | None = None,
    scenario_params: dict | None = None,
) -> tuple[list[dict], dict]:
    """Baut eine Optimierungsmatrix für beliebige stündliche Slots aus historischen Logs."""
    from house_config.planning_flex_bridge import (
        PROFILE_SPEC,
        house_profile_baseload_overlay,
        meter_residual_baseload_kw,
        milp_flex_thermal_annual_ids,
        monthly_residual_baseload_kw,
        profile_flat_baseload_kw,
        resolve_consumption_source,
        resolve_profile_spec_flex_targets,
    )
    from house_config.profile_csv_policy import (
        se_uses_meter_residual_baseload,
        se_uses_monthly_baseload,
    )
    consumption_source = resolve_consumption_source(scenario_params)
    profile = (scenario_params or {}).get("_house_profile")
    flexible_consumers = None
    flex_consumer_ids = None
    if scenario_params:
        from simulation.engine import _flexible_consumers_from_scenario
        flexible_consumers = _flexible_consumers_from_scenario(scenario_params)
        if flexible_consumers:
            flex_consumer_ids = [consumer["id"] for consumer in flexible_consumers]

    baseload_stored, historical_totals, total_load, hourly_flex = (
        cache.get_window_consumption(
            slot_datetimes,
            flex_consumer_ids=flex_consumer_ids,
        )
    )
    _, all_consumer_totals, reference_total_load, _ = cache.get_window_consumption(
        slot_datetimes
    )
    reference_total_kwh = round(sum(reference_total_load), 3)

    residual_clipped_hours = 0
    if consumption_source == PROFILE_SPEC:
        if not profile:
            raise ValueError(
                "consumption_source=profile_spec erfordert _house_profile im Szenario."
            )
        from data.modeled_climate import ModeledClimateContext

        climate = ModeledClimateContext.from_scenario(scenario_params)
        thermal_milp_ids = milp_flex_thermal_annual_ids(flexible_consumers)
        overlay = house_profile_baseload_overlay(
            profile,
            slot_datetimes,
            historical_totals=None,
            cons_data_consumer_ids=set(),
            milp_flex_thermal_ids=thermal_milp_ids,
            climate=climate,
        )
        if se_uses_meter_residual_baseload(profile):
            residual, residual_clipped_hours = meter_residual_baseload_kw(
                profile,
                slot_datetimes,
                climate=climate,
            )
            baseload_kw = [round(base + extra, 3) for base, extra in zip(residual, overlay)]
        elif se_uses_monthly_baseload(profile):
            residual = monthly_residual_baseload_kw(
                profile,
                slot_datetimes,
                climate=climate,
            )
            baseload_kw = [round(base + extra, 3) for base, extra in zip(residual, overlay)]
        else:
            flat_kw = profile_flat_baseload_kw(profile)
            baseload_kw = [round(flat_kw + extra, 3) for extra in overlay]
        historical_baseload_kwh = round(sum(baseload_kw) * float(DEFAULT_DT_H), 3)
        matrix_total_kw = list(baseload_kw)
        consumer_daily_targets_kwh = resolve_profile_spec_flex_targets(
            flexible_consumers or [],
            profile,
            slot_datetimes,
            historical_totals=historical_totals,
            window_end=window_end,
            climate=climate,
        )
        spec_flex_kwh = round(sum(consumer_daily_targets_kwh.values()), 3)
        spec_total_kwh = round(historical_baseload_kwh + spec_flex_kwh, 3)
    else:
        baseload_kw, historical_baseload_kwh = resolve_hourly_baseload_kw(
            total_load, hourly_flex
        )
        if profile:
            from data.modeled_climate import ModeledClimateContext

            climate = ModeledClimateContext.from_scenario(scenario_params)
            cons_data_consumer_ids = cache.cons_data_consumer_ids_present()
            overlay = house_profile_baseload_overlay(
                profile,
                slot_datetimes,
                historical_totals=all_consumer_totals,
                cons_data_consumer_ids=cons_data_consumer_ids,
                climate=climate,
            )
            baseload_kw = [
                round(base + extra, 3) for base, extra in zip(baseload_kw, overlay)
            ]
            historical_baseload_kwh = round(sum(baseload_kw) * float(DEFAULT_DT_H), 3)
        matrix_total_kw = total_load
        consumer_daily_targets_kwh = dict(historical_totals)
        spec_flex_kwh = round(sum(consumer_daily_targets_kwh.values()), 3)
        spec_total_kwh = round(sum(total_load) * float(DEFAULT_DT_H), 3)

    stored_baseload_kwh = round(sum(baseload_stored) * float(DEFAULT_DT_H), 3)
    pv_profile = cache.get_pv_for_slots(
        slot_datetimes,
        scenario_params=scenario_params,
    )
    price_ctx = (
        price_resources.at_planning_moment(planning_moment)
        if price_resources is not None and planning_moment is not None
        else None
    )
    epex_prices, brutto_prices, price_sources = matrix_prices_from_context(
        prices_df,
        slot_datetimes,
        price_ctx,
        planning_moment=planning_moment,
        **_pricing_kwargs_from_scenario(scenario_params),
    )
    anchor = charging_anchor if charging_anchor is not None else window_end

    matrix = []
    for slot_dt, price, epex, pv, base, total, price_source in zip(
        slot_datetimes,
        brutto_prices,
        epex_prices,
        pv_profile,
        baseload_kw,
        matrix_total_kw,
        price_sources,
    ):
        row = {
            "hour": slot_dt.hour,
            "date": slot_dt.date(),
            "slot_datetime": slot_dt,
            "k_act": price,
            "price_buy": epex,
            "price_source": price_source,
            "expected_p_act": base,
            "expected_p_total": total,
            "expected_p_pv": pv,
            "consumption_mode": consumption_source,
            "charging_anchor": anchor,
        }
        matrix.append(row)

    settings = feed_in_settings or config.get_feed_in_settings()
    feed_in_prices.enrich_matrix_feed_in_prices(matrix, settings)

    if consumption_source == PROFILE_SPEC:
        reference_totals = dict(historical_totals)
        meta_historical_totals = dict(consumer_daily_targets_kwh)
        meta_historical_total_kwh = spec_total_kwh
    else:
        reference_totals = dict(historical_totals)
        meta_historical_totals = dict(historical_totals)
        meta_historical_total_kwh = round(sum(total_load) * float(DEFAULT_DT_H), 3)

    meta = {
        "window_end": window_end,
        "consumption_source": consumption_source,
        "spec_baseload_kwh": historical_baseload_kwh,
        "spec_flex_targets_kwh": dict(consumer_daily_targets_kwh),
        "spec_total_kwh": spec_total_kwh,
        "reference_totals": reference_totals,
        "reference_total_kwh": reference_total_kwh,
        "historical_totals": meta_historical_totals,
        "historical_total_kwh": meta_historical_total_kwh,
        "baseload_kwh": historical_baseload_kwh,
        "baseload_stored_kwh": stored_baseload_kwh,
        "baseload_adjustment_kwh": round(
            stored_baseload_kwh - historical_baseload_kwh, 3
        ),
        "consumer_daily_targets_kwh": consumer_daily_targets_kwh,
        "residual_clipped_hours": residual_clipped_hours,
    }
    if flexible_consumers:
        meta["_flexible_consumers"] = flexible_consumers
    return matrix, meta


def build_historical_window_matrix(
    anchor: datetime,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    feed_in_settings: feed_in_prices.FeedInSettings | None = None,
    scenario_params: dict | None = None,
) -> tuple[list[dict], dict]:
    """Baut eine 24h-Matrix aus historischen Logs für [Anker-24h, Anker)."""
    from simulation.engine import window_slot_datetimes
    slot_datetimes = window_slot_datetimes(anchor)
    return build_historical_matrix_for_slots(
        slot_datetimes,
        cache,
        prices_df,
        window_end=anchor,
        feed_in_settings=feed_in_settings,
        charging_anchor=anchor,
        scenario_params=scenario_params,
    )


def build_sunrise_window_matrix(
    anchor: datetime,
    cache: HistoricalDataCache,
    prices_df: pd.DataFrame,
    scenario_params: dict,
    feed_in_settings: feed_in_prices.FeedInSettings | None = None,
    price_resources: BacktestingPriceResources | None = None,
) -> tuple[list[dict], dict, int | None, list[dict]]:
    """
    Sunrise-MILP-Matrix SA₀→SA₂ for ready_by ``anchor``; book meta = [SA₁, SA₂).

    Returns: (book-slice matrix, meta, sa1_index in full matrix, full MILP matrix)
    """
    step = resolve_sunrise_book_step_for_scenario(anchor, scenario_params)
    book_slots = [naive_backtesting_slot(dt) for dt in step.book_slots]
    milp_slots = [naive_backtesting_slot(dt) for dt in step.milp_slots]
    matrix_kwargs = {
        "price_resources": price_resources,
        "planning_moment": step.sa0,
        "scenario_params": scenario_params,
    }
    book_matrix, meta = build_historical_matrix_for_slots(
        book_slots,
        cache,
        prices_df,
        window_end=anchor,
        feed_in_settings=feed_in_settings,
        charging_anchor=anchor,
        **matrix_kwargs,
    )
    matrix_full, _full_meta = build_historical_matrix_for_slots(
        milp_slots,
        cache,
        prices_df,
        window_end=anchor,
        feed_in_settings=feed_in_settings,
        charging_anchor=anchor,
        **matrix_kwargs,
    )
    matrix_full = list(matrix_full)
    overlay_step_consumption_on_matrix(matrix_full, book_matrix)
    meta["planning_horizon_hours"] = len(milp_slots)
    meta["sunrise_anchor"] = step.sa1
    meta["step_slot_datetimes"] = book_slots
    meta["ready_by"] = anchor
    meta["sa0"] = naive_backtesting_slot(step.sa0)
    meta["sa1"] = naive_backtesting_slot(step.sa1)
    meta["sa2"] = naive_backtesting_slot(step.sa2)
    meta["sa1_index"] = step.sa1_index
    meta["book_hours"] = step.book_hours
    return book_matrix, meta, step.sa1_index, matrix_full



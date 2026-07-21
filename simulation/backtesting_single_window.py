"""Einzelnes Backtesting-Fenster on-demand (Abweichungs-Kalender)."""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

import config
from data.data_loader import load_market_prices
from scripts.run_backtesting import resolve_backtesting_window
from simulation.backtesting_snapshots import build_window_snapshot, normalize_window_anchor_key
from simulation.engine import (
    HistoricalDataCache,
    _flexible_consumers_from_scenario,
    _scenario_to_battery_params,
    _simulate_anchor_step,
    window_slot_datetimes,
)
from simulation.horizon_mode import parse_horizon_mode

logger = logging.getLogger(__name__)

_DEFAULT_INITIAL_SOC = 50.0


def initial_soc_for_anchor(
    anchor: datetime,
    scenario_id: str,
    hourly_df: pd.DataFrame,
) -> float:
    """SOC am Fensterstart aus backtesting_hourly.csv; Fallback 50 %."""
    slots = window_slot_datetimes(anchor)
    first_slot = slots[0]
    if hourly_df is None or hourly_df.empty:
        logger.warning(
            "Kein hourly_df für SOC-Lookup — Fallback %.1f%% (Anker %s, Szenario %s).",
            _DEFAULT_INITIAL_SOC,
            anchor,
            scenario_id,
        )
        return _DEFAULT_INITIAL_SOC
    part = hourly_df.loc[hourly_df["scenario_id"] == scenario_id].copy()
    if part.empty or "ts" not in part.columns or "sim_soc" not in part.columns:
        logger.warning(
            "Keine sim_soc-Zeilen für Szenario %s — Fallback %.1f%%.",
            scenario_id,
            _DEFAULT_INITIAL_SOC,
        )
        return _DEFAULT_INITIAL_SOC
    part["ts"] = pd.to_datetime(part["ts"])
    match = part.loc[part["ts"] == pd.Timestamp(first_slot)]
    if match.empty:
        logger.warning(
            "Kein hourly-Eintrag für %s (Szenario %s) — Fallback %.1f%%.",
            first_slot,
            scenario_id,
            _DEFAULT_INITIAL_SOC,
        )
        return _DEFAULT_INITIAL_SOC
    return float(match.iloc[0]["sim_soc"])


def _price_month_bounds(anchor: datetime, period: dict) -> tuple[int, int]:
    start_month = int(period.get("start_month") or anchor.month)
    end_month = int(period.get("end_month") or anchor.month)
    month = anchor.month
    if start_month == end_month:
        return start_month, end_month
    return month, min(12, month + 1)


def _load_prices_for_anchor(anchor: datetime, period: dict) -> pd.DataFrame:
    sim_cfg = config.get_scenario_explorer_conf()
    year = int(period.get("backtesting_year") or anchor.year)
    price_start, price_end = _price_month_bounds(anchor, period)
    start, end = resolve_backtesting_window(
        pd.Timestamp(year, price_start, 1),
        pd.Timestamp(year, price_end, 1),
        sim_cfg.get("price_range", "last_12_months"),
    )
    return load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )


def simulate_window_snapshot(
    anchor: datetime,
    scenario_id: str,
    meta: dict,
    *,
    initial_soc: float,
    horizon_mode: str,
    cache: HistoricalDataCache | None = None,
) -> dict:
    """Simuliert ein Fenster und liefert ein In-Memory-Snapshot-Dict."""
    horizon_mode = parse_horizon_mode(horizon_mode)
    period = meta.get("period") or {}
    scenarios = config.get_backtesting_scenarios()
    if scenario_id not in scenarios:
        raise ValueError(f"Szenario {scenario_id!r} nicht in backtesting_scenarios.json.")
    scenario_params = dict(scenarios[scenario_id])
    cache = cache or HistoricalDataCache()
    cache.load()
    prices_df = _load_prices_for_anchor(anchor, period)
    battery_params = _scenario_to_battery_params(scenario_params)
    feed_in_settings = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)

    (
        chart_rows,
        matrix,
        step_meta,
        _end_soc,
        chart_rows_full,
        matrix_full,
        sunrise_soc_min_index,
    ) = _simulate_anchor_step(
        anchor,
        initial_soc,
        horizon_mode=horizon_mode,
        cache=cache,
        prices_df=prices_df,
        scenario_params=scenario_params,
        battery_params=battery_params,
        feed_in_settings=feed_in_settings,
        hours_done=0,
        collect_cbc=False,
        collect_full_horizon=True,
    )

    return build_window_snapshot(
        window_anchor=anchor,
        scenario_id=scenario_id,
        horizon_mode=horizon_mode,
        kind="on_demand",
        initial_soc=initial_soc,
        meta=step_meta,
        chart_rows_24h=chart_rows,
        matrix_24h=matrix,
        chart_rows_full=chart_rows_full,
        matrix_full=matrix_full,
        sunrise_soc_min_index=sunrise_soc_min_index,
        scenario_params=scenario_params,
        battery_params=battery_params,
    )


def cache_key_for_window(
    window_anchor: str,
    scenario_id: str,
    horizon_mode: str,
) -> tuple[str, str, str]:
    return (
        normalize_window_anchor_key(window_anchor),
        scenario_id,
        horizon_mode,
    )

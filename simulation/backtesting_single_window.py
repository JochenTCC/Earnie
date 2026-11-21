"""Einzelnes Backtesting-Fenster on-demand (Abweichungs-Kalender)."""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

import config
from data.edibert_market_range import load_market_prices
from simulation.backtesting_snapshots import build_window_snapshot, normalize_window_anchor_key
from simulation.engine import (
    HistoricalDataCache,
    _scenario_to_battery_params,
    _simulate_anchor_step,
    window_slot_datetimes,
)
from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW, parse_horizon_mode

logger = logging.getLogger(__name__)

# Start SoC of the year run (``simulate_backtesting``'s default): the first window of the
# period starts with it, its start slot lies before the first booked slot.
RUN_START_SOC = 50.0


def _window_start_slot(anchor: datetime, scenario_id: str, horizon_mode: str) -> pd.Timestamp:
    """First booked slot of the window: anchor − 24 h, or the sunrise book start."""
    if parse_horizon_mode(horizon_mode) != SUNRISE_WINDOW:
        return pd.Timestamp(window_slot_datetimes(anchor)[0])
    from simulation.backtesting_horizon import (
        naive_backtesting_slot,
        resolve_sunrise_book_step_for_scenario,
    )

    scenarios = config.get_backtesting_scenarios()
    if scenario_id not in scenarios:
        raise ValueError(f"Szenario {scenario_id!r} nicht in backtesting_scenarios.json.")
    step = resolve_sunrise_book_step_for_scenario(anchor, scenarios[scenario_id])
    return pd.Timestamp(naive_backtesting_slot(step.book_slots[0]))


def initial_soc_for_anchor(
    anchor: datetime,
    scenario_id: str,
    hourly_df: pd.DataFrame,
    *,
    horizon_mode: str = FIXED_24H,
) -> float:
    """SoC at the window's first booked slot, from backtesting.csv.

    Before the first booked slot of the scenario: ``RUN_START_SOC``, as in the year run.
    Raises ``ValueError`` when the series has no SoC for that slot.
    """
    start_slot = _window_start_slot(anchor, scenario_id, horizon_mode)
    if hourly_df is None or hourly_df.empty or "sim_soc" not in hourly_df.columns:
        raise ValueError("Backtesting-Log ohne SoC-Reihe: Start-SoC des Fensters unbekannt.")
    part = hourly_df.loc[hourly_df["scenario_id"] == scenario_id]
    if part.empty:
        raise ValueError(f"Backtesting-Log ohne Reihe für {scenario_id!r}.")
    stamps = pd.to_datetime(part["ts"])
    if start_slot < stamps.min():
        return RUN_START_SOC
    match = part.loc[stamps == start_slot]
    if match.empty:
        raise ValueError(
            f"Backtesting-Log ohne SoC für {start_slot} (Szenario {scenario_id!r}): "
            "Start-SoC des Fensters unbekannt."
        )
    return float(match.iloc[0]["sim_soc"])


# Days of prices loaded around the anchor: the sunrise window plans from SA₀ (about two days
# before the anchor) and its full horizon reaches past the anchor; fixed_24h needs [anchor−24h, anchor).
_PRICE_DAYS_BEFORE_ANCHOR = 3
_PRICE_DAYS_AFTER_ANCHOR = 2
# Required price coverage before the anchor (start of the planning window, SA₀ or anchor−24h).
_REQUIRED_PRICE_DAYS_BEFORE_ANCHOR = 2


def _load_prices_for_anchor(
    anchor: datetime,
    *,
    market_zone: str | None = None,
) -> pd.DataFrame:
    """Day-ahead prices for the days around the window anchor (the anchor's own dates).

    The year run's ``backtesting_year`` is the year of the period start; a period across a
    year end (e.g. 2025-11 … 2026-10) must not load the anchor's month in that year.
    """
    sim_cfg = config.get_scenario_explorer_conf()
    anchor_naive = _naive_timestamp(anchor)
    anchor_day = anchor_naive.normalize()
    start = anchor_day - pd.Timedelta(days=_PRICE_DAYS_BEFORE_ANCHOR)
    end = anchor_day + pd.Timedelta(days=_PRICE_DAYS_AFTER_ANCHOR)
    prices_df = load_market_prices(
        start,
        end,
        sim_cfg,
        timeout=config.get_global_timeout(default=30),
        market_zone=market_zone,
    )
    _require_price_coverage(prices_df, anchor_naive)
    return prices_df


def _naive_timestamp(value: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def _require_price_coverage(prices_df: pd.DataFrame, anchor_naive: pd.Timestamp) -> None:
    """Fail loud when the loaded prices do not cover the window.

    ``epex_prices_for_slots`` would otherwise fill every missing slot with the nearest
    sample, i.e. one constant price for the whole window.
    """
    index = prices_df.index
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    required_start = anchor_naive.normalize() - pd.Timedelta(days=_REQUIRED_PRICE_DAYS_BEFORE_ANCHOR)
    required_last = anchor_naive.floor("h") - pd.Timedelta(hours=1)
    if index.min() > required_start or index.max() < required_last:
        raise ValueError(
            f"Börsenpreise decken das Fenster {required_start} – {anchor_naive} nicht ab "
            f"(geladen: {index.min()} – {index.max()})."
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
    del meta  # prices follow the anchor's own dates, not the run period (see _load_prices_for_anchor)
    horizon_mode = parse_horizon_mode(horizon_mode)
    scenarios = config.get_backtesting_scenarios()
    if scenario_id not in scenarios:
        raise ValueError(f"Szenario {scenario_id!r} nicht in backtesting_scenarios.json.")
    scenario_params = dict(scenarios[scenario_id])
    cache = cache or HistoricalDataCache()
    cache.load()
    prices_df = _load_prices_for_anchor(
        anchor,
        market_zone=scenario_params.get("market_zone"),
    )
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
    # Match year-run engine: standby is subtracted in plausibility baseload check.
    if isinstance(battery_params, list):
        step_meta["standby_power_kw"] = float(
            sum(float(b.get("standby_power_kw") or 0.0) for b in battery_params)
        )
    else:
        step_meta["standby_power_kw"] = float(
            battery_params.get("standby_power_kw") or 0.0
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

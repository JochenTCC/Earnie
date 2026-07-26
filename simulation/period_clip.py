"""Clip SE/backtesting result series to the configured calendar period."""
from __future__ import annotations

import pandas as pd


def _naive_ts(value: pd.Timestamp | str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_localize(None)
    return stamp


def clip_results_to_period(
    df: pd.DataFrame,
    start: pd.Timestamp | str,
    end: pd.Timestamp | str,
) -> pd.DataFrame:
    """
    Keep hours in ``[start 00:00, end 23:00]`` (inclusive).

    Sunrise / fixed_24h book windows may spill before ``start`` or after ``end``;
    those stub months must not receive monthly fees.
    """
    if df.empty:
        return df
    start_ts = _naive_ts(start).normalize()
    end_ts = _naive_ts(end).normalize() + pd.Timedelta(hours=23)
    out = df
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        out = df.copy()
        out.index = index.tz_localize(None)
    clipped = out.loc[(out.index >= start_ts) & (out.index <= end_ts)]
    clipped.index.name = out.index.name or "ts"
    return clipped


def clip_results_map_to_period(
    results: dict[str, pd.DataFrame],
    start: pd.Timestamp | str,
    end: pd.Timestamp | str,
) -> dict[str, pd.DataFrame]:
    return {
        scenario_id: clip_results_to_period(df, start, end)
        for scenario_id, df in results.items()
    }

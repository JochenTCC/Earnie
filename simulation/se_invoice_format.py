"""Formatting and monthly series helpers of the SE invoice markdown (split from se_invoice_markdown)."""
from __future__ import annotations

import re
import pandas as pd


def _safe_filename(scenario_id: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", str(scenario_id).strip(), flags=re.UNICODE)
    return cleaned.strip("._") or "scenario"


def _fmt_eur(value: float) -> str:
    return f"{float(value):.2f} €"


def _fmt_kwh(value: float) -> str:
    return f"{float(value):.1f} kWh"


def _fmt_cent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}"


def _series_or_zero(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns and not df.empty:
        return df[column].fillna(0.0).astype(float)
    return pd.Series(0.0, index=df.index, dtype=float)


def _series_or_nan(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns and not df.empty:
        return pd.to_numeric(df[column], errors="coerce")
    return pd.Series(float("nan"), index=df.index, dtype=float)


def _month_keys(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    return sorted({pd.Timestamp(ts).strftime("%Y-%m") for ts in df.index})


def _month_mask(series: pd.Series, month_key: str) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    return pd.Series(
        pd.DatetimeIndex(series.index).strftime("%Y-%m") == month_key,
        index=series.index,
    )


def _monthly_sum(series: pd.Series, month_key: str) -> float:
    if series.empty:
        return 0.0
    return float(series.loc[_month_mask(series, month_key)].sum())

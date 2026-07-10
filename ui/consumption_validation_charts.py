"""Vergleich Ist-Verbrauchs-CSV mit modelliertem Hausprofil."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go

from data.consumption_profiles import build_modeled_hourly_kw_profile
from house_config.consumption_csv import load_hourly_profile_csv

_WEEKDAY_LABELS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _parse_csv_timestamp(ts_raw: str) -> datetime:
    return datetime.fromisoformat(ts_raw.replace(" ", "T", 1)[:19])


def csv_series_to_monthly_kwh(series: list[tuple[str, float]]) -> dict[str, float]:
    """Aggregiert stündliche kW-Werte zu Monatssummen in kWh."""
    monthly: dict[str, float] = defaultdict(float)
    for ts_raw, power_kw in series:
        ts = _parse_csv_timestamp(ts_raw)
        key = f"{ts.year}-{ts.month:02d}"
        monthly[key] += float(power_kw)
    return dict(sorted(monthly.items()))


def modeled_monthly_kwh(profile: dict, *, hours: int = 8760) -> dict[str, float]:
    """Monatssummen aus modelliertem Profil (ohne total_profile_csv)."""
    from datetime import timedelta

    hourly = build_modeled_hourly_kw_profile(profile, hours=hours)
    monthly: dict[str, float] = defaultdict(float)
    start = datetime(2023, 1, 1, 0, 0, 0)
    for index, power_kw in enumerate(hourly):
        ts = start + timedelta(hours=index)
        key = f"{ts.year}-{ts.month:02d}"
        monthly[key] += float(power_kw)
    return dict(sorted(monthly.items()))


def load_csv_monthly_kwh(csv_path: str) -> dict[str, float]:
    series = load_hourly_profile_csv(csv_path)
    return csv_series_to_monthly_kwh(series)


def cons_dataframe_to_series(df: pd.DataFrame) -> list[tuple[str, float]]:
    """Mappt cons_data_hourly DataFrame (total_kw) auf (timestamp, kW)-Serie."""
    if df.empty:
        return []
    series: list[tuple[str, float]] = []
    for ts, row in df.iterrows():
        series.append((ts.strftime("%Y-%m-%d %H:%M:%S"), float(row["total_kw"])))
    return series


def cons_dataframe_to_navigation_series(df: pd.DataFrame) -> list[tuple[str, float]]:
    """Timestamp-Serie für KW-Navigation aus cons_data DataFrame-Index."""
    if df.empty:
        return []
    return [(ts.strftime("%Y-%m-%d %H:%M:%S"), 0.0) for ts in df.index]


_CONS_DATA_PLOT_COLUMNS = ("total_kw", "baseload_kw", "pv_kw")


def slice_cons_dataframe_for_iso_week(
    df: pd.DataFrame,
    *,
    iso_year: int,
    iso_week: int,
) -> pd.DataFrame:
    """Schneidet cons_data-Zeilen für eine ISO-Kalenderwoche."""
    if df.empty:
        return df
    rows: list[pd.Series] = []
    index_labels: list[datetime] = []
    for ts, row in df.iterrows():
        ts_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if ts_dt.isocalendar()[:2] != (iso_year, iso_week):
            continue
        rows.append(row)
        index_labels.append(ts_dt)
    if not rows:
        return pd.DataFrame(columns=df.columns)
    sliced = pd.DataFrame(rows)
    sliced.index = pd.DatetimeIndex(index_labels)
    return sliced


def cons_data_columns_timeseries_chart(
    df: pd.DataFrame,
    *,
    iso_year: int,
    iso_week: int,
) -> go.Figure:
    """Stündliche Verläufe total_kw, baseload_kw, pv_kw für eine ISO-KW."""
    week_df = slice_cons_dataframe_for_iso_week(df, iso_year=iso_year, iso_week=iso_week)
    if week_df.empty:
        raise ValueError(f"Keine Daten für {format_iso_week_label(iso_year, iso_week)}.")
    x_labels = [
        _format_hour_axis_label(ts.strftime("%Y-%m-%d %H:%M:%S"))
        for ts in week_df.index
    ]
    fig = go.Figure()
    for column in _CONS_DATA_PLOT_COLUMNS:
        if column not in week_df.columns:
            continue
        fig.add_scatter(
            name=column,
            x=x_labels,
            y=week_df[column].astype(float).tolist(),
            mode="lines",
        )
    fig.update_layout(
        title=f"Stündlicher Verlauf — KW {iso_week}/{iso_year}",
        xaxis_title="Zeit",
        yaxis_title="kW",
        height=360,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def cons_data_monthly_kwh(df: pd.DataFrame) -> dict[str, float]:
    return csv_series_to_monthly_kwh(cons_dataframe_to_series(df))


def iso_weeks_in_series(series: list[tuple[str, float]]) -> list[tuple[int, int]]:
    """ISO-Kalenderwochen (Jahr, Woche) in Reihenfolge des ersten Vorkommens."""
    weeks: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for ts_raw, _ in series:
        iso_year, iso_week, _ = _parse_csv_timestamp(ts_raw).isocalendar()
        key = (iso_year, iso_week)
        if key not in seen:
            seen.add(key)
            weeks.append(key)
    return weeks


def format_iso_week_label(iso_year: int, iso_week: int) -> str:
    """Anzeige-Label z. B. KW 12/2024 (18.03.–24.03.2024)."""
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    sunday = date.fromisocalendar(iso_year, iso_week, 7)
    return (
        f"KW {iso_week}/{iso_year} "
        f"({monday.strftime('%d.%m.')}–{sunday.strftime('%d.%m.%Y')})"
    )


def slice_series_for_iso_week(
    series: list[tuple[str, float]],
    modeled: list[float],
    iso_year: int,
    iso_week: int,
) -> tuple[list[str], list[float], list[float]]:
    """Schneidet Ist- und Modellwerte für eine ISO-Kalenderwoche (indexbasiert)."""
    timestamps: list[str] = []
    actual: list[float] = []
    modeled_slice: list[float] = []
    for index, (ts_raw, power_kw) in enumerate(series):
        ts = _parse_csv_timestamp(ts_raw)
        if ts.isocalendar()[:2] != (iso_year, iso_week):
            continue
        timestamps.append(ts_raw)
        actual.append(float(power_kw))
        modeled_slice.append(float(modeled[index]))
    return timestamps, actual, modeled_slice


def _format_hour_axis_label(ts_raw: str) -> str:
    ts = _parse_csv_timestamp(ts_raw)
    weekday = _WEEKDAY_LABELS[ts.weekday()]
    return f"{weekday} {ts:%H:%M}"


def monthly_comparison_chart(
    actual: dict[str, float],
    modeled: dict[str, float],
) -> go.Figure:
    months = sorted(set(actual) | set(modeled))
    actual_vals = [actual.get(month, 0.0) for month in months]
    modeled_vals = [modeled.get(month, 0.0) for month in months]
    fig = go.Figure()
    fig.add_bar(name="Ist (CSV)", x=months, y=actual_vals)
    fig.add_bar(name="Modell", x=months, y=modeled_vals)
    fig.update_layout(
        barmode="group",
        title="Monatsverbrauch: Ist vs. Modell (kWh)",
        xaxis_title="Monat",
        yaxis_title="kWh",
        height=380,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def timeseries_comparison_from_series(
    series: list[tuple[str, float]],
    profile: dict,
    *,
    iso_year: int,
    iso_week: int,
    actual_label: str = "Ist (CSV)",
) -> go.Figure:
    """Vergleicht Ist-Serie und Modell für eine ISO-Kalenderwoche."""
    modeled = build_modeled_hourly_kw_profile(profile, hours=len(series))
    timestamps, actual, modeled_slice = slice_series_for_iso_week(
        series, modeled, iso_year, iso_week
    )
    if not actual:
        raise ValueError(f"Keine Daten für {format_iso_week_label(iso_year, iso_week)}.")
    x_labels = [_format_hour_axis_label(ts_raw) for ts_raw in timestamps]
    fig = go.Figure()
    fig.add_scatter(name=actual_label, x=x_labels, y=actual, mode="lines")
    fig.add_scatter(name="Modell", x=x_labels, y=modeled_slice, mode="lines")
    fig.update_layout(
        title=f"Stündlicher Verlauf — KW {iso_week}/{iso_year}",
        xaxis_title="Zeit",
        yaxis_title="kW",
        height=360,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def timeseries_comparison_chart(
    csv_path: str,
    profile: dict,
    *,
    iso_year: int,
    iso_week: int,
) -> go.Figure:
    """Vergleicht Ist und Modell für eine ISO-Kalenderwoche."""
    series = load_hourly_profile_csv(csv_path)
    return timeseries_comparison_from_series(
        series,
        profile,
        iso_year=iso_year,
        iso_week=iso_week,
    )

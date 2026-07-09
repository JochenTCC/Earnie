"""Vergleich Ist-Verbrauchs-CSV mit modelliertem Hausprofil."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

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


def timeseries_comparison_chart(
    csv_path: str,
    profile: dict,
    *,
    iso_year: int,
    iso_week: int,
) -> go.Figure:
    """Vergleicht Ist und Modell für eine ISO-Kalenderwoche."""
    series = load_hourly_profile_csv(csv_path)
    modeled = build_modeled_hourly_kw_profile(profile, hours=len(series))
    timestamps, actual, modeled_slice = slice_series_for_iso_week(
        series, modeled, iso_year, iso_week
    )
    if not actual:
        raise ValueError(f"Keine CSV-Daten für {format_iso_week_label(iso_year, iso_week)}.")
    x_labels = [_format_hour_axis_label(ts_raw) for ts_raw in timestamps]
    fig = go.Figure()
    fig.add_scatter(name="Ist (CSV)", x=x_labels, y=actual, mode="lines")
    fig.add_scatter(name="Modell", x=x_labels, y=modeled_slice, mode="lines")
    fig.update_layout(
        title=f"Stündlicher Verlauf — KW {iso_week}/{iso_year}",
        xaxis_title="Zeit",
        yaxis_title="kW",
        height=360,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig

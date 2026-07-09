"""Vergleich Ist-Verbrauchs-CSV mit modelliertem Hausprofil."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import plotly.graph_objects as go

from data.consumption_profiles import build_modeled_hourly_kw_profile
from house_config.consumption_csv import load_hourly_profile_csv


def csv_series_to_monthly_kwh(series: list[tuple[str, float]]) -> dict[str, float]:
    """Aggregiert stündliche kW-Werte zu Monatssummen in kWh."""
    monthly: dict[str, float] = defaultdict(float)
    for ts_raw, power_kw in series:
        ts = datetime.fromisoformat(ts_raw.replace(" ", "T", 1)[:19])
        key = f"{ts.year}-{ts.month:02d}"
        monthly[key] += float(power_kw)
    return dict(sorted(monthly.items()))


def modeled_monthly_kwh(profile: dict, *, hours: int = 8760) -> dict[str, float]:
    """Monatssummen aus modelliertem Profil (ohne total_profile_csv)."""
    from datetime import datetime, timedelta

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
    max_points: int = 168,
) -> go.Figure:
    """Vergleicht die ersten max_points Stunden (Default: eine Woche)."""
    series = load_hourly_profile_csv(csv_path)
    actual = [kw for _, kw in series[:max_points]]
    modeled = build_modeled_hourly_kw_profile(profile, hours=max(len(actual), max_points))
    modeled = modeled[: len(actual)]
    hours = list(range(len(actual)))
    fig = go.Figure()
    fig.add_scatter(name="Ist (CSV)", x=hours, y=actual, mode="lines")
    fig.add_scatter(name="Modell", x=hours, y=modeled, mode="lines")
    fig.update_layout(
        title=f"Stündlicher Verlauf (erste {len(actual)} h)",
        xaxis_title="Stunde",
        yaxis_title="kW",
        height=360,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig

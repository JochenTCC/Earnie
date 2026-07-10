"""Plotly-Charts für die gemeinsame Verbrauchs-UI."""
from __future__ import annotations

import plotly.graph_objects as go

from ui.chart_colors import COLOR_BASELOAD, CONSUMER_PALETTE
from ui.consumption_display.aggregation import (
    monthly_kwh_by_consumer,
    monthly_pv_kwh,
    monthly_total_kwh,
    parse_timestamp,
)
from ui.consumption_display.types import ConsumptionSeriesBundle
from ui.consumption_validation_charts import format_iso_week_label

_PV_COLOR = "#f4c430"
_BASELOAD_KEY = "baseload"


def _consumer_color(consumer_id: str, index: int) -> str:
    if consumer_id == _BASELOAD_KEY:
        return COLOR_BASELOAD
    return CONSUMER_PALETTE[index % len(CONSUMER_PALETTE)]


def _consumer_label(bundle: ConsumptionSeriesBundle, consumer_id: str) -> str:
    if consumer_id == _BASELOAD_KEY:
        return bundle.consumer_labels.get(_BASELOAD_KEY, "Basislast")
    return bundle.consumer_labels.get(consumer_id, consumer_id)


def _stack_keys(bundle: ConsumptionSeriesBundle) -> list[str]:
    return [*bundle.consumer_ids(), _BASELOAD_KEY]


def stacked_monthly_chart(
    bundle: ConsumptionSeriesBundle,
    *,
    title: str = "Monatsverbrauch (kWh)",
) -> go.Figure:
    """Gestapelte Monatsbalken je Verbraucher + Basislast; PV separat."""
    months = sorted(monthly_total_kwh(bundle).keys())
    by_month = monthly_kwh_by_consumer(bundle)
    pv_monthly = monthly_pv_kwh(bundle)
    fig = go.Figure()
    stack_keys = _stack_keys(bundle)
    for index, key in enumerate(stack_keys):
        if key == _BASELOAD_KEY:
            values = [by_month.get(month, {}).get(_BASELOAD_KEY, 0.0) for month in months]
            label = _consumer_label(bundle, _BASELOAD_KEY)
            color = COLOR_BASELOAD
        else:
            values = [by_month.get(month, {}).get(key, 0.0) for month in months]
            label = _consumer_label(bundle, key)
            color = _consumer_color(key, index)
        fig.add_bar(name=label, x=months, y=values, marker_color=color)
    if pv_monthly:
        fig.add_scatter(
            name="PV-Erzeugung",
            x=months,
            y=[pv_monthly.get(month, 0.0) for month in months],
            mode="lines+markers",
            line=dict(color=_PV_COLOR, width=2),
            yaxis="y",
        )
    fig.update_layout(
        barmode="stack",
        title=title,
        xaxis_title="Monat",
        yaxis_title="kWh",
        height=380,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def csv_validation_monthly_chart(
    bundle: ConsumptionSeriesBundle,
    actual_monthly: dict[str, float],
) -> go.Figure:
    """Gruppiert: Ist-Gesamt vs. Modell gestapelt (je Verbraucher + Basislast)."""
    months = sorted(set(actual_monthly) | set(monthly_total_kwh(bundle).keys()))
    by_month = monthly_kwh_by_consumer(bundle)
    fig = go.Figure()
    fig.add_bar(
        name="Ist (CSV)",
        x=months,
        y=[actual_monthly.get(month, 0.0) for month in months],
        marker_color="#6b8cae",
        offsetgroup="ist",
    )
    for index, key in enumerate(_stack_keys(bundle)):
        if key == _BASELOAD_KEY:
            values = [by_month.get(month, {}).get(_BASELOAD_KEY, 0.0) for month in months]
            label = f"Modell — {_consumer_label(bundle, _BASELOAD_KEY)}"
            color = COLOR_BASELOAD
        else:
            values = [by_month.get(month, {}).get(key, 0.0) for month in months]
            label = f"Modell — {_consumer_label(bundle, key)}"
            color = _consumer_color(key, index)
        fig.add_bar(
            name=label,
            x=months,
            y=values,
            marker_color=color,
            offsetgroup="model",
        )
    fig.update_layout(
        barmode="stack",
        title="Monatsverbrauch: Ist vs. Modell (kWh)",
        xaxis_title="Monat",
        yaxis_title="kWh",
        height=380,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def timeseries_chart(
    bundle: ConsumptionSeriesBundle,
    *,
    title: str,
) -> go.Figure:
    """Stündlicher Verlauf: Linien je Verbraucher + Basislast; PV und Ist separat."""
    if not bundle.timestamps:
        raise ValueError("Keine Daten für den gewählten Zeitraum.")
    x_values = [parse_timestamp(ts_raw) for ts_raw in bundle.timestamps]
    fig = go.Figure()
    stack_keys = _stack_keys(bundle)
    for index, key in enumerate(stack_keys):
        if key == _BASELOAD_KEY:
            values = bundle.baseload
            label = _consumer_label(bundle, _BASELOAD_KEY)
            color = COLOR_BASELOAD
        else:
            values = bundle.consumer_series[key]
            label = _consumer_label(bundle, key)
            color = _consumer_color(key, index)
        fig.add_scatter(
            name=label,
            x=x_values,
            y=values,
            mode="lines",
            line=dict(width=1.5, color=color),
        )
    if bundle.pv is not None:
        fig.add_scatter(
            name="PV-Erzeugung",
            x=x_values,
            y=bundle.pv,
            mode="lines",
            line=dict(color=_PV_COLOR, width=2),
        )
    if bundle.actual_total is not None:
        fig.add_scatter(
            name="Ist (CSV)",
            x=x_values,
            y=bundle.actual_total,
            mode="lines",
            line=dict(color="#6b8cae", width=2, dash="dash"),
        )
    fig.update_layout(
        title=title,
        xaxis_title="Zeit",
        yaxis_title="kW",
        height=360,
        margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(
            type="date",
            tickformat="%a %d.%m.",
            dtick=86_400_000,
        ),
    )
    return fig


def week_timeseries_chart(
    bundle: ConsumptionSeriesBundle,
    *,
    iso_year: int,
    iso_week: int,
) -> go.Figure:
    from ui.consumption_display.aggregation import slice_bundle_for_iso_week

    sliced = slice_bundle_for_iso_week(bundle, iso_year=iso_year, iso_week=iso_week)
    return timeseries_chart(
        sliced,
        title=f"Stündlicher Verlauf — {format_iso_week_label(iso_year, iso_week)}",
    )


def stack_monthly_sum_matches_total(
    bundle: ConsumptionSeriesBundle,
    *,
    tolerance: float = 1e-6,
) -> bool:
    """Prüft, ob gestapelte Monatswerte ≈ Gesamtverbrauch sind."""
    totals = monthly_total_kwh(bundle)
    by_month = monthly_kwh_by_consumer(bundle)
    for month, total in totals.items():
        stack_sum = sum(by_month.get(month, {}).values())
        if abs(stack_sum - total) > tolerance:
            return False
    return True

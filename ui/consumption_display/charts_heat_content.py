"""Live heat-content chart (split from charts)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go

from ui.consumption_display.aggregation import (
    parse_timestamp,
)
from ui.consumption_display.charts_color import _color_with_alpha

if TYPE_CHECKING:
    from ui.consumption_display.heat_content_history import LiveHeatContentForecastFan


_HC_SIM_COLOR = "#2a6f97"


_HC_MEAS_COLOR = "#bc4749"


_HC_FAN_ALPHA_MIN = 0.15


_HC_FAN_ALPHA_MAX = 0.85


def _add_heat_content_forecast_fan(
    fig: go.Figure,
    forecast_fan: LiveHeatContentForecastFan,
) -> int:
    """Overlay latest hourly Q-forecast lines; returns number of fan traces added."""
    added = 0
    for key, lines in forecast_fan.lines_by_key.items():
        if not lines:
            continue
        label = forecast_fan.labels.get(key, key)
        count = len(lines)
        for index, line in enumerate(lines):
            if count <= 1:
                alpha = _HC_FAN_ALPHA_MAX
            else:
                alpha = _HC_FAN_ALPHA_MIN + (
                    (_HC_FAN_ALPHA_MAX - _HC_FAN_ALPHA_MIN) * index / (count - 1)
                )
            is_newest = index == count - 1
            fig.add_scatter(
                name=f"{label} Prognose (letzte 12 h)",
                x=line.x_timestamps,
                y=line.q_sim_kwh,
                mode="lines",
                line=dict(
                    color=_color_with_alpha(_HC_SIM_COLOR, alpha),
                    width=2 if is_newest else 1,
                ),
                showlegend=is_newest,
                legendgroup=f"hc_fan_{key}",
                hovertemplate="%{x|%d.%m. %H:%M}<br>%{y:.2f} kWh<extra></extra>",
            )
            added += 1
    return added


def live_heat_content_chart(
    timestamps: list[str],
    *,
    q_sim_by_key: dict[str, list[float | None]],
    q_meas_by_key: dict[str, list[float | None]],
    labels: dict[str, str],
    title: str = "Wärmeinhalt",
    forecast_fan: LiveHeatContentForecastFan | None = None,
) -> go.Figure | None:
    """Live-log Q_sim (solid) vs Q_meas (dashed) in kWh. Returns None when empty."""
    if not timestamps or not q_sim_by_key:
        return None
    x_values = [parse_timestamp(ts) for ts in timestamps]
    fig = go.Figure()
    has_meas = False
    has_sim = False
    for key, sim_values in q_sim_by_key.items():
        if len(sim_values) != len(x_values):
            continue
        label = labels.get(key, key)
        if any(v is not None for v in sim_values):
            has_sim = True
            fig.add_scatter(
                name=f"{label} (Sim)",
                x=x_values,
                y=sim_values,
                mode="lines",
                line=dict(color=_HC_SIM_COLOR, width=2),
                connectgaps=False,
            )
        measured = q_meas_by_key.get(key) or []
        if measured and len(measured) == len(x_values) and any(
            v is not None for v in measured
        ):
            has_meas = True
            fig.add_scatter(
                name=f"{label} (Ist)",
                x=x_values,
                y=measured,
                mode="lines",
                line=dict(color=_HC_MEAS_COLOR, width=2, dash="dash"),
                connectgaps=False,
            )
    fan_traces = 0
    if forecast_fan is not None and forecast_fan.has_lines():
        fan_traces = _add_heat_content_forecast_fan(fig, forecast_fan)
    if not fig.data:
        return None
    fig.update_layout(
        title=title,
        xaxis_title="Zeit",
        yaxis_title="kWh",
        height=320,
        margin=dict(l=40, r=20, t=50, b=40),
        xaxis=dict(type="date", tickformat="%a %d.%m.", dtick=86_400_000),
    )
    fig.layout.meta = {
        "has_measured": has_meas,
        "has_sim": has_sim,
        "forecast_fan_traces": fan_traces,
        "forecast_fan_horizon_h": (
            forecast_fan.common_horizon_h if forecast_fan is not None else 0
        ),
    }
    return fig

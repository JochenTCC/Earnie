"""Chart-Dekorationen: Zonen, Marker, Legende, Titel."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

import pandas as pd
import plotly.graph_objects as go

from ui.chart_consumer_stack import _chart_flex_consumers
from optimizer.deviation_eval import DeviationEvent
from runtime_store.history_timeline import SLOT_MISSING
from ui.chart_colors import (
    CHART_MARKER_NOW_COLOR,
    CHART_MARKER_SUNRISE_COLOR,
    CHART_MISSING_SLOT_FILL,
    COLOR_COST_BASELINE,
    COLOR_COST_OPTIMIZED,
    COLOR_COST_SAVINGS,
    COLOR_COST_SAVINGS_NEGATIVE,
)
from ui.chart_slot_axis import (
    ChartSlotAxis,
    _LINE_ANCHOR_SLOT_CENTER,
    _axis_x_bounds,
    _forecast_zone_x0,
    _history_zone_x1,
    _slot_time_in_chart,
    _zone_slot_left,
    _zone_slot_right,
)

_DEVIATION_MARKER_SIZE = 11


_DEVIATION_Y_STACK_FACTOR = 0.06


@dataclass(frozen=True)
class ChartSunMarkers:
    now_x: datetime | None
    sa0_x: datetime | None
    sa1_x: datetime | None
    sa2_x: datetime | None


def _sunrise_chart_title(chart: UiChartWindow) -> str:
    return (
        "Sonnenaufgang→Sonnenaufgang "
        f"({chart.start.strftime('%d.%m.%Y %H:%M')} – "
        f"{chart.end.strftime('%d.%m.%Y %H:%M')})"
    )


_CHART2_S2_TITLE = "Kumulierte Kosten & Verbrauch (Sonnenaufgang→Sonnenaufgang)"


_CHART2_S2_HELP = (
    "Grauer Bereich: **Ist bisher** (blau, kumuliert aus Produktiv-Log) und "
    "**Ersparnis bisher** (geplante BL−Opt-Differenz der abgelaufenen Slots, "
    "pro SA-Tag). Neutral/Grün: **Prognose** (BL Ziel / optimiert, an Ist an der "
    "Log-Grenze angeschlossen). Kennzahlen BL Ziel / Optimiert: **pro SA-Tag** "
    "(Mobil: sichtbarer Tag; Desktop SA₀→SA₂: zwei Spalten). Am laufenden Tag "
    "zusätzlich **Ersparnis bisher** (SA→Jetzt) und **Ersparnis erwartet** "
    "(ganzer SA-Tag). Fehlende Log-Slots: orange, Lücken in Ist-Kurven."
)


def _mask_missing_log_slots(
    df: pd.DataFrame,
    slot_qualities: tuple[str, ...] | None,
) -> pd.DataFrame:
    """Setzt Messwerte in fehlenden Log-Slots auf NaN (Lücken in Linien)."""
    if not slot_qualities or len(slot_qualities) != len(df):
        return df
    masked = df.copy()
    numeric_cols = [
        "PV-Prognose (kW)",
        "Verbrauch-Prognose (kW)",
        "Geplante Batterie-Aktion (kW)",
        "Netzbezug (kW)",
        "Simulierter SoC (%)",
        "Strompreis (Cent/kWh)",
    ]
    for consumer in _chart_flex_consumers():
        numeric_cols.append(f"{consumer['name']} (kW)")
    for index, quality in enumerate(slot_qualities):
        if quality != SLOT_MISSING:
            continue
        for col in numeric_cols:
            if col in masked.columns:
                masked.iloc[index, masked.columns.get_loc(col)] = float("nan")
    return masked


def _anchor_x_in_chart_window(chart: UiChartWindow, anchor: datetime) -> datetime | None:
    """SA-Anker als Marker, wenn er im sichtbaren Chart-Fenster liegt."""
    if anchor < chart.start or anchor > chart.end:
        return None
    return anchor


def build_sun_markers(
    chart: UiChartWindow,
    now: datetime,
    planning_window,
    *,
    slot_datetimes: tuple[datetime, ...] | None = None,
    show_now: bool = True,
) -> ChartSunMarkers:
    slots = slot_datetimes or chart.slot_datetimes
    now_x: datetime | None = None
    if show_now:
        if slots and chart.start <= now <= chart.end + timedelta(hours=1):
            now_x = now
        else:
            now_x = _slot_time_in_chart(slots, now)
    return ChartSunMarkers(
        now_x=now_x,
        sa0_x=_anchor_x_in_chart_window(chart, chart.sa0),
        sa1_x=_anchor_x_in_chart_window(chart, chart.sa1),
        sa2_x=_anchor_x_in_chart_window(chart, chart.sa2),
    )


def _add_zone_backgrounds(
    fig: go.Figure,
    zones,
    axis: ChartSlotAxis,
    *,
    range_start: datetime | None = None,
) -> None:
    x_left, x_right = _axis_x_bounds(axis, range_start=range_start)
    history_fills_axis = (
        zones.history.fill_color is not None
        and zones.forecast.fill_color is None
        and zones.live_plan.end <= zones.history.end
    )
    if (
        zones.history.fill_color
        and zones.history.end > zones.history.start
    ):
        fig.add_vrect(
            x0=x_left,
            x1=_history_zone_x1(
                axis,
                zones.history.end,
                x_right=x_right,
                fill_to_axis_end=history_fills_axis,
            ),
            fillcolor=zones.history.fill_color,
            line_width=0,
            layer="below",
        )
    if (
        zones.forecast.fill_color
        and zones.forecast.end > zones.forecast.start
    ):
        fig.add_vrect(
            x0=_forecast_zone_x0(axis, zones.forecast.start, x_left),
            x1=x_right,
            fillcolor=zones.forecast.fill_color,
            line_width=0,
            layer="below",
        )


def _add_missing_slot_backgrounds(
    fig: go.Figure,
    axis: ChartSlotAxis,
    slot_qualities: tuple[str, ...] | None,
) -> None:
    if not slot_qualities or len(slot_qualities) != len(axis.starts):
        return
    for index, quality in enumerate(slot_qualities):
        if quality != SLOT_MISSING:
            continue
        fig.add_vrect(
            x0=axis.legacy_index_time(index - 0.5),
            x1=axis.legacy_index_time(index + 0.5),
            fillcolor=CHART_MISSING_SLOT_FILL,
            line_width=0,
            layer="below",
        )


def _add_sun_markers(fig: go.Figure, markers: ChartSunMarkers) -> None:
    if markers.now_x is not None:
        fig.add_vline(
            x=markers.now_x,
            line=dict(color=CHART_MARKER_NOW_COLOR, width=1.5, dash="dot"),
            annotation_text="Jetzt",
            annotation_position="top",
        )
    for label, anchor_x in (
        ("SA₀", markers.sa0_x),
        ("SA₁", markers.sa1_x),
        ("SA₂", markers.sa2_x),
    ):
        if anchor_x is None:
            continue
        fig.add_vline(
            x=anchor_x,
            line=dict(color=CHART_MARKER_SUNRISE_COLOR, width=1.5),
            annotation_text=label,
            annotation_position="top",
        )


def _power_chart_ymax(df: pd.DataFrame) -> float:
    """Oberkante für Soll/Ist-Marker oberhalb der Leistungskurven."""
    columns = [
        "PV-Prognose (kW)",
        "Verbrauch-Prognose (kW)",
        "Geplante Batterie-Aktion (kW)",
        "Netzbezug (kW)",
    ]
    for consumer in _chart_flex_consumers():
        columns.append(f"{consumer['name']} (kW)")
    peak = 0.0
    for column in columns:
        if column not in df.columns:
            continue
        series = pd.to_numeric(df[column], errors="coerce").abs()
        if series.empty:
            continue
        value = series.max()
        if value is not None and not math.isnan(value):
            peak = max(peak, float(value))
    return max(peak, 0.5)


def build_deviation_marker_traces(
    axis: ChartSlotAxis,
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...],
    power_ymax: float,
) -> list[go.Scatter]:
    """Plotly-Scatter-Marker für Soll/Ist-Abweichungen (Epic Soll-Ist P3)."""
    if not slot_deviation_events:
        return []
    slot_count = len(axis.starts)
    if len(slot_deviation_events) != slot_count:
        return []
    traces: list[go.Scatter] = []
    base_y = power_ymax * 1.04
    step_y = max(power_ymax * _DEVIATION_Y_STACK_FACTOR, 0.08)
    for index, events in enumerate(slot_deviation_events):
        if not events:
            continue
        x_time = axis.at(index, _LINE_ANCHOR_SLOT_CENTER).iloc[0]
        for stack_index, event in enumerate(events):
            traces.append(
                go.Scatter(
                    x=[x_time],
                    y=[base_y + stack_index * step_y],
                    mode="markers",
                    marker=dict(
                        symbol=event.symbol,
                        color=event.color,
                        size=_DEVIATION_MARKER_SIZE,
                        line=dict(width=1, color="white"),
                    ),
                    name=event.label,
                    showlegend=False,
                    hovertemplate=(
                        f"<b>{event.label}</b><br>"
                        f"{event.message}"
                        f"<br><extra></extra>"
                    ),
                )
            )
    return traces


def _add_deviation_markers(
    fig: go.Figure,
    axis: ChartSlotAxis,
    plot_df: pd.DataFrame,
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...] | None,
) -> None:
    if not slot_deviation_events:
        return
    for trace in build_deviation_marker_traces(
        axis,
        slot_deviation_events,
        _power_chart_ymax(plot_df),
    ):
        fig.add_trace(trace)


_CHART_BOTTOM_MARGIN = 0


def _chart_legend() -> dict:
    return dict(
        orientation="h",
        yanchor="top",
        y=-0.22,
        x=0.5,
        xanchor="center",
        font=dict(size=10),
    )


def _collapsible_chart_layout(*, top_margin: int) -> dict:
    """Layout für Cockpit-Charts: Plotly-Legende aus, HTML-Legende darunter."""
    return dict(
        legend=dict(orientation="h"),
        showlegend=False,
        margin=dict(l=40, r=40, t=top_margin, b=_CHART_BOTTOM_MARGIN),
    )


_COST_SUMMARY_FONT_SIZE = 14


_COST_SUMMARY_LINE_SHIFT = 20


_COST_SUMMARY_Y_TOP = 1.0


_COST_SUMMARY_COLUMN_X = (0.01, 0.52)


def _savings_annotation_color(savings_euro: float) -> str:
    if savings_euro < 0:
        return COLOR_COST_SAVINGS
    if savings_euro > 0:
        return COLOR_COST_SAVINGS_NEGATIVE
    return COLOR_COST_BASELINE


def _append_summary_line(
    lines: list[dict],
    base: dict,
    summary_font: dict,
    *,
    text: str,
    line_index: int,
    color: str,
) -> int:
    lines.append(
        {
            **base,
            "text": text,
            "yshift": -line_index * _COST_SUMMARY_LINE_SHIFT,
            "font": {**summary_font, "color": color},
        }
    )
    return line_index + 1


def _cost_summary_column_annotations(
    matched_baseline_cost_euro: float,
    optimized_cost_euro: float,
    *,
    x: float = 0.01,
    label: str | None = None,
    achieved_savings_euro: float | None = None,
    show_split_savings: bool = False,
) -> list[dict]:
    """One KPI column (optional day label + BL / Optimiert / Ersparnis)."""
    savings_euro = optimized_cost_euro - matched_baseline_cost_euro
    summary_font = dict(size=_COST_SUMMARY_FONT_SIZE)
    base = dict(
        xref="paper",
        yref="y domain",
        x=x,
        y=_COST_SUMMARY_Y_TOP,
        showarrow=False,
        xanchor="left",
        yanchor="top",
        font=summary_font,
    )
    lines: list[dict] = []
    line_index = 0
    if label:
        lines.append(
            {
                **base,
                "text": label,
                "font": {**summary_font, "color": COLOR_COST_BASELINE},
            }
        )
        line_index = 1
    line_index = _append_summary_line(
        lines,
        base,
        summary_font,
        text=f"BL Ziel: {matched_baseline_cost_euro:.2f} €",
        line_index=line_index,
        color=COLOR_COST_BASELINE,
    )
    line_index = _append_summary_line(
        lines,
        base,
        summary_font,
        text=f"Optimiert: {optimized_cost_euro:.2f} €",
        line_index=line_index,
        color=COLOR_COST_OPTIMIZED,
    )
    if show_split_savings and achieved_savings_euro is not None:
        line_index = _append_summary_line(
            lines,
            base,
            summary_font,
            text=f"Ersparnis bisher: {achieved_savings_euro:+.2f} €",
            line_index=line_index,
            color=_savings_annotation_color(achieved_savings_euro),
        )
        _append_summary_line(
            lines,
            base,
            summary_font,
            text=f"Ersparnis erwartet: {savings_euro:+.2f} €",
            line_index=line_index,
            color=_savings_annotation_color(savings_euro),
        )
    else:
        _append_summary_line(
            lines,
            base,
            summary_font,
            text=f"Ersparnis: {savings_euro:+.2f} €",
            line_index=line_index,
            color=_savings_annotation_color(savings_euro),
        )
    return lines


def _cost_summary_annotations(
    matched_baseline_cost_euro: float | None = None,
    optimized_cost_euro: float | None = None,
    *,
    days: Sequence | None = None,
) -> list[dict]:
    """Plotly cost KPIs: one column (legacy floats) or one/two SA-day columns."""
    if days:
        annotations: list[dict] = []
        for index, day in enumerate(days[:2]):
            x = _COST_SUMMARY_COLUMN_X[min(index, len(_COST_SUMMARY_COLUMN_X) - 1)]
            annotations.extend(
                _cost_summary_column_annotations(
                    day.matched_baseline_cost_euro,
                    day.optimized_cost_euro,
                    x=x,
                    label=day.label if len(days) > 1 else None,
                    achieved_savings_euro=day.achieved_savings_euro,
                    show_split_savings=bool(day.show_split_savings),
                )
            )
        return annotations
    if matched_baseline_cost_euro is None or optimized_cost_euro is None:
        return []
    return _cost_summary_column_annotations(
        matched_baseline_cost_euro,
        optimized_cost_euro,
    )


def _add_cost_summary_annotations(
    fig: go.Figure,
    matched_baseline_cost_euro: float | None = None,
    optimized_cost_euro: float | None = None,
    *,
    days: Sequence | None = None,
) -> None:
    for annotation in _cost_summary_annotations(
        matched_baseline_cost_euro,
        optimized_cost_euro,
        days=days,
    ):
        fig.add_annotation(**annotation)


def _chart_range_start(chart_window: UiChartWindow | None) -> datetime | None:
    """Linker X-Rand = Fensteranfang SA₀ bzw. SA₁ (Spec ui-sunset2sunset §4)."""
    if chart_window is None:
        return None
    return chart_window.start


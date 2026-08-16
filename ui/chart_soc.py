"""SoC-Traces, ESS-Mode-Underlay und Preis auf SoC-Achse."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

import config
import pandas as pd
import plotly.graph_objects as go

from data.planning_window import normalize_hour_slot
from optimizer import battery as bat
from optimizer.slot_duration import (
    DEFAULT_DT_H,
    normalize_quarter_hour_slot,
    slot_step,
)
from runtime_store.history_timeline import CHART_IST_BATTERY_KW_COLUMN
from ui.chart_colors import (
    COLOR_ESS_UNDERLAY_CHARGE,
    COLOR_ESS_UNDERLAY_DISCHARGE,
    COLOR_ESS_UNDERLAY_HOLD,
    COLOR_SOC,
)
from ui.chart_slot_axis import (
    ChartSlotAxis,
    _chart_time_series,
    _line_plot_float,
    _optional_float,
)
from ui.chart_trace_segments import (
    _EXPORT_PRICE_COLUMN,
    _hour_prices_from_df,
    _hourly_price_hover_labels,
    _hourly_price_hv_xy,
    _segment_connected_line_xy,
    _trace_segments,
)
































































def _soc_split_points(
    length: int,
    history_slot_count: int | None,
    *,
    skip_history: bool = False,
) -> list[tuple[int, int]]:
    if skip_history:
        if history_slot_count is not None and history_slot_count > 0:
            return [(history_slot_count, length)]
        return [(0, length)]
    if history_slot_count is not None and 0 < history_slot_count < length:
        return [(0, history_slot_count), (history_slot_count, length)]
    return [(0, length)]


def _part_extrap_offsets(
    part_start: int,
    part_end: int,
    extrap_start: int | None,
    extrap_end: int | None,
) -> tuple[int | None, int | None]:
    if extrap_start is None or extrap_end is None:
        return None, None
    abs_extrap_start = max(extrap_start, part_start)
    abs_extrap_end = min(extrap_end, part_end)
    if abs_extrap_start < abs_extrap_end:
        return abs_extrap_start - part_start, abs_extrap_end - part_start
    return None, None


def _add_soc_line_trace(
    fig: go.Figure,
    soc_x: pd.Series,
    soc_y: pd.Series,
    *,
    name: str,
    show_legend: bool,
    yaxis: str,
    hover_labels: list[str],
    line: dict,
    opacity: float = 1.0,
) -> None:
    fig.add_trace(go.Scatter(
        x=soc_x,
        y=soc_y,
        name=name,
        showlegend=show_legend,
        mode="lines",
        line=line,
        opacity=opacity,
        yaxis=yaxis,
        connectgaps=False,
        customdata=hover_labels,
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>%{fullData.name}: "
            "%{y:.1f}<extra></extra>"
        ),
    ))


def _add_optimized_soc_segment(
    fig: go.Figure,
    ctx: dict,
    abs_start: int,
    abs_end: int,
    index: int,
    part_start: int,
) -> None:
    length = ctx["length"]
    history_slot_count = ctx["history_slot_count"]
    seg_tail = ctx["tail_y"] if abs_end == length else None
    is_milp_part = history_slot_count is None or part_start >= history_slot_count
    ramp_before, ramp_after = _milp_part_soc_ramps(
        ctx["axis"],
        ctx["soc"],
        ctx["df"],
        ctx["chart_now"],
        abs_start,
        abs_end,
        history_slot_count,
        is_milp_part,
        ctx["battery_params"],
    )
    # Keep horizon end-of-hour SoC even when the current-hour ramp is active.
    # Clearing tail_y here drew a flat last hour (start SoC repeated to 06:00).
    soc_x, soc_y = _segment_connected_line_xy(
        ctx["axis"], ctx["soc"], abs_start, abs_end, tail_y=seg_tail,
        step_line=False,
    )
    if soc_x.empty:
        return
    soc_x, soc_y = _apply_soc_current_hour_ramps(
        soc_x, soc_y, ramp_before, ramp_after,
    )
    _add_soc_line_trace(
        fig,
        soc_x,
        soc_y,
        name="SoC",
        show_legend=part_start == 0 and index == 0,
        yaxis=ctx["yaxis"],
        hover_labels=_soc_hover_labels_for_times(
            soc_x, ctx["uhrzeit"], ctx["axis"].starts,
        ),
        line=dict(color=COLOR_SOC, width=2.5),
    )


def add_optimized_soc_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
    history_slot_count: int | None = None,
    chart_now: datetime | None = None,
    battery_params: dict | None = None,
) -> None:
    ctx = {
        "df": df,
        "axis": axis,
        "yaxis": yaxis,
        "uhrzeit": df["Uhrzeit"],
        "length": len(df),
        "soc": df["Simulierter SoC (%)"],
        "tail_y": (
            _soc_tail_y_from_row(df.iloc[-1], battery_params=battery_params)
            if not df.empty
            else None
        ),
        "history_slot_count": history_slot_count,
        "chart_now": chart_now,
        "battery_params": battery_params,
    }
    for part_start, part_end in _soc_split_points(ctx["length"], history_slot_count):
        part_extrap_start, part_extrap_end = _part_extrap_offsets(
            part_start, part_end, extrap_start, extrap_end
        )
        segments = _trace_segments(
            part_end - part_start, part_extrap_start, part_extrap_end
        )
        for index, (start, end, _is_extrapolated) in enumerate(segments):
            abs_start = part_start + start
            abs_end = part_start + end
            if abs_start >= abs_end:
                continue
            _add_optimized_soc_segment(
                fig, ctx, abs_start, abs_end, index, part_start
            )


def add_baseline_soc_traces(
    fig: go.Figure,
    matched_baseline_df: pd.DataFrame | None,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
    chart_now: datetime | None = None,
    history_slot_count: int | None = None,
    soc_at_now: float | None = None,
    battery_params: dict | None = None,
) -> None:
    add_anchored_counterfactual_soc_traces(
        fig,
        matched_baseline_df,
        name="SoC BL Ziel",
        dash="dot",
        yaxis=yaxis,
        extrap_start=extrap_start,
        extrap_end=extrap_end,
        chart_now=chart_now,
        history_slot_count=history_slot_count,
        soc_at_now=soc_at_now,
        battery_params=battery_params,
    )


def _add_counterfactual_soc_segment(
    fig: go.Figure,
    ctx: dict,
    abs_start: int,
    abs_end: int,
    index: int,
) -> None:
    soc_df = ctx["soc_df"]
    matched_axis = ctx["axis"]
    soc = soc_df["Simulierter SoC (%)"]
    seg_tail = None
    if abs_end == ctx["length"]:
        seg_tail = _soc_tail_y_from_row(
            soc_df.iloc[-1],
            battery_params=ctx["battery_params"],
        )
    ramp_after = None
    if ctx["chart_now"] is not None:
        ramp_after = _current_hour_soc_ramp(
            matched_axis,
            soc,
            soc_df,
            ctx["chart_now"],
            abs_start,
            abs_end,
            ctx["history_slot_count"],
            y_at_now=ctx["soc_at_now"],
            battery_params=ctx["battery_params"],
        )
    # Same as optimized SoC: do not drop horizon tail when ramp_after is set.
    matched_x, matched_y = _segment_connected_line_xy(
        matched_axis,
        soc,
        abs_start,
        abs_end,
        tail_y=seg_tail,
        step_line=False,
        bridge_left=(index > 0),
    )
    if matched_x.empty:
        return
    matched_x, matched_y = _apply_soc_current_hour_ramps(
        matched_x, matched_y, None, ramp_after,
    )
    if index == 0:
        matched_x, matched_y = _anchor_baseline_soc_at_now(
            matched_x, matched_y, ctx["chart_now"], ctx["soc_at_now"],
        )
    _add_soc_line_trace(
        fig,
        matched_x,
        matched_y,
        name=ctx["name"],
        show_legend=index == 0,
        yaxis=ctx["yaxis"],
        hover_labels=_soc_hover_labels_for_times(
            matched_x, soc_df["Uhrzeit"], matched_axis.starts,
        ),
        line=dict(color=COLOR_SOC, width=ctx["line_width"], dash=ctx["dash"]),
        opacity=ctx["opacity"],
    )


def add_anchored_counterfactual_soc_traces(
    fig: go.Figure,
    soc_df: pd.DataFrame | None,
    *,
    name: str,
    dash: str,
    line_width: float = 2.5,
    opacity: float = 1.0,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
    chart_now: datetime | None = None,
    history_slot_count: int | None = None,
    soc_at_now: float | None = None,
    battery_params: dict | None = None,
) -> None:
    if soc_df is None or soc_df.empty:
        return
    length = len(soc_df)
    if history_slot_count is not None and history_slot_count >= length:
        return
    ctx = {
        "soc_df": soc_df,
        "axis": ChartSlotAxis.from_dataframe(soc_df),
        "length": length,
        "name": name,
        "dash": dash,
        "line_width": line_width,
        "opacity": opacity,
        "yaxis": yaxis,
        "chart_now": chart_now,
        "history_slot_count": history_slot_count,
        "soc_at_now": soc_at_now,
        "battery_params": battery_params,
    }
    for part_start, part_end in _soc_split_points(
        length, history_slot_count, skip_history=True
    ):
        part_extrap_start, part_extrap_end = _part_extrap_offsets(
            part_start, part_end, extrap_start, extrap_end
        )
        matched_segments = _trace_segments(
            part_end - part_start, part_extrap_start, part_extrap_end,
        )
        for index, (start, end, _is_extrapolated) in enumerate(matched_segments):
            abs_start = part_start + start
            abs_end = part_start + end
            if abs_start >= abs_end:
                continue
            _add_counterfactual_soc_segment(fig, ctx, abs_start, abs_end, index)


def add_price_on_soc_axis_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
    *,
    column: str = "Strompreis (Cent/kWh)",
    name: str = "Preis",
    line: dict | None = None,
    hover_label: str = "Preis",
) -> None:
    """Preis auf der SoC-Achse — Stufen je Chart-Slot (QH/Stunde), an Slot-Rändern."""
    del extrap_start, extrap_end
    line_style = line if line is not None else dict(color="red", width=2.5, shape="hv")
    line_x, line_y = _hourly_price_hv_xy(axis, df, column=column)
    if line_x.empty:
        return
    slot_prices = _hour_prices_from_df(df, column=column)
    customdata: list[float] = []
    slot_idx = 0
    for x in line_x:
        x_ts = pd.Timestamp(x)
        while slot_idx + 1 < len(slot_prices):
            next_slot = slot_prices[slot_idx + 1][0]
            if x_ts >= pd.Timestamp(next_slot):
                slot_idx += 1
            else:
                break
        customdata.append(slot_prices[slot_idx][1])
    fig.add_trace(go.Scatter(
        x=line_x,
        y=line_y,
        name=name,
        showlegend=True,
        mode="lines",
        line=line_style,
        opacity=1.0,
        yaxis=yaxis,
        text=_hourly_price_hover_labels(df, line_x, column=column),
        customdata=customdata,
        hovertemplate=(
            f"Uhrzeit: %{{text}}<br>{hover_label}: %{{customdata:.2f}} Cent/kWh"
            "<extra></extra>"
        ),
    ))


def add_export_price_on_soc_axis_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Einspeisevergütung auf der SoC-Achse — gestrichelte orange Stufen."""
    add_price_on_soc_axis_trace(
        fig,
        df,
        axis,
        yaxis=yaxis,
        extrap_start=extrap_start,
        extrap_end=extrap_end,
        column=_EXPORT_PRICE_COLUMN,
        name="Einspeisepreis",
        line=dict(color="orange", width=2.5, dash="dash", shape="hv"),
        hover_label="Einspeisepreis",
    )

from ui.chart_soc_ramps import (  # noqa: E402
    _anchor_baseline_soc_at_now,
    _apply_soc_current_hour_ramps,
    _apply_soc_intra_hour_ramp,
    _current_hour_soc_ramp,
    _current_hour_soc_ramp_before_now,
    _first_milp_slot_in_current_hour,
    _has_milp_slots_between,
    _history_battery_kw_for_extrapolation,
    _resolve_battery_params,
    _slot_index_at_or_after,
    _soc_at_chart_now,
    _soc_from_history_extrapolation,
    _soc_hover_labels_for_times,
    _soc_on_milp_polyline,
    _soc_tail_y_from_row,
    _soc_y_at_moment,
    _soc_y_for_chart_now,
)
from ui.chart_soc_underlay import (  # noqa: E402
    ESS_UNDERLAY_CHARGE,
    ESS_UNDERLAY_DISCHARGE,
    ESS_UNDERLAY_HOLD,
    _ESS_UNDERLAY_COLORS,
    _ESS_UNDERLAY_LINE_WIDTH,
    _ESS_UNDERLAY_NEAR_ZERO_FRACTION,
    _ESS_UNDERLAY_OPACITY,
    _ESS_UNDERLAY_TRACE_NAMES,
    _ZWANGS_POWER_RE,
    _add_ess_underlay_run,
    _add_ess_underlay_scatter,
    _clip_line_xy_to_span,
    _contiguous_underlay_runs,
    _ess_underlay_near_zero,
    _extend_underlay_xy_to_run_end,
    _milp_part_soc_ramps,
    _parse_zwangs_power_kw,
    _underlay_part_ranges,
    _underlay_ramp_if_overlaps,
    add_ess_mode_soc_underlay_traces,
    classify_ess_soc_underlay,
)

# Re-Exports für API-Stabilität (from ui.chart_soc import ...)
__all__ = [
    "ESS_UNDERLAY_CHARGE",
    "ESS_UNDERLAY_DISCHARGE",
    "ESS_UNDERLAY_HOLD",
    "add_anchored_counterfactual_soc_traces",
    "add_baseline_soc_traces",
    "add_ess_mode_soc_underlay_traces",
    "add_export_price_on_soc_axis_trace",
    "add_optimized_soc_trace",
    "add_price_on_soc_axis_trace",
    "classify_ess_soc_underlay",
    "_soc_tail_y_from_row",
]

"""ESS-mode SoC underlay traces for Chart 2."""
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
from ui.chart_soc_ramps import (
    _apply_soc_current_hour_ramps,
    _current_hour_soc_ramp,
    _current_hour_soc_ramp_before_now,
    _resolve_battery_params,
    _soc_at_chart_now,
    _soc_hover_labels_for_times,
    _soc_tail_y_from_row,
)









































ESS_UNDERLAY_HOLD = "hold"

ESS_UNDERLAY_CHARGE = "charge"

ESS_UNDERLAY_DISCHARGE = "discharge"

_ESS_UNDERLAY_NEAR_ZERO_FRACTION = 0.05

_ESS_UNDERLAY_LINE_WIDTH = 16.0

_ESS_UNDERLAY_OPACITY = 0.2

_ESS_UNDERLAY_TRACE_NAMES = {
    ESS_UNDERLAY_HOLD: "Entladesperre / Hold",
    ESS_UNDERLAY_CHARGE: "Zwangsladen",
    ESS_UNDERLAY_DISCHARGE: "Zwangsentladen",
}

_ESS_UNDERLAY_COLORS = {
    ESS_UNDERLAY_HOLD: COLOR_ESS_UNDERLAY_HOLD,
    ESS_UNDERLAY_CHARGE: COLOR_ESS_UNDERLAY_CHARGE,
    ESS_UNDERLAY_DISCHARGE: COLOR_ESS_UNDERLAY_DISCHARGE,
}

_ZWANGS_POWER_RE = re.compile(
    r"^Zwangs(?:laden|entladen)\s*\(([-\d.]+)\s*kW\)",
    re.IGNORECASE,
)

def _parse_zwangs_power_kw(command: str) -> float | None:
    match = _ZWANGS_POWER_RE.match(str(command).strip())
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None

def _ess_underlay_near_zero(power_kw: float, max_power_kw: float) -> bool:
    if max_power_kw <= 0:
        return abs(power_kw) <= 0.0
    return abs(power_kw) < _ESS_UNDERLAY_NEAR_ZERO_FRACTION * max_power_kw

def classify_ess_soc_underlay(
    command,
    max_power_kw: float,
) -> str | None:
    """Map Steuerbefehl → underlay kind (hold/charge/discharge) or None."""
    text = str(command)
    if "Entladesperre" in text:
        return ESS_UNDERLAY_HOLD
    if text.startswith("Zwangsladen"):
        power = _parse_zwangs_power_kw(text)
        if power is None:
            power = 0.0
        if _ess_underlay_near_zero(power, max_power_kw):
            return ESS_UNDERLAY_HOLD
        return ESS_UNDERLAY_CHARGE
    if text.startswith("Zwangsentladen"):
        power = _parse_zwangs_power_kw(text)
        if power is None:
            power = 0.0
        if _ess_underlay_near_zero(power, max_power_kw):
            return ESS_UNDERLAY_HOLD
        return ESS_UNDERLAY_DISCHARGE
    return None

def _contiguous_underlay_runs(
    kinds: list[str | None],
    start: int,
    end: int,
) -> list[tuple[int, int, str]]:
    runs: list[tuple[int, int, str]] = []
    index = start
    while index < end:
        kind = kinds[index]
        if kind is None:
            index += 1
            continue
        run_end = index + 1
        while run_end < end and kinds[run_end] == kind:
            run_end += 1
        runs.append((index, run_end, kind))
        index = run_end
    return runs

def _add_ess_underlay_scatter(
    fig: go.Figure,
    *,
    soc_x: pd.Series,
    soc_y: pd.Series,
    kind: str,
    hover_labels: list[str],
    yaxis: str,
    show_legend: bool,
) -> None:
    fig.add_trace(go.Scatter(
        x=soc_x,
        y=soc_y,
        name=_ESS_UNDERLAY_TRACE_NAMES[kind],
        showlegend=show_legend,
        mode="lines",
        line=dict(color=_ESS_UNDERLAY_COLORS[kind], width=_ESS_UNDERLAY_LINE_WIDTH),
        opacity=_ESS_UNDERLAY_OPACITY,
        yaxis=yaxis,
        connectgaps=False,
        customdata=hover_labels,
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>%{fullData.name}<extra></extra>"
        ),
    ))

def _underlay_part_ranges(
    length: int,
    history_slot_count: int | None,
) -> list[tuple[int, int]]:
    if history_slot_count is not None and 0 < history_slot_count < length:
        return [(0, history_slot_count), (history_slot_count, length)]
    return [(0, length)]

def _extend_underlay_xy_to_run_end(
    axis: ChartSlotAxis,
    soc: pd.Series,
    soc_x: pd.Series,
    soc_y: pd.Series,
    run_end: int,
    length: int,
) -> tuple[pd.Series, pd.Series]:
    """Ensure underlay covers the full last slot (1-slot runs stay visible)."""
    if soc_x.empty or run_end >= length:
        return soc_x, soc_y
    end_x = axis.at(run_end, 0.0).iloc[0]
    if pd.Timestamp(soc_x.iloc[-1]) >= pd.Timestamp(end_x):
        return soc_x, soc_y
    end_y = _line_plot_float(soc.iloc[run_end])
    return (
        pd.concat([soc_x, pd.Series([end_x])], ignore_index=True),
        pd.concat([soc_y, pd.Series([end_y])], ignore_index=True),
    )

def _clip_line_xy_to_span(
    soc_x: pd.Series,
    soc_y: pd.Series,
    span_start: pd.Timestamp,
    span_end: pd.Timestamp,
) -> tuple[pd.Series, pd.Series]:
    """Drop points forced outside the underlay run (e.g. hour-ramp endpoints)."""
    kept_x: list = []
    kept_y: list[float] = []
    for x_val, y_val in zip(soc_x, soc_y):
        stamp = pd.Timestamp(x_val)
        if stamp < span_start or stamp > span_end:
            continue
        kept_x.append(x_val)
        kept_y.append(float(y_val))
    if not kept_x:
        return soc_x, soc_y
    return _chart_time_series(kept_x), pd.Series(kept_y, dtype=float)

def _underlay_ramp_if_overlaps(
    soc_x: pd.Series,
    ramp: tuple[datetime, float, datetime, float] | None,
) -> tuple[datetime, float, datetime, float] | None:
    if ramp is None or soc_x.empty:
        return None
    t_start, _y0, t_end, _y1 = ramp
    x_min = pd.Timestamp(soc_x.iloc[0])
    x_max = pd.Timestamp(soc_x.iloc[-1])
    if pd.Timestamp(t_end) < x_min or pd.Timestamp(t_start) > x_max:
        return None
    return ramp

def _add_ess_underlay_run(
    fig: go.Figure,
    *,
    axis: ChartSlotAxis,
    soc: pd.Series,
    uhrzeit: pd.Series,
    df: pd.DataFrame,
    run_start: int,
    run_end: int,
    kind: str,
    length: int,
    yaxis: str,
    legend_shown: set[str],
    battery_params: dict | None,
    ramp_before: tuple[datetime, float, datetime, float] | None = None,
    ramp_after: tuple[datetime, float, datetime, float] | None = None,
) -> None:
    seg_tail = None
    if run_end == length:
        seg_tail = _soc_tail_y_from_row(df.iloc[-1], battery_params=battery_params)
    soc_x, soc_y = _segment_connected_line_xy(
        axis,
        soc,
        run_start,
        run_end,
        tail_y=seg_tail,
        step_line=False,
        bridge_left=False,
    )
    soc_x, soc_y = _extend_underlay_xy_to_run_end(
        axis, soc, soc_x, soc_y, run_end, length,
    )
    if soc_x.empty:
        return
    span_start = pd.Timestamp(soc_x.iloc[0])
    span_end = pd.Timestamp(soc_x.iloc[-1])
    soc_x, soc_y = _apply_soc_current_hour_ramps(
        soc_x,
        soc_y,
        _underlay_ramp_if_overlaps(soc_x, ramp_before),
        _underlay_ramp_if_overlaps(soc_x, ramp_after),
    )
    soc_x, soc_y = _clip_line_xy_to_span(soc_x, soc_y, span_start, span_end)
    if soc_x.empty:
        return
    hover_labels = _soc_hover_labels_for_times(soc_x, uhrzeit, axis.starts)
    show_legend = kind not in legend_shown
    _add_ess_underlay_scatter(
        fig,
        soc_x=soc_x,
        soc_y=soc_y,
        kind=kind,
        hover_labels=hover_labels,
        yaxis=yaxis,
        show_legend=show_legend,
    )
    legend_shown.add(kind)

def _milp_part_soc_ramps(
    axis: ChartSlotAxis,
    soc: pd.Series,
    df: pd.DataFrame,
    chart_now: datetime | None,
    abs_start: int,
    abs_end: int,
    history_slot_count: int | None,
    is_milp_part: bool,
    battery_params: dict | None,
) -> tuple[
    tuple[datetime, float, datetime, float] | None,
    tuple[datetime, float, datetime, float] | None,
]:
    if chart_now is None or not is_milp_part:
        return None, None
    y_at_now: float | None = None
    if history_slot_count is not None and history_slot_count > 0:
        y_at_now = _soc_at_chart_now(
            axis, df, chart_now, history_slot_count,
            battery_params=battery_params,
        )
    ramp_before = _current_hour_soc_ramp_before_now(
        axis,
        soc,
        df,
        chart_now,
        abs_start,
        abs_end,
        history_slot_count,
        y_at_now=y_at_now,
        battery_params=battery_params,
    )
    ramp_after = _current_hour_soc_ramp(
        axis,
        soc,
        df,
        chart_now,
        abs_start,
        abs_end,
        history_slot_count,
        y_at_now=y_at_now,
        battery_params=battery_params,
    )
    return ramp_before, ramp_after

def _underlay_part_extrap(
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


def _add_underlay_part(
    fig: go.Figure,
    ctx: dict,
    part_start: int,
    part_end: int,
    kinds: list[str | None],
    legend_shown: set[str],
) -> None:
    part_extrap_start, part_extrap_end = _underlay_part_extrap(
        part_start, part_end, ctx["extrap_start"], ctx["extrap_end"]
    )
    segments = _trace_segments(
        part_end - part_start, part_extrap_start, part_extrap_end
    )
    is_milp_part = (
        ctx["history_slot_count"] is None or part_start >= ctx["history_slot_count"]
    )
    for start, end, _is_extrapolated in segments:
        abs_start = part_start + start
        abs_end = part_start + end
        ramp_before, ramp_after = _milp_part_soc_ramps(
            ctx["axis"],
            ctx["soc"],
            ctx["df"],
            ctx["chart_now"],
            abs_start,
            abs_end,
            ctx["history_slot_count"],
            is_milp_part,
            ctx["battery_params"],
        )
        for run_start, run_end, kind in _contiguous_underlay_runs(
            kinds, abs_start, abs_end
        ):
            _add_ess_underlay_run(
                fig,
                axis=ctx["axis"],
                soc=ctx["soc"],
                uhrzeit=ctx["uhrzeit"],
                df=ctx["df"],
                run_start=run_start,
                run_end=run_end,
                kind=kind,
                length=ctx["length"],
                yaxis=ctx["yaxis"],
                legend_shown=legend_shown,
                battery_params=ctx["battery_params"],
                ramp_before=ramp_before,
                ramp_after=ramp_after,
            )


def add_ess_mode_soc_underlay_traces(
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
    """Thicker translucent SoC underlay by ESS mode (hold/charge/discharge)."""
    if "Steuerbefehl" not in df.columns or "Simulierter SoC (%)" not in df.columns:
        return
    params = _resolve_battery_params(battery_params)
    max_power_kw = float(params.get("max_power_kw") or 0.0)
    length = len(df)
    kinds = [
        classify_ess_soc_underlay(df["Steuerbefehl"].iloc[i], max_power_kw)
        for i in range(length)
    ]
    ctx = {
        "axis": axis,
        "soc": df["Simulierter SoC (%)"],
        "uhrzeit": df["Uhrzeit"],
        "df": df,
        "length": length,
        "yaxis": yaxis,
        "extrap_start": extrap_start,
        "extrap_end": extrap_end,
        "history_slot_count": history_slot_count,
        "chart_now": chart_now,
        "battery_params": battery_params,
    }
    legend_shown: set[str] = set()
    for part_start, part_end in _underlay_part_ranges(length, history_slot_count):
        _add_underlay_part(fig, ctx, part_start, part_end, kinds, legend_shown)

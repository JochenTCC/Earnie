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
from optimizer.slot_duration import DEFAULT_DT_H
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


def _resolve_battery_params(battery_params: dict | None) -> dict:
    if battery_params is not None:
        return battery_params
    return config.get_battery_params()


def _soc_tail_y_from_row(
    row: pd.Series,
    battery_params: dict | None = None,
) -> float | None:
    """SoC am Ende der Stunde aus geplanter Batterieaktion (Optimierer/Huawei-Logik)."""
    if "Geplante Batterie-Aktion (kW)" not in row.index:
        return None
    soc = _optional_float(row.get("Simulierter SoC (%)"))
    action = _optional_float(row.get("Geplante Batterie-Aktion (kW)"))
    if soc is None or action is None:
        return None
    params = _resolve_battery_params(battery_params)
    capacity = float(params.get("battery_capacity_kwh", 0.0))
    if capacity <= 0:
        return None
    new_soc, _ = bat.apply_soc_change(
        soc,
        action,
        capacity,
        params["efficiency"],
        params["min_soc"],
        params["max_soc"],
        dt_h=DEFAULT_DT_H,
    )
    return round(new_soc, 1)


def _soc_y_at_moment(
    axis: ChartSlotAxis,
    soc: pd.Series,
    moment: datetime,
    max_index: int,
) -> float:
    """Lineare SoC-Interpolation zwischen Slot-Anfangswerten bis ``max_index``."""
    moment_ts = pd.Timestamp(moment)
    last_idx: int | None = None
    limit = min(max_index, len(axis.starts))
    for index in range(limit):
        if axis.starts.iloc[index] <= moment_ts:
            last_idx = index
        else:
            break
    if last_idx is None:
        return float("nan")
    y0 = _line_plot_float(soc.iloc[last_idx])
    if last_idx + 1 < limit:
        next_ts = axis.starts.iloc[last_idx + 1]
        if moment_ts < next_ts:
            t0 = axis.starts.iloc[last_idx].to_pydatetime()
            t1 = next_ts.to_pydatetime()
            y1 = _line_plot_float(soc.iloc[last_idx + 1])
            span = (t1 - t0).total_seconds()
            if span > 0 and not math.isnan(y0) and not math.isnan(y1):
                frac = (moment - t0).total_seconds() / span
                return y0 + frac * (y1 - y0)
    return y0


def _history_battery_kw_for_extrapolation(row: pd.Series) -> float | None:
    """Ist-Leistung aus Log bevorzugen, sonst geplanter Batteriewert."""
    ist = _optional_float(row.get(CHART_IST_BATTERY_KW_COLUMN))
    if ist is not None:
        return ist
    return _optional_float(row.get("Geplante Batterie-Aktion (kW)"))


def _soc_from_history_extrapolation(
    axis: ChartSlotAxis,
    soc: pd.Series,
    df: pd.DataFrame,
    moment: datetime,
    history_slot_count: int,
    battery_params: dict | None = None,
) -> float:
    """SoC aus Log-Slots; nach letztem Log-Eintrag per Batterieleistung hochgerechnet."""
    if history_slot_count <= 0:
        return float("nan")
    last_idx = history_slot_count - 1
    last_start = axis.starts.iloc[last_idx].to_pydatetime()
    if moment <= last_start:
        return _soc_y_at_moment(axis, soc, moment, history_slot_count)
    last_soc = _line_plot_float(soc.iloc[last_idx])
    if math.isnan(last_soc):
        return float("nan")
    action = _history_battery_kw_for_extrapolation(df.iloc[last_idx])
    if action is None:
        return last_soc
    elapsed_h = (moment - last_start).total_seconds() / 3600.0
    if elapsed_h <= 0:
        return last_soc
    params = _resolve_battery_params(battery_params)
    capacity = float(params.get("battery_capacity_kwh", 0.0))
    if capacity <= 0:
        return last_soc
    new_soc, _ = bat.apply_soc_change(
        last_soc,
        action,
        capacity,
        params["efficiency"],
        params["min_soc"],
        params["max_soc"],
        dt_h=elapsed_h,
    )
    return round(new_soc, 1)


def _soc_at_chart_now(
    axis: ChartSlotAxis,
    df: pd.DataFrame,
    chart_now: datetime | None,
    history_slot_count: int | None,
    battery_params: dict | None = None,
) -> float | None:
    """SoC am Jetzt-Marker aus Log-Daten (Referenz für BL-Ziel-Anker)."""
    if (
        chart_now is None
        or chart_now.tzinfo is None
        or history_slot_count is None
        or history_slot_count <= 0
    ):
        return None
    soc = df["Simulierter SoC (%)"]
    value = _soc_from_history_extrapolation(
        axis, soc, df, chart_now, history_slot_count,
        battery_params=battery_params,
    )
    if math.isnan(value):
        return None
    return value


def _first_milp_slot_in_current_hour(
    axis: ChartSlotAxis,
    now: datetime,
    seg_start: int,
    seg_end: int,
    history_slot_count: int | None,
) -> int | None:
    hour_start = normalize_hour_slot(now)
    hour_end = hour_start + timedelta(hours=1)
    for index in range(seg_start, seg_end):
        slot = axis.starts.iloc[index].to_pydatetime()
        if hour_start <= slot < hour_end:
            if history_slot_count is not None and index < history_slot_count:
                continue
            return index
    return None


def _current_hour_soc_ramp_before_now(
    axis: ChartSlotAxis,
    soc: pd.Series,
    df: pd.DataFrame,
    now: datetime,
    seg_start: int,
    seg_end: int,
    history_slot_count: int | None,
    y_at_now: float | None = None,
    battery_params: dict | None = None,
) -> tuple[datetime, float, datetime, float] | None:
    """
    Rampe erster MILP-Viertelstunde → Jetzt (keine konstante MILP-Soll-Treppe).

    Ergänzt die Rampe Jetzt → Stundenende in der laufenden Stunde ab x:15.
    """
    if now.tzinfo is None or history_slot_count is None or history_slot_count <= 0:
        return None
    hour_start = normalize_hour_slot(now)
    hour_end = hour_start + timedelta(hours=1)
    if now <= hour_start or now >= hour_end or seg_start >= seg_end:
        return None

    milp_idx = _first_milp_slot_in_current_hour(
        axis, now, seg_start, seg_end, history_slot_count,
    )
    if milp_idx is None:
        return None

    t_start = axis.starts.iloc[milp_idx].to_pydatetime()
    if now <= t_start:
        return None

    y_start = _soc_from_history_extrapolation(
        axis, soc, df, t_start, history_slot_count,
        battery_params=battery_params,
    )
    if y_at_now is not None:
        y_end = y_at_now
    else:
        y_end = _soc_from_history_extrapolation(
            axis, soc, df, now, history_slot_count,
            battery_params=battery_params,
        )
    if math.isnan(y_start) or math.isnan(y_end):
        return None
    return t_start, y_start, now, y_end


def _current_hour_soc_ramp(
    axis: ChartSlotAxis,
    soc: pd.Series,
    df: pd.DataFrame,
    now: datetime,
    seg_start: int,
    seg_end: int,
    history_slot_count: int | None,
    y_at_now: float | None = None,
    battery_params: dict | None = None,
) -> tuple[datetime, float, datetime, float] | None:
    """
    Rampe Jetzt → Stundenende im neutralen MILP-Bereich (keine SoC-Treppe).

    Gilt nur für Slots der laufenden Stunde nach dem Produktiv-Log.
    """
    if now.tzinfo is None:
        return None
    hour_start = normalize_hour_slot(now)
    hour_end = hour_start + timedelta(hours=1)
    if now >= hour_end or seg_start >= seg_end:
        return None

    milp_idx = _first_milp_slot_in_current_hour(
        axis, now, seg_start, seg_end, history_slot_count,
    )
    if milp_idx is None:
        return None

    y_end = _soc_tail_y_from_row(df.iloc[milp_idx], battery_params=battery_params)
    if y_end is None:
        return None

    t_start = max(now, hour_start)
    if y_at_now is not None:
        y_start = y_at_now
    elif history_slot_count is not None and history_slot_count > 0:
        y_start = _soc_from_history_extrapolation(
            axis, soc, df, t_start, history_slot_count,
            battery_params=battery_params,
        )
    else:
        y_start = float("nan")
    if math.isnan(y_start):
        y_start = _soc_y_at_moment(axis, soc, t_start, seg_end)
    if math.isnan(y_start) or t_start >= hour_end:
        return None
    return t_start, y_start, hour_end, y_end


def _apply_soc_intra_hour_ramp(
    line_x: pd.Series,
    line_y: pd.Series,
    ramp: tuple[datetime, float, datetime, float],
) -> tuple[pd.Series, pd.Series]:
    """Ersetzt konstante Viertelstunden-Punkte durch Rampe bis Stundenende."""
    t_start, y_start, t_end, y_end = ramp
    ts_start = pd.Timestamp(t_start)
    ts_end = pd.Timestamp(t_end)
    kept: list[tuple[datetime, float]] = []
    for x_val, y_val in zip(line_x, line_y):
        t_stamp = pd.Timestamp(x_val)
        if t_stamp == ts_start:
            kept.append((t_start, float(y_start)))
            continue
        if ts_start < t_stamp < ts_end:
            continue
        if t_stamp == ts_end:
            kept.append((t_end, float(y_end)))
            continue
        kept.append((t_stamp.to_pydatetime(), float(y_val)))

    if not any(pd.Timestamp(t) == ts_start for t, _ in kept):
        kept.append((t_start, float(y_start)))
    if not any(pd.Timestamp(t) == ts_end for t, _ in kept):
        kept.append((t_end, float(y_end)))

    kept.sort(key=lambda pair: pd.Timestamp(pair[0]))
    merged: list[tuple[datetime, float]] = []
    for point in kept:
        if merged and pd.Timestamp(merged[-1][0]) == pd.Timestamp(point[0]):
            merged[-1] = point
        else:
            merged.append(point)
    if not merged:
        return line_x, line_y
    times, values = zip(*merged)
    return _chart_time_series(list(times)), pd.Series(values, dtype=float)


def _apply_soc_current_hour_ramps(
    line_x: pd.Series,
    line_y: pd.Series,
    ramp_before: tuple[datetime, float, datetime, float] | None,
    ramp_after: tuple[datetime, float, datetime, float] | None,
) -> tuple[pd.Series, pd.Series]:
    if ramp_before is not None:
        line_x, line_y = _apply_soc_intra_hour_ramp(line_x, line_y, ramp_before)
    if ramp_after is not None:
        line_x, line_y = _apply_soc_intra_hour_ramp(line_x, line_y, ramp_after)
    return line_x, line_y


def _anchor_baseline_soc_at_now(
    line_x: pd.Series,
    line_y: pd.Series,
    chart_now: datetime | None,
    soc_at_now: float | None,
) -> tuple[pd.Series, pd.Series]:
    """BL-Ziel beginnt am Jetzt-Marker — keine Spur davor."""
    if chart_now is None or soc_at_now is None:
        return line_x, line_y
    ts_now = pd.Timestamp(chart_now)
    kept: list[tuple[datetime, float]] = [(chart_now, float(soc_at_now))]
    for x_val, y_val in zip(line_x, line_y):
        if pd.Timestamp(x_val) <= ts_now:
            continue
        kept.append((pd.Timestamp(x_val).to_pydatetime(), float(y_val)))
    kept.sort(key=lambda pair: pd.Timestamp(pair[0]))
    merged: list[tuple[datetime, float]] = []
    for point in kept:
        if merged and pd.Timestamp(merged[-1][0]) == pd.Timestamp(point[0]):
            merged[-1] = point
        else:
            merged.append(point)
    if not merged:
        return line_x, line_y
    times, values = zip(*merged)
    return _chart_time_series(list(times)), pd.Series(values, dtype=float)


def _soc_hover_labels_for_times(
    times: pd.Series,
    uhrzeit: pd.Series,
    slot_starts: pd.Series,
) -> list[str]:
    """Hover-Labels für SoC-Punkte (inkl. Jetzt-/Stundenend-Interpolation)."""
    slot_labels = {
        pd.Timestamp(start): str(label)
        for start, label in zip(slot_starts, uhrzeit)
    }
    labels: list[str] = []
    for moment in times:
        ts = pd.Timestamp(moment)
        label = slot_labels.get(ts)
        if label is None:
            label = ts.strftime("%d.%m. %H:%M")
        labels.append(label)
    return labels


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
) -> None:
    seg_tail = None
    if run_end == length:
        seg_tail = _soc_tail_y_from_row(df.iloc[-1], battery_params=battery_params)
    soc_x, soc_y = _segment_connected_line_xy(
        axis, soc, run_start, run_end, tail_y=seg_tail, step_line=False,
    )
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


def add_ess_mode_soc_underlay_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
    history_slot_count: int | None = None,
    battery_params: dict | None = None,
) -> None:
    """Thicker translucent SoC underlay by ESS mode (hold/charge/discharge)."""
    if "Steuerbefehl" not in df.columns or "Simulierter SoC (%)" not in df.columns:
        return
    params = _resolve_battery_params(battery_params)
    max_power_kw = float(params.get("max_power_kw") or 0.0)
    commands = df["Steuerbefehl"]
    soc = df["Simulierter SoC (%)"]
    uhrzeit = df["Uhrzeit"]
    length = len(df)
    kinds = [
        classify_ess_soc_underlay(commands.iloc[i], max_power_kw)
        for i in range(length)
    ]
    legend_shown: set[str] = set()
    for part_start, part_end in _underlay_part_ranges(length, history_slot_count):
        part_extrap_start: int | None = None
        part_extrap_end: int | None = None
        if extrap_start is not None and extrap_end is not None:
            abs_extrap_start = max(extrap_start, part_start)
            abs_extrap_end = min(extrap_end, part_end)
            if abs_extrap_start < abs_extrap_end:
                part_extrap_start = abs_extrap_start - part_start
                part_extrap_end = abs_extrap_end - part_start
        segments = _trace_segments(
            part_end - part_start, part_extrap_start, part_extrap_end
        )
        for start, end, _is_extrapolated in segments:
            abs_start = part_start + start
            abs_end = part_start + end
            for run_start, run_end, kind in _contiguous_underlay_runs(
                kinds, abs_start, abs_end
            ):
                _add_ess_underlay_run(
                    fig,
                    axis=axis,
                    soc=soc,
                    uhrzeit=uhrzeit,
                    df=df,
                    run_start=run_start,
                    run_end=run_end,
                    kind=kind,
                    length=length,
                    yaxis=yaxis,
                    legend_shown=legend_shown,
                    battery_params=battery_params,
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
    uhrzeit = df["Uhrzeit"]
    length = len(df)
    soc = df["Simulierter SoC (%)"]
    tail_y = (
        _soc_tail_y_from_row(df.iloc[-1], battery_params=battery_params)
        if not df.empty
        else None
    )

    split_points: list[tuple[int, int]] = []
    if history_slot_count is not None and 0 < history_slot_count < length:
        split_points = [(0, history_slot_count), (history_slot_count, length)]
    else:
        split_points = [(0, length)]

    for part_start, part_end in split_points:
        part_extrap_start: int | None = None
        part_extrap_end: int | None = None
        if extrap_start is not None and extrap_end is not None:
            abs_extrap_start = max(extrap_start, part_start)
            abs_extrap_end = min(extrap_end, part_end)
            if abs_extrap_start < abs_extrap_end:
                part_extrap_start = abs_extrap_start - part_start
                part_extrap_end = abs_extrap_end - part_start
        segments = _trace_segments(
            part_end - part_start, part_extrap_start, part_extrap_end
        )
        for index, (start, end, _is_extrapolated) in enumerate(segments):
            abs_start = part_start + start
            abs_end = part_start + end
            if abs_start >= abs_end:
                continue
            seg_tail = tail_y if abs_end == length else None
            is_milp_part = (
                history_slot_count is None or part_start >= history_slot_count
            )
            ramp_before: tuple[datetime, float, datetime, float] | None = None
            ramp_after: tuple[datetime, float, datetime, float] | None = None
            if chart_now is not None and is_milp_part:
                ramp_before = _current_hour_soc_ramp_before_now(
                    axis,
                    soc,
                    df,
                    chart_now,
                    abs_start,
                    abs_end,
                    history_slot_count,
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
                    battery_params=battery_params,
                )
            # Keep horizon end-of-hour SoC even when the current-hour ramp is active.
            # Clearing tail_y here drew a flat last hour (start SoC repeated to 06:00).
            soc_x, soc_y = _segment_connected_line_xy(
                axis, soc, abs_start, abs_end, tail_y=seg_tail,
                step_line=False,
            )
            if soc_x.empty:
                continue
            soc_x, soc_y = _apply_soc_current_hour_ramps(
                soc_x, soc_y, ramp_before, ramp_after,
            )
            hover_labels = _soc_hover_labels_for_times(
                soc_x, uhrzeit, axis.starts,
            )
            show_legend = part_start == 0 and index == 0
            fig.add_trace(go.Scatter(
                x=soc_x,
                y=soc_y,
                name="SoC",
                showlegend=show_legend,
                mode="lines",
                line=dict(color=COLOR_SOC, width=2.5),
                opacity=1.0,
                yaxis=yaxis,
                connectgaps=False,
                customdata=hover_labels,
                hovertemplate=(
                    "Uhrzeit: %{customdata}<br>%{fullData.name}: "
                    "%{y:.1f}<extra></extra>"
                ),
            ))


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
    matched_axis = ChartSlotAxis.from_dataframe(soc_df)
    length = len(soc_df)
    if history_slot_count is not None and history_slot_count >= length:
        return
    split_points: list[tuple[int, int]] = []
    if history_slot_count is not None and history_slot_count > 0:
        split_points = [(history_slot_count, length)]
    else:
        split_points = [(0, length)]

    for part_start, part_end in split_points:
        part_extrap_start: int | None = None
        part_extrap_end: int | None = None
        if extrap_start is not None and extrap_end is not None:
            abs_extrap_start = max(extrap_start, part_start)
            abs_extrap_end = min(extrap_end, part_end)
            if abs_extrap_start < abs_extrap_end:
                part_extrap_start = abs_extrap_start - part_start
                part_extrap_end = abs_extrap_end - part_start
        matched_segments = _trace_segments(
            part_end - part_start, part_extrap_start, part_extrap_end,
        )
        for index, (start, end, _is_extrapolated) in enumerate(matched_segments):
            abs_start = part_start + start
            abs_end = part_start + end
            if abs_start >= abs_end:
                continue
            seg_tail = None
            if abs_end == length:
                seg_tail = _soc_tail_y_from_row(
                    soc_df.iloc[-1],
                    battery_params=battery_params,
                )
            ramp_after: tuple[datetime, float, datetime, float] | None = None
            if chart_now is not None:
                ramp_after = _current_hour_soc_ramp(
                    matched_axis,
                    soc_df["Simulierter SoC (%)"],
                    soc_df,
                    chart_now,
                    abs_start,
                    abs_end,
                    history_slot_count,
                    y_at_now=soc_at_now,
                    battery_params=battery_params,
                )
            # Same as optimized SoC: do not drop horizon tail when ramp_after is set.
            matched_x, matched_y = _segment_connected_line_xy(
                matched_axis,
                soc_df["Simulierter SoC (%)"],
                abs_start,
                abs_end,
                tail_y=seg_tail,
                step_line=False,
                bridge_left=(index > 0),
            )
            if matched_x.empty:
                continue
            matched_x, matched_y = _apply_soc_current_hour_ramps(
                matched_x, matched_y, None, ramp_after,
            )
            if index == 0:
                matched_x, matched_y = _anchor_baseline_soc_at_now(
                    matched_x, matched_y, chart_now, soc_at_now,
                )
            hover_labels = _soc_hover_labels_for_times(
                matched_x,
                soc_df["Uhrzeit"],
                matched_axis.starts,
            )
            show_legend = index == 0
            fig.add_trace(go.Scatter(
                x=matched_x,
                y=matched_y,
                name=name,
                showlegend=show_legend,
                mode="lines",
                line=dict(color=COLOR_SOC, width=line_width, dash=dash),
                opacity=opacity,
                yaxis=yaxis,
                connectgaps=False,
                customdata=hover_labels,
                hovertemplate=(
                    "Uhrzeit: %{customdata}<br>%{fullData.name}: "
                    "%{y:.1f}<extra></extra>"
                ),
            ))


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


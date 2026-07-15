"""SoC-Traces, Entladesperre-Band und Preis auf SoC-Achse."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import config
import pandas as pd
import plotly.graph_objects as go

from data.planning_window import normalize_hour_slot
from optimizer import battery as bat
from runtime_store.history_timeline import CHART_IST_BATTERY_KW_COLUMN
from ui.chart_colors import (
    CHART_ENTLADESPERRE_BAND_FILL,
    CHART_ENTLADESPERRE_BAND_STRIPE,
    COLOR_SOC,
)
from ui.chart_consumer_stack import _CONSUMER_PV_FOLLOW_PATTERN, _is_entladesperre_command
from ui.chart_slot_axis import (
    ChartSlotAxis,
    _battery_bar_times,
    _chart_time_series,
    _line_plot_float,
    _optional_float,
    _safe_float,
)
from ui.chart_trace_segments import (
    _hour_prices_from_df,
    _hourly_price_hover_labels,
    _hourly_price_hv_xy,
    _segment_connected_line_xy,
    _trace_segments,
)

_ENTLADESPERRE_BAND_HEIGHT_PCT = 4.0


_ENTLADESPERRE_BAND_Y_MIN = -5.0


_ENTLADESPERRE_BAND_WIDTH_FRACTION = 0.85


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
        action * elapsed_h,
        capacity,
        params["efficiency"],
        params["min_soc"],
        params["max_soc"],
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


def _entladesperre_band_marker() -> dict:
    return dict(
        color=CHART_ENTLADESPERRE_BAND_FILL,
        opacity=0.95,
        pattern=dict(
            shape=_CONSUMER_PV_FOLLOW_PATTERN,
            fgcolor=CHART_ENTLADESPERRE_BAND_STRIPE,
            bgcolor=CHART_ENTLADESPERRE_BAND_FILL,
            solidity=0.45,
            fillmode="overlay",
        ),
    )


def _entladesperre_soc_band_bottom(soc: float) -> float:
    return max(_ENTLADESPERRE_BAND_Y_MIN, soc - _ENTLADESPERRE_BAND_HEIGHT_PCT)


def add_entladesperre_soc_band_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Gelb-schwarz gestreiftes Band knapp unter dem SoC bei Entladesperre."""
    if "Steuerbefehl" not in df.columns or "Simulierter SoC (%)" not in df.columns:
        return
    commands = df["Steuerbefehl"]
    soc_series = df["Simulierter SoC (%)"]
    uhrzeit = df["Uhrzeit"]
    segments = _trace_segments(len(df), extrap_start, extrap_end)
    legend_shown = False
    for start, end, _is_extrapolated in segments:
        indices = [
            index
            for index in range(start, end)
            if _is_entladesperre_command(commands.iloc[index])
        ]
        if not indices:
            continue
        xs: list = []
        ys: list[float] = []
        bases: list[float] = []
        widths: list[float] = []
        custom: list = []
        for index in indices:
            soc = _safe_float(soc_series.iloc[index], 0.0)
            band_bottom = _entladesperre_soc_band_bottom(soc)
            band_height = max(0.0, soc - band_bottom)
            if band_height <= 0:
                continue
            xs.append(_battery_bar_times(axis, index).iloc[0])
            ys.append(band_height)
            bases.append(band_bottom)
            widths.append(
                axis.bar_width_ms(_ENTLADESPERRE_BAND_WIDTH_FRACTION, index)
            )
            custom.append(uhrzeit.iloc[index])
        if not xs:
            continue
        fig.add_trace(go.Bar(
            x=xs,
            y=ys,
            base=bases,
            name="Entladesperre",
            showlegend=not legend_shown,
            marker=_entladesperre_band_marker(),
            width=widths,
            yaxis="y2",
            customdata=custom,
            hovertemplate=(
                "Uhrzeit: %{customdata}<br>Entladesperre aktiv<extra></extra>"
            ),
        ))
        legend_shown = True


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
            seg_tail_for_line = None if ramp_after is not None else seg_tail
            soc_x, soc_y = _segment_connected_line_xy(
                axis, soc, abs_start, abs_end, tail_y=seg_tail_for_line,
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
    if matched_baseline_df is None or matched_baseline_df.empty:
        return
    matched_axis = ChartSlotAxis.from_dataframe(matched_baseline_df)
    length = len(matched_baseline_df)
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
                    matched_baseline_df.iloc[-1],
                    battery_params=battery_params,
                )
            ramp_after: tuple[datetime, float, datetime, float] | None = None
            if chart_now is not None:
                ramp_after = _current_hour_soc_ramp(
                    matched_axis,
                    matched_baseline_df["Simulierter SoC (%)"],
                    matched_baseline_df,
                    chart_now,
                    abs_start,
                    abs_end,
                    history_slot_count,
                    y_at_now=soc_at_now,
                    battery_params=battery_params,
                )
            seg_tail_for_line = None if ramp_after is not None else seg_tail
            matched_x, matched_y = _segment_connected_line_xy(
                matched_axis,
                matched_baseline_df["Simulierter SoC (%)"],
                abs_start,
                abs_end,
                tail_y=seg_tail_for_line,
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
                matched_baseline_df["Uhrzeit"],
                matched_axis.starts,
            )
            show_legend = index == 0
            fig.add_trace(go.Scatter(
                x=matched_x,
                y=matched_y,
                name="SoC BL Ziel",
                showlegend=show_legend,
            mode="lines",
            line=dict(color=COLOR_SOC, width=2.5, dash="dot"),
            opacity=1.0,
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
) -> None:
    """Strompreis auf der SoC-Achse — stündliche Stufen, an Slot-Rändern ausgerichtet."""
    del extrap_start, extrap_end
    line_x, line_y = _hourly_price_hv_xy(axis, df)
    if line_x.empty:
        return
    hour_prices = _hour_prices_from_df(df)
    customdata: list[float] = []
    hour_idx = 0
    for x in line_x:
        x_ts = pd.Timestamp(x)
        while hour_idx + 1 < len(hour_prices):
            next_hour = hour_prices[hour_idx + 1][0]
            if x_ts >= pd.Timestamp(next_hour):
                hour_idx += 1
            else:
                break
        customdata.append(hour_prices[hour_idx][1])
    fig.add_trace(go.Scatter(
        x=line_x,
        y=line_y,
        name="Preis",
        showlegend=True,
        mode="lines",
        line=dict(color="red", width=2.5, shape="hv"),
        opacity=1.0,
        yaxis=yaxis,
        text=_hourly_price_hover_labels(df, line_x),
        customdata=customdata,
        hovertemplate=(
            "Uhrzeit: %{text}<br>Preis: %{customdata:.2f} Cent/kWh"
            "<extra></extra>"
        ),
    ))


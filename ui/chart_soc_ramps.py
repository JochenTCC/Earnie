"""SoC ramp / extrapolation helpers for Chart 2."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import config
import pandas as pd

from data.planning_window import normalize_hour_slot
from optimizer import battery as bat
from optimizer.slot_duration import (
    DEFAULT_DT_H,
    normalize_quarter_hour_slot,
    slot_step,
)
from runtime_store.history_timeline import CHART_IST_BATTERY_KW_COLUMN
from ui.chart_slot_axis import (
    ChartSlotAxis,
    _chart_time_series,
    _line_plot_float,
    _optional_float,
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

def _soc_y_for_chart_now(
    axis: ChartSlotAxis,
    soc: pd.Series,
    df: pd.DataFrame,
    chart_now: datetime,
    history_slot_count: int,
    battery_params: dict | None = None,
) -> float:
    """
    SoC am Jetzt — gleiche Quelle wie die aktuelle Stunden-Rampe.

    Sobald weitere MILP-Viertel in der laufenden Stunde folgen, entlang der
    MILP-Polylinie (nicht Ist-Extrapolation aus dem letzten Log-Slot); sonst
    Log-Extrapolation. So treffen SoC und SoC BL Ziel am Jetzt-Marker.
    """
    seg_end = len(soc)
    quarter_start = normalize_quarter_hour_slot(chart_now)
    quarter_end = quarter_start + slot_step()
    hour_end = normalize_hour_slot(chart_now) + timedelta(hours=1)
    later_milp = _has_milp_slots_between(
        axis, quarter_end, hour_end, 0, seg_end, history_slot_count,
    )
    start_idx = _slot_index_at_or_after(axis, quarter_start, 0, seg_end)
    if (
        later_milp
        and start_idx is not None
        and start_idx >= history_slot_count
    ):
        return _soc_on_milp_polyline(
            axis, soc, chart_now, start_idx, seg_end,
        )
    return _soc_from_history_extrapolation(
        axis, soc, df, chart_now, history_slot_count,
        battery_params=battery_params,
    )

def _soc_at_chart_now(
    axis: ChartSlotAxis,
    df: pd.DataFrame,
    chart_now: datetime | None,
    history_slot_count: int | None,
    battery_params: dict | None = None,
) -> float | None:
    """SoC am Jetzt-Marker (Referenz für BL-Ziel-Anker und Opt-Rampe)."""
    if (
        chart_now is None
        or chart_now.tzinfo is None
        or history_slot_count is None
        or history_slot_count <= 0
    ):
        return None
    soc = df["Simulierter SoC (%)"]
    value = _soc_y_for_chart_now(
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

def _slot_index_at_or_after(
    axis: ChartSlotAxis,
    moment: datetime,
    seg_start: int,
    seg_end: int,
) -> int | None:
    moment_ts = pd.Timestamp(moment)
    for index in range(seg_start, seg_end):
        if axis.starts.iloc[index] >= moment_ts:
            return index
    return None

def _has_milp_slots_between(
    axis: ChartSlotAxis,
    start_exclusive: datetime,
    end_exclusive: datetime,
    seg_start: int,
    seg_end: int,
    history_slot_count: int | None,
) -> bool:
    """True if a MILP slot start lies in (start_exclusive, end_exclusive)."""
    lo = pd.Timestamp(start_exclusive)
    hi = pd.Timestamp(end_exclusive)
    for index in range(seg_start, seg_end):
        if history_slot_count is not None and index < history_slot_count:
            continue
        stamp = axis.starts.iloc[index]
        if lo < stamp < hi:
            return True
    return False

def _soc_on_milp_polyline(
    axis: ChartSlotAxis,
    soc: pd.Series,
    moment: datetime,
    slot_idx: int,
    seg_end: int,
) -> float:
    """SoC along planned slot polyline at ``moment`` (within/after ``slot_idx``)."""
    t0 = axis.starts.iloc[slot_idx].to_pydatetime()
    y0 = _line_plot_float(soc.iloc[slot_idx])
    if moment <= t0 or math.isnan(y0):
        return y0
    if slot_idx + 1 >= seg_end or slot_idx + 1 >= len(soc):
        return y0
    t1 = axis.starts.iloc[slot_idx + 1].to_pydatetime()
    y1 = _line_plot_float(soc.iloc[slot_idx + 1])
    span = (t1 - t0).total_seconds()
    if span <= 0 or math.isnan(y1):
        return y0
    frac = min(1.0, max(0.0, (moment - t0).total_seconds() / span))
    return y0 + frac * (y1 - y0)

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
    Rampe laufende MILP-Viertelstunde → Jetzt (keine konstante MILP-Soll-Treppe).

    Nur innerhalb der aktuellen Viertelstunde — spätere MILP-Slots der Stunde
    bleiben erhalten (sonst divergiert SoC vom ESS-Underlay).
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

    quarter_start = normalize_quarter_hour_slot(now)
    milp_start = axis.starts.iloc[milp_idx].to_pydatetime()
    t_start = max(milp_start, quarter_start)
    if now <= t_start:
        return None

    start_idx = _slot_index_at_or_after(axis, t_start, seg_start, seg_end)
    if start_idx is None:
        return None
    quarter_end = quarter_start + slot_step()
    later_milp = _has_milp_slots_between(
        axis, quarter_end, hour_end, seg_start, seg_end, history_slot_count,
    )
    y_start, y_end = _ramp_before_ys(
        {
            "axis": axis,
            "soc": soc,
            "df": df,
            "now": now,
            "t_start": t_start,
            "start_idx": start_idx,
            "seg_end": seg_end,
            "later_milp": later_milp,
            "history_slot_count": history_slot_count,
            "y_at_now": y_at_now,
            "battery_params": battery_params,
        }
    )
    if math.isnan(y_start) or math.isnan(y_end):
        return None
    return t_start, y_start, now, y_end


def _ramp_before_ys(ctx: dict) -> tuple[float, float]:
    use_milp_polyline = (
        ctx["later_milp"]
        and (
            ctx["history_slot_count"] is None
            or ctx["start_idx"] >= ctx["history_slot_count"]
        )
    )
    if use_milp_polyline:
        y_start = _line_plot_float(ctx["soc"].iloc[ctx["start_idx"]])
        if ctx["y_at_now"] is not None:
            return y_start, ctx["y_at_now"]
        return y_start, _soc_on_milp_polyline(
            ctx["axis"], ctx["soc"], ctx["now"], ctx["start_idx"], ctx["seg_end"],
        )
    y_start = _soc_from_history_extrapolation(
        ctx["axis"],
        ctx["soc"],
        ctx["df"],
        ctx["t_start"],
        ctx["history_slot_count"],
        battery_params=ctx["battery_params"],
    )
    if ctx["y_at_now"] is not None:
        return y_start, ctx["y_at_now"]
    return y_start, _soc_from_history_extrapolation(
        ctx["axis"],
        ctx["soc"],
        ctx["df"],
        ctx["now"],
        ctx["history_slot_count"],
        battery_params=ctx["battery_params"],
    )

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
    Rampe Jetzt → Ende der aktuellen Viertelstunde (oder Stundenende).

    Wenn weitere MILP-Viertel in derselben Stunde folgen, nur bis
    Viertelstundenende rampen — sonst würde die geplante SoC-Kurve
    (und der ESS-Underlay) zwischen Jetzt und Stundenende gelöscht.
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

    quarter_start = normalize_quarter_hour_slot(now)
    quarter_end = quarter_start + slot_step()
    later_milp = _has_milp_slots_between(
        axis, quarter_end, hour_end, seg_start, seg_end, history_slot_count,
    )
    window = {
        "axis": axis,
        "soc": soc,
        "df": df,
        "seg_start": seg_start,
        "seg_end": seg_end,
        "history_slot_count": history_slot_count,
        "battery_params": battery_params,
        "later_milp": later_milp,
        "quarter_start": quarter_start,
        "quarter_end": quarter_end,
        "hour_end": hour_end,
        "milp_idx": milp_idx,
        "y_at_now": y_at_now,
    }
    end_point = _ramp_end_point(window)
    if end_point is None:
        return None
    t_end, y_end = end_point
    t_start = max(now, hour_start)
    window["t_start"] = t_start
    y_start = _ramp_start_soc(window)
    if math.isnan(y_start):
        y_start = _soc_y_at_moment(axis, soc, t_start, seg_end)
    if math.isnan(y_start) or math.isnan(y_end) or t_start >= t_end:
        return None
    return t_start, y_start, t_end, y_end


def _ramp_end_point(window: dict) -> tuple[datetime, float] | None:
    if window["later_milp"]:
        t_end = min(window["quarter_end"], window["hour_end"])
        end_idx = _slot_index_at_or_after(
            window["axis"], t_end, window["seg_start"], window["seg_end"],
        )
        if end_idx is None:
            return None
        return t_end, _line_plot_float(window["soc"].iloc[end_idx])
    y_end = _soc_tail_y_from_row(
        window["df"].iloc[window["milp_idx"]],
        battery_params=window["battery_params"],
    )
    if y_end is None:
        return None
    return window["hour_end"], y_end


def _ramp_start_soc(window: dict) -> float:
    if window["y_at_now"] is not None:
        return window["y_at_now"]
    if window["later_milp"]:
        start_idx = _slot_index_at_or_after(
            window["axis"],
            window["quarter_start"],
            window["seg_start"],
            window["seg_end"],
        )
        if start_idx is None:
            return float("nan")
        if (
            window["history_slot_count"] is not None
            and start_idx < window["history_slot_count"]
        ):
            return _soc_from_history_extrapolation(
                window["axis"],
                window["soc"],
                window["df"],
                window["t_start"],
                window["history_slot_count"],
                battery_params=window["battery_params"],
            )
        return _soc_on_milp_polyline(
            window["axis"],
            window["soc"],
            window["t_start"],
            start_idx,
            window["seg_end"],
        )
    if window["history_slot_count"] is not None and window["history_slot_count"] > 0:
        return _soc_from_history_extrapolation(
            window["axis"],
            window["soc"],
            window["df"],
            window["t_start"],
            window["history_slot_count"],
            battery_params=window["battery_params"],
        )
    return float("nan")

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

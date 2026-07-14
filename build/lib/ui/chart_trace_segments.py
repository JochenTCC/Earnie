"""Segmentierte Linien- und Balken-Traces für Charts."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from data.planning_window import normalize_hour_slot
from ui.chart_colors import CHART_PV_FILL_COLOR, CHART_PV_LINE_COLOR
from ui.chart_slot_axis import (
    ChartSlotAxis,
    _BAR_CENTER_NUDGE,
    _EMPTY_FLOAT_SERIES,
    _LINE_ANCHOR_SLOT_CENTER,
    _LINE_ANCHOR_SLOT_START,
    _anchor_fraction_from_legacy_shift,
    _chart_time_series,
    _empty_chart_time_series,
    _line_plot_float,
    _optional_float,
    _slot_indices_for_hour,
    _zone_slot_left,
    _zone_slot_right,
)

def _extended_line_xy(
    axis: ChartSlotAxis,
    y: pd.Series,
    tail_y: float | None = None,
    *,
    anchor_fraction: float = _LINE_ANCHOR_SLOT_START,
) -> tuple[pd.Series, pd.Series]:
    """Verlängert Linien bis zum rechten Slot-Rand (Ende des letzten Slots)."""
    if y.empty:
        return axis.at(slice(None), anchor_fraction), y
    tail_time = axis.legacy_index_time(len(axis.starts) - 0.5)
    extended_x = pd.concat(
        [axis.at(slice(None), anchor_fraction), pd.Series([tail_time])],
        ignore_index=True,
    )
    end_y = y.iloc[-1] if tail_y is None else tail_y
    extended_y = pd.concat([y, pd.Series([end_y])], ignore_index=True)
    return extended_x, extended_y


def _extended_hover_labels(uhrzeit: pd.Series) -> list[str]:
    """Hover-Labels für verlängerte Linien (letzte Uhrzeit einmal wiederholt)."""
    if uhrzeit.empty:
        return []
    return pd.concat(
        [uhrzeit, pd.Series([uhrzeit.iloc[-1]])],
        ignore_index=True,
    ).tolist()


def _line_hover(uhrzeit: pd.Series, y_format: str) -> dict:
    return dict(
        customdata=_extended_hover_labels(uhrzeit),
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>%{fullData.name}: "
            f"%{{y:{y_format}}}<extra></extra>"
        ),
    )


def _bar_hover(uhrzeit: pd.Series, y_format: str) -> dict:
    return dict(
        customdata=uhrzeit,
        hovertemplate=(
            "Uhrzeit: %{customdata}<br>%{fullData.name}: "
            f"%{{y:{y_format}}}<extra></extra>"
        ),
    )


def _price_extrapolated_mask(df: pd.DataFrame) -> pd.Series:
    if "Preis extrapoliert" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["Preis extrapoliert"].fillna(False).astype(bool)


def _extrapolation_bounds(df: pd.DataFrame) -> tuple[int | None, int | None]:
    """Liefert [start, end) der ersten extrapolierten Slot-Gruppe oder (None, None)."""
    mask = _price_extrapolated_mask(df)
    positions = [index for index, flagged in enumerate(mask) if flagged]
    if not positions:
        return None, None
    return positions[0], positions[-1] + 1


def _trace_segments(
    length: int,
    extrap_start: int | None,
    extrap_end: int | None,
) -> list[tuple[int, int, bool]]:
    if extrap_start is None or extrap_end is None:
        return [(0, length, False)]
    segments: list[tuple[int, int, bool]] = []
    if extrap_start > 0:
        segments.append((0, extrap_start, False))
    segments.append((extrap_start, extrap_end, True))
    if extrap_end < length:
        segments.append((extrap_end, length, False))
    return segments


def _bar_widths_ms(
    axis: ChartSlotAxis,
    start: int,
    end: int,
    width_fraction: float,
) -> list[float]:
    return [
        axis.bar_width_ms(width_fraction, index)
        for index in range(start, end)
    ]


def _hour_prices_from_df(df: pd.DataFrame) -> list[tuple[datetime, float]]:
    """Ein Preis pro volle Stunde (chronologisch), bevorzugt Wert am Stunden-Slot."""
    by_hour: dict[datetime, float] = {}
    for _, row in df.iterrows():
        slot = pd.Timestamp(row["slot_datetime"]).to_pydatetime()
        hour = normalize_hour_slot(slot)
        price = _optional_float(row.get("Strompreis (Cent/kWh)"))
        if price is None:
            continue
        if slot == hour or hour not in by_hour:
            by_hour[hour] = price
    ordered: list[tuple[datetime, float]] = []
    seen: set[datetime] = set()
    for _, row in df.iterrows():
        hour = normalize_hour_slot(pd.Timestamp(row["slot_datetime"]).to_pydatetime())
        if hour in seen or hour not in by_hour:
            continue
        seen.add(hour)
        ordered.append((hour, by_hour[hour]))
    return ordered


def _hourly_price_hv_xy(
    axis: ChartSlotAxis,
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    """
    Preis-Treppe mit Stufen nur an Stundengrenzen (Spec: stündlicher Marktpreis).

    Bei gemischter 15-min/1-h-Achse spannt jede Stufe die volle Stundenbreite auf der Achse.
    """
    hour_prices = _hour_prices_from_df(df)
    if not hour_prices:
        return _empty_chart_time_series(), _EMPTY_FLOAT_SERIES
    points_x: list[datetime] = []
    points_y: list[float] = []
    for hour, price in hour_prices:
        indices = _slot_indices_for_hour(axis, hour)
        if not indices:
            continue
        x_left = _zone_slot_left(axis, indices[0])
        x_right = _zone_slot_right(axis, indices[-1])
        if not points_x:
            points_x.extend([x_left, x_right])
            points_y.extend([price, price])
            continue
        if x_left != points_x[-1]:
            points_x.append(x_left)
            points_y.append(points_y[-1])
        if price != points_y[-1]:
            points_x.append(x_left)
            points_y.append(price)
        points_x.append(x_right)
        points_y.append(price)
    tail_x = axis.legacy_index_time(len(axis.starts) - 0.5)
    if points_x and pd.Timestamp(points_x[-1]) < pd.Timestamp(tail_x):
        points_x.append(tail_x)
        points_y.append(points_y[-1])
    return _chart_time_series(points_x), pd.Series(points_y, dtype=float)


def _hourly_price_hover_labels(
    df: pd.DataFrame,
    line_x: pd.Series,
) -> list[str]:
    """Hover-Uhrzeit je Punkt entlang der stündlichen Preis-Treppe."""
    hour_prices = _hour_prices_from_df(df)
    if not hour_prices or line_x.empty:
        return []
    labels: list[str] = []
    hour_idx = 0
    for x in line_x:
        x_ts = pd.Timestamp(x)
        while hour_idx + 1 < len(hour_prices):
            _hour, _ = hour_prices[hour_idx + 1]
            if x_ts >= pd.Timestamp(_hour):
                hour_idx += 1
            else:
                break
        labels.append(hour_prices[hour_idx][0].strftime("%d.%m. %H:%M"))
    return labels


def _segment_extended_line(
    axis: ChartSlotAxis,
    y: pd.Series,
    start: int,
    end: int,
    tail_y: float | None = None,
    *,
    anchor_fraction: float = _LINE_ANCHOR_SLOT_START,
) -> tuple[pd.Series, pd.Series]:
    if start >= end:
        return _empty_chart_time_series(), _EMPTY_FLOAT_SERIES
    return _extended_line_xy(
        axis.slice(start, end),
        y.iloc[start:end],
        tail_y=tail_y,
        anchor_fraction=anchor_fraction,
    )


def _segment_linear_connected_line_xy(
    axis: ChartSlotAxis,
    y: pd.Series,
    start: int,
    end: int,
    tail_y: float | None = None,
    *,
    anchor_fraction: float = _LINE_ANCHOR_SLOT_START,
    bridge_left: bool = True,
) -> tuple[pd.Series, pd.Series]:
    """
    Stückweise lineare Verbindung ohne Stufen an Segmentgrenzen.

    anchor_fraction 0.0: Anker am Slotbeginn (früher Index −0.5).
    anchor_fraction 0.5: Slotmitte (früher Index +0.0, wie Flex-Balken).
    """
    if start >= end:
        return _empty_chart_time_series(), _EMPTY_FLOAT_SERIES

    points_x: list[datetime] = []
    points_y: list[float] = []

    if bridge_left and start > 0 and start - 1 < len(y):
        points_x.append(axis.at(start - 1, anchor_fraction).iloc[0])
        points_y.append(_line_plot_float(y.iloc[start - 1]))

    for hour_index in range(start, end):
        points_x.append(axis.at(hour_index, anchor_fraction).iloc[0])
        points_y.append(_line_plot_float(y.iloc[hour_index]))

    if end == len(axis.starts):
        points_x.append(axis.legacy_index_time(len(axis.starts) - 0.5))
        points_y.append(
            _line_plot_float(y.iloc[end - 1]) if tail_y is None else float(tail_y)
        )

    return _chart_time_series(points_x), pd.Series(points_y, dtype=float)


def _segment_connected_line_xy(
    axis: ChartSlotAxis,
    y: pd.Series,
    start: int,
    end: int,
    tail_y: float | None = None,
    *,
    step_line: bool = True,
    anchor_fraction: float = _LINE_ANCHOR_SLOT_START,
    bridge_left: bool = True,
) -> tuple[pd.Series, pd.Series]:
    """
    Linienabschnitt inkl. Brückenpunkt an der linken Grenze.

    step_line=True (HV): vertikaler Übergang an der Segmentgrenze.
    step_line=False (SoC o.ä.): durchgehender linearer Verlauf ohne Stufe.
    """
    if not step_line:
        return _segment_linear_connected_line_xy(
            axis, y, start, end, tail_y=tail_y,
            anchor_fraction=anchor_fraction, bridge_left=bridge_left,
        )

    if start >= end:
        return _empty_chart_time_series(), _EMPTY_FLOAT_SERIES
    seg_tail = tail_y if end == len(axis.starts) else None
    line_x, line_y = _segment_extended_line(
        axis, y, start, end, tail_y=seg_tail, anchor_fraction=anchor_fraction
    )
    if start > 0 and start - 1 < len(y) and bridge_left:
        boundary_x = axis.at(start, anchor_fraction).iloc[0]
        bridge_y = float(y.iloc[start - 1])
        line_x = pd.concat([pd.Series([boundary_x]), line_x], ignore_index=True)
        line_y = pd.concat([pd.Series([bridge_y]), line_y], ignore_index=True)
    return line_x, line_y


def _segment_hover_labels(
    uhrzeit: pd.Series,
    start: int,
    end: int,
    *,
    step_line: bool = True,
    point_count: int | None = None,
) -> list[str]:
    if start >= end:
        return []
    if not step_line:
        segment = uhrzeit.iloc[start:end]
        if start > 0:
            labels = [str(uhrzeit.iloc[start - 1])]
            labels.extend(str(value) for value in segment)
        else:
            labels = [str(value) for value in segment]
        if end == len(uhrzeit) and not segment.empty:
            labels.append(str(segment.iloc[-1]))
        if point_count is not None:
            return labels[:point_count]
        return labels
    labels = _extended_hover_labels(uhrzeit.iloc[start:end])
    if start > 0:
        labels = [str(uhrzeit.iloc[start - 1])] + labels
    if point_count is not None:
        return labels[:point_count]
    return labels


def _add_segmented_hv_line(
    fig: go.Figure,
    axis: ChartSlotAxis,
    y: pd.Series,
    uhrzeit: pd.Series,
    segments: list[tuple[int, int, bool]],
    *,
    name: str,
    line_kwargs: dict,
    yaxis: str = "y",
    y_format: str = ".2f",
    base_opacity: float = 1.0,
    tail_y: float | None = None,
    custom_hover_values: pd.Series | None = None,
    hover_template: str | None = None,
    segment_hover_template: str | None = None,
    anchor_fraction: float = _LINE_ANCHOR_SLOT_START,
    bridge_left: bool = True,
) -> None:
    for index, (start, end, _is_extrapolated) in enumerate(segments):
        if start >= end:
            continue
        seg_tail = tail_y if end == len(axis.starts) else None
        line_x, line_y = _segment_connected_line_xy(
            axis,
            y,
            start,
            end,
            tail_y=seg_tail,
            step_line=True,
            anchor_fraction=anchor_fraction,
            bridge_left=bridge_left,
        )
        if line_x.empty:
            continue
        trace_kwargs: dict = dict(
            x=line_x,
            y=line_y,
            name=name if index == 0 else name,
            showlegend=index == 0,
            mode="lines",
            line=dict(line_kwargs),
            opacity=base_opacity,
            yaxis=yaxis,
        )
        if custom_hover_values is not None and hover_template is not None:
            hover_values = custom_hover_values.iloc[start:end]
            cent_labels = pd.concat(
                [hover_values, pd.Series([hover_values.iloc[-1]])],
                ignore_index=True,
            ).tolist()
            if start > 0:
                cent_labels = [float(custom_hover_values.iloc[start - 1])] + cent_labels
            trace_kwargs.update(
                customdata=cent_labels,
                hovertemplate=hover_template,
                text=_segment_hover_labels(uhrzeit, start, end),
            )
        elif segment_hover_template is not None:
            trace_kwargs.update(
                customdata=_segment_hover_labels(uhrzeit, start, end),
                hovertemplate=segment_hover_template,
            )
        else:
            trace_kwargs.update(
                customdata=_segment_hover_labels(uhrzeit, start, end),
                hovertemplate=(
                    "Uhrzeit: %{customdata}<br>%{fullData.name}: "
                    f"%{{y:{y_format}}}<extra></extra>"
                ),
            )
        fig.add_trace(go.Scatter(**trace_kwargs))


def _add_pv_trace(
    fig: go.Figure,
    axis: ChartSlotAxis,
    pv_kw: pd.Series,
    uhrzeit: pd.Series,
) -> None:
    """PV-Verlauf mit gelber Fläche — Anker in der Slotmitte, glatte Interpolation."""
    pv_x, pv_y = _extended_line_xy(
        axis, pv_kw, anchor_fraction=_LINE_ANCHOR_SLOT_CENTER
    )
    fig.add_trace(go.Scatter(
        x=pv_x,
        y=pv_y,
        name="PV",
        line=dict(color=CHART_PV_LINE_COLOR, width=2),
        fill="tozeroy",
        fillcolor=CHART_PV_FILL_COLOR,
        yaxis="y",
        **_line_hover(uhrzeit, ".2f"),
    ))


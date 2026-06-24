"""Plotly-Charts für 24h-Optimierungsdarstellung."""
from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from optimizer import battery as bat

_COLOR_BASELINE = "#7f8c8d"
_COLOR_OPTIMIZED = "#e67e22"
_EXTRAPOLATED_TRACE_OPACITY = 0.5
_PV_LINE_COLOR = "#f1c40f"
_PV_FILL_COLOR = "rgba(241, 196, 15, 0.15)"
_CONSUMER_PALETTE_START = (127, 140, 141)
_CONSUMER_PALETTE_END = (0, 188, 212)


def get_bar_colors(df: pd.DataFrame) -> list[str]:
    """Batterie-Balkenfarbe je Steuerbefehl (Modus)."""
    colors = []
    for cmd in df["Steuerbefehl"]:
        text = str(cmd)
        if text.startswith("Zwangsladen"):
            colors.append("forestgreen")
        elif text.startswith("Zwangsentladen"):
            colors.append("crimson")
        elif "Entladesperre" in text:
            colors.append("darkorange")
        elif text == "Baseline":
            colors.append("lightgray")
        elif text.startswith("Baseline (Ziel)"):
            colors.append("lightgray")
        else:
            colors.append("dodgerblue")
    return colors


def _active_consumer_bar_columns(df: pd.DataFrame) -> list[tuple[dict, str]]:
    """Verbraucher-Spalten mit sichtbaren Planwerten (> 0 kWh über den Tag)."""
    active = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = f"{consumer['name']} (kW)"
        if col in df.columns and df[col].sum() > 0:
            active.append((consumer, col))
    return active


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _lerp_rgb(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    factor: float,
) -> tuple[int, int, int]:
    return tuple(
        int(round(start[channel] + (end[channel] - start[channel]) * factor))
        for channel in range(3)
    )


def _consumer_bar_palette(count: int) -> list[str]:
    """Farben für Flex-Verbraucher: gleichmäßig von Grau nach Cyan."""
    if count <= 0:
        return []
    if count == 1:
        return [_rgb_to_hex(_lerp_rgb(_CONSUMER_PALETTE_START, _CONSUMER_PALETTE_END, 0.5))]
    return [
        _rgb_to_hex(
            _lerp_rgb(
                _CONSUMER_PALETTE_START,
                _CONSUMER_PALETTE_END,
                index / (count - 1),
            )
        )
        for index in range(count)
    ]


def _chart_slot_x(length: int) -> pd.Series:
    """Numerische Slot-Positionen 0..n-1 (eine Einheit = eine Stunde)."""
    return pd.Series(range(length), dtype=float)


def _chart_line_x(slot_x: pd.Series) -> pd.Series:
    """Linien um 30 min zurück auf Slot-Mitte, passend zu den Stunden-Balken."""
    return slot_x - 0.5


def _extended_line_xy(
    slot_x: pd.Series,
    y: pd.Series,
    tail_y: float | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Verlängert Linien um 1 h für die -0.5-Verschiebung (Ende des letzten Slots)."""
    if y.empty:
        return _chart_line_x(slot_x), y
    tail_slot = float(slot_x.iloc[-1]) + 1.0
    extended_slot = pd.concat(
        [slot_x, pd.Series([tail_slot])],
        ignore_index=True,
    )
    end_y = y.iloc[-1] if tail_y is None else tail_y
    extended_y = pd.concat([y, pd.Series([end_y])], ignore_index=True)
    return _chart_line_x(extended_slot), extended_y


def _soc_tail_y_from_row(row: pd.Series) -> float | None:
    """SoC am Ende der Stunde aus geplanter Batterieaktion (Optimierer/Huawei-Logik)."""
    if "Geplante Batterie-Aktion (kW)" not in row.index:
        return None
    params = config.get_battery_params()
    new_soc, _ = bat.apply_soc_change(
        float(row["Simulierter SoC (%)"]),
        float(row["Geplante Batterie-Aktion (kW)"]),
        params["battery_capacity_kwh"],
        params["efficiency"],
        params["min_soc"],
        params["max_soc"],
    )
    return round(new_soc, 1)


def _extended_soc_line_xy(
    slot_x: pd.Series,
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    soc = df["Simulierter SoC (%)"]
    tail_y = _soc_tail_y_from_row(df.iloc[-1]) if not df.empty else None
    return _extended_line_xy(slot_x, soc, tail_y=tail_y)


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


def _segment_opacity(base_opacity: float, is_extrapolated: bool) -> float:
    if is_extrapolated:
        return base_opacity * _EXTRAPOLATED_TRACE_OPACITY
    return base_opacity


def _segment_extended_line(
    slot_x: pd.Series,
    y: pd.Series,
    start: int,
    end: int,
    tail_y: float | None = None,
) -> tuple[pd.Series, pd.Series]:
    if start >= end:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    return _extended_line_xy(slot_x.iloc[start:end], y.iloc[start:end], tail_y=tail_y)


def _segment_linear_connected_line_xy(
    slot_x: pd.Series,
    y: pd.Series,
    start: int,
    end: int,
    tail_y: float | None = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Stückweise lineare Verbindung ohne Stufen an Segmentgrenzen.

    Endpunkt vor der Spiegelung = letzte Stunde des Segments (x = Slot − 0,5 h).
    Startpunkt danach = derselbe Punkt, weiter zum nächsten Stundenwert.
    """
    if start >= end:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    points_x: list[float] = []
    points_y: list[float] = []

    if start > 0:
        join_x = float(slot_x.iloc[start - 1]) - 0.5
        points_x.append(join_x)
        points_y.append(float(y.iloc[start - 1]))

    for hour_index in range(start, end):
        points_x.append(float(slot_x.iloc[hour_index]) - 0.5)
        points_y.append(float(y.iloc[hour_index]))

    if end == len(slot_x):
        points_x.append(float(slot_x.iloc[end - 1]) + 0.5)
        points_y.append(
            float(y.iloc[end - 1]) if tail_y is None else float(tail_y)
        )

    return pd.Series(points_x, dtype=float), pd.Series(points_y, dtype=float)


def _segment_connected_line_xy(
    slot_x: pd.Series,
    y: pd.Series,
    start: int,
    end: int,
    tail_y: float | None = None,
    *,
    step_line: bool = True,
) -> tuple[pd.Series, pd.Series]:
    """
    Linienabschnitt inkl. Brückenpunkt an der linken Grenze.

    step_line=True (HV): vertikaler Übergang an der Segmentgrenze.
    step_line=False (SoC o.ä.): durchgehender linearer Verlauf ohne Stufe.
    """
    if not step_line:
        return _segment_linear_connected_line_xy(slot_x, y, start, end, tail_y=tail_y)

    if start >= end:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    seg_tail = tail_y if end == len(slot_x) else None
    line_x, line_y = _segment_extended_line(slot_x, y, start, end, tail_y=seg_tail)
    if start > 0:
        boundary_x = float(slot_x.iloc[start]) - 0.5
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
    slot_x: pd.Series,
    y: pd.Series,
    uhrzeit: pd.Series,
    segments: list[tuple[int, int, bool]],
    *,
    name: str,
    line_kwargs: dict,
    yaxis: str = "y",
    y_format: str = ".2f",
    base_opacity: float = 1.0,
    extrapolated_dotted: bool = False,
    tail_y: float | None = None,
    custom_hover_values: pd.Series | None = None,
    hover_template: str | None = None,
    segment_hover_template: str | None = None,
) -> None:
    for index, (start, end, is_extrapolated) in enumerate(segments):
        if start >= end:
            continue
        seg_tail = tail_y if end == len(slot_x) else None
        line_x, line_y = _segment_connected_line_xy(
            slot_x, y, start, end, tail_y=seg_tail, step_line=True
        )
        if line_x.empty:
            continue
        line = dict(line_kwargs)
        if extrapolated_dotted and is_extrapolated:
            line["dash"] = "dot"
            opacity = 1.0
        else:
            opacity = _segment_opacity(base_opacity, is_extrapolated)
        trace_kwargs: dict = dict(
            x=line_x,
            y=line_y,
            name=name if index == 0 else name,
            showlegend=index == 0,
            mode="lines",
            line=line,
            opacity=opacity,
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


def _extrapolation_caption(df: pd.DataFrame) -> str | None:
    extrap_start, extrap_end = _extrapolation_bounds(df)
    if extrap_start is None:
        return None
    from_hour = df["Uhrzeit"].iloc[extrap_start]
    to_hour = df["Uhrzeit"].iloc[extrap_end - 1]
    return (
        f"Ab **{from_hour}** bis **{to_hour}**: Strompreis geschätzt "
        f"(Spiegelung gleicher Uhrzeit vom Vortag, gepunktete rote Linie). "
        f"Übrige Verläufe (ohne PV) in diesem Bereich mit 50 % Transparenz."
    )


def _add_pv_trace(
    fig: go.Figure,
    slot_x: pd.Series,
    pv_kw: pd.Series,
    uhrzeit: pd.Series,
) -> None:
    """PV-Verlauf mit gelber Fläche — unabhängig von extrapolierten Preisen."""
    pv_x, pv_y = _extended_line_xy(slot_x, pv_kw)
    fig.add_trace(go.Scatter(
        x=pv_x,
        y=pv_y,
        name="PV",
        line=dict(color=_PV_LINE_COLOR, width=2),
        fill="tozeroy",
        fillcolor=_PV_FILL_COLOR,
        yaxis="y",
        **_line_hover(uhrzeit, ".2f"),
    ))


def _chart_xaxis_config(uhrzeit: pd.Series) -> dict:
    tickvals = list(range(len(uhrzeit)))
    return dict(
        title="Uhrzeit (Stunden-Slots / Intervalle)",
        type="linear",
        tickmode="array",
        tickvals=tickvals,
        ticktext=uhrzeit.tolist(),
        range=[-0.5, len(uhrzeit) - 0.5],
    )


def _consumer_bar_x(
    slot_x: pd.Series,
    index: int,
    count: int,
    bar_width: float,
    base_offset: float,
) -> pd.Series:
    """X-Position je Stunde: nebeneinander und mit Batterie im selben Slot zentriert."""
    if count <= 1:
        return slot_x + base_offset
    shift = (index - (count - 1) / 2) * bar_width
    return slot_x + base_offset + shift


def add_power_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    bar_colors: list[str],
    slot_x: pd.Series,
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    battery_bar_width = 0.9
    bar_offset = 0.05
    uhrzeit = df["Uhrzeit"]
    segments = _trace_segments(len(df), extrap_start, extrap_end)
    active_consumers = _active_consumer_bar_columns(df)
    consumer_count = len(active_consumers)
    consumer_bar_width = (
        battery_bar_width / consumer_count if consumer_count else battery_bar_width
    )
    consumer_colors = _consumer_bar_palette(consumer_count)
    if "PV-Prognose (kW)" in df.columns:
        _add_pv_trace(fig, slot_x, df["PV-Prognose (kW)"], uhrzeit)

    if "Verbrauch-Prognose (kW)" in df.columns:
        _add_segmented_hv_line(
            fig,
            slot_x,
            df["Verbrauch-Prognose (kW)"],
            uhrzeit,
            segments,
            name="Verbrauch",
            line_kwargs=dict(color="#3498db", width=2, dash="dash"),
            y_format=".2f",
            base_opacity=1.0,
        )

    for seg_index, (start, end, is_extrapolated) in enumerate(segments):
        if start >= end:
            continue
        fig.add_trace(go.Bar(
            x=slot_x.iloc[start:end] + bar_offset,
            y=df["Geplante Batterie-Aktion (kW)"].iloc[start:end],
            name="Batterie" if seg_index == 0 else "Batterie",
            showlegend=seg_index == 0,
            marker=dict(color=bar_colors[start:end]),
            opacity=_segment_opacity(0.75, is_extrapolated),
            width=battery_bar_width,
            yaxis="y",
            customdata=uhrzeit.iloc[start:end],
            hovertemplate=(
                "Uhrzeit: %{customdata}<br>%{fullData.name}: "
                "%{y:.2f}<extra></extra>"
            ),
        ))

    for consumer_index, (consumer, col) in enumerate(active_consumers):
        for seg_index, (start, end, is_extrapolated) in enumerate(segments):
            if start >= end:
                continue
            fig.add_trace(go.Bar(
                x=_consumer_bar_x(
                    slot_x.iloc[start:end],
                    consumer_index,
                    consumer_count,
                    consumer_bar_width,
                    bar_offset,
                ),
                y=df[col].iloc[start:end],
                name=consumer["name"] if seg_index == 0 else consumer["name"],
                showlegend=seg_index == 0,
                marker=dict(color=consumer_colors[consumer_index]),
                opacity=_segment_opacity(0.65, is_extrapolated),
                width=consumer_bar_width,
                yaxis="y",
                customdata=uhrzeit.iloc[start:end],
                hovertemplate=(
                    "Uhrzeit: %{customdata}<br>%{fullData.name}: "
                    "%{y:.2f}<extra></extra>"
                ),
            ))


def add_optimized_soc_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    slot_x: pd.Series,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    uhrzeit = df["Uhrzeit"]
    segments = _trace_segments(len(df), extrap_start, extrap_end)
    soc = df["Simulierter SoC (%)"]
    tail_y = _soc_tail_y_from_row(df.iloc[-1]) if not df.empty else None
    for index, (start, end, is_extrapolated) in enumerate(segments):
        if start >= end:
            continue
        seg_tail = tail_y if end == len(slot_x) else None
        soc_x, soc_y = _segment_connected_line_xy(
            slot_x, soc, start, end, tail_y=seg_tail, step_line=False
        )
        if soc_x.empty:
            continue
        fig.add_trace(go.Scatter(
            x=soc_x,
            y=soc_y,
            name="SoC" if index == 0 else "SoC",
            showlegend=index == 0,
            mode="lines",
            line=dict(color=_COLOR_OPTIMIZED, width=2.5),
            opacity=_segment_opacity(1.0, is_extrapolated),
            yaxis=yaxis,
            customdata=_segment_hover_labels(
                uhrzeit,
                start,
                end,
                step_line=False,
                point_count=len(soc_x),
            ),
            hovertemplate=(
                "Uhrzeit: %{customdata}<br>%{fullData.name}: "
                "%{y:.1f}<extra></extra>"
            ),
        ))


def add_baseline_soc_traces(
    fig: go.Figure,
    baseline_df: pd.DataFrame | None,
    matched_baseline_df: pd.DataFrame | None,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    segments = _trace_segments(
        len(baseline_df) if baseline_df is not None and not baseline_df.empty else 0,
        extrap_start,
        extrap_end,
    )
    if baseline_df is not None and not baseline_df.empty:
        baseline_slot_x = _chart_slot_x(len(baseline_df))
        for index, (start, end, is_extrapolated) in enumerate(segments):
            if start >= end:
                continue
            seg_tail = None
            if end == len(baseline_slot_x):
                seg_tail = _soc_tail_y_from_row(baseline_df.iloc[-1])
            baseline_x, baseline_y = _segment_connected_line_xy(
                baseline_slot_x,
                baseline_df["Simulierter SoC (%)"],
                start,
                end,
                tail_y=seg_tail,
                step_line=False,
            )
            if baseline_x.empty:
                continue
            fig.add_trace(go.Scatter(
                x=baseline_x,
                y=baseline_y,
                name="SoC BL Profil" if index == 0 else "SoC BL Profil",
                showlegend=index == 0,
                mode="lines",
                line=dict(color=_COLOR_BASELINE, width=2.5, dash="dash"),
                opacity=_segment_opacity(1.0, is_extrapolated),
                yaxis=yaxis,
                customdata=_segment_hover_labels(
                    baseline_df["Uhrzeit"],
                    start,
                    end,
                    step_line=False,
                    point_count=len(baseline_x),
                ),
                hovertemplate=(
                    "Uhrzeit: %{customdata}<br>%{fullData.name}: "
                    "%{y:.1f}<extra></extra>"
                ),
            ))
    if matched_baseline_df is not None and not matched_baseline_df.empty:
        matched_slot_x = _chart_slot_x(len(matched_baseline_df))
        matched_segments = _trace_segments(len(matched_baseline_df), extrap_start, extrap_end)
        for index, (start, end, is_extrapolated) in enumerate(matched_segments):
            if start >= end:
                continue
            seg_tail = None
            if end == len(matched_slot_x):
                seg_tail = _soc_tail_y_from_row(matched_baseline_df.iloc[-1])
            matched_x, matched_y = _segment_connected_line_xy(
                matched_slot_x,
                matched_baseline_df["Simulierter SoC (%)"],
                start,
                end,
                tail_y=seg_tail,
                step_line=False,
            )
            if matched_x.empty:
                continue
            fig.add_trace(go.Scatter(
                x=matched_x,
                y=matched_y,
                name="SoC BL Ziel" if index == 0 else "SoC BL Ziel",
                showlegend=index == 0,
                mode="lines",
                line=dict(color=_COLOR_BASELINE, width=2.5, dash="dot"),
                opacity=_segment_opacity(1.0, is_extrapolated),
                yaxis=yaxis,
                customdata=_segment_hover_labels(
                    matched_baseline_df["Uhrzeit"],
                    start,
                    end,
                    step_line=False,
                    point_count=len(matched_x),
                ),
                hovertemplate=(
                    "Uhrzeit: %{customdata}<br>%{fullData.name}: "
                    "%{y:.1f}<extra></extra>"
                ),
            ))


def _scale_series_to_0_100(values: pd.Series) -> pd.Series:
    """Lineare Skalierung auf 0–100 (für gemeinsame Achse mit SoC)."""
    lo = float(values.min())
    hi = float(values.max())
    if hi - lo < 1e-6:
        return pd.Series([50.0] * len(values), index=values.index)
    return (values - lo) / (hi - lo) * 100.0


def add_price_on_soc_axis_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    slot_x: pd.Series,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Strompreis auf der SoC-Achse (0–100), Hover zeigt Cent/kWh."""
    uhrzeit = df["Uhrzeit"]
    price_cent = df["Strompreis (Cent/kWh)"]
    price_scaled = _scale_series_to_0_100(price_cent)
    segments = _trace_segments(len(df), extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        slot_x,
        price_scaled,
        uhrzeit,
        segments,
        name="Preis",
        line_kwargs=dict(color="red", width=2.5, shape="hv"),
        yaxis=yaxis,
        extrapolated_dotted=True,
        custom_hover_values=price_cent,
        hover_template=(
            "Uhrzeit: %{text}<br>Preis: %{customdata:.2f} Cent/kWh"
            "<extra></extra>"
        ),
    )


def add_cumulative_cost_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    slot_x: pd.Series,
    hourly_matched_cost_euro: list[float],
    hourly_optimized_cost_euro: list[float],
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierte Stromkosten: BL Ziel und optimiert."""
    if not hourly_matched_cost_euro or not hourly_optimized_cost_euro:
        return
    length = len(slot_x)
    matched_cum = pd.Series(hourly_matched_cost_euro[:length], dtype=float).cumsum()
    optimized_cum = pd.Series(hourly_optimized_cost_euro[:length], dtype=float).cumsum()
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        slot_x,
        matched_cum,
        uhrzeit,
        segments,
        name="Kosten BL Ziel",
        line_kwargs=dict(color=_COLOR_BASELINE, width=2.5, shape="hv"),
        extrapolated_dotted=True,
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten BL Ziel (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    )
    _add_segmented_hv_line(
        fig,
        slot_x,
        optimized_cum,
        uhrzeit,
        segments,
        name="Kosten optimiert",
        line_kwargs=dict(color=_COLOR_OPTIMIZED, width=2.5, shape="hv"),
        extrapolated_dotted=True,
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten optimiert (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    )


def add_cumulative_consumption_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    slot_x: pd.Series,
    hourly_matched_kwh: list[float],
    hourly_optimized_kwh: list[float],
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierter Gesamtverbrauch (Grundlast + Flex) auf separater Achse."""
    if not hourly_matched_kwh or not hourly_optimized_kwh:
        return
    length = len(slot_x)
    matched_cum = pd.Series(hourly_matched_kwh[:length], dtype=float).cumsum()
    optimized_cum = pd.Series(hourly_optimized_kwh[:length], dtype=float).cumsum()
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        slot_x,
        matched_cum,
        uhrzeit,
        segments,
        name="Verbrauch BL Ziel",
        line_kwargs=dict(color=_COLOR_BASELINE, width=2.5, dash="dash", shape="hv"),
        yaxis=yaxis,
        y_format=".2f",
        base_opacity=1.0,
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Verbrauch BL Ziel (kumuliert): %{y:.2f} kWh"
            "<extra></extra>"
        ),
    )
    _add_segmented_hv_line(
        fig,
        slot_x,
        optimized_cum,
        uhrzeit,
        segments,
        name="Verbrauch optimiert",
        line_kwargs=dict(color=_COLOR_OPTIMIZED, width=2.5, dash="dash", shape="hv"),
        yaxis=yaxis,
        y_format=".2f",
        base_opacity=1.0,
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Verbrauch optimiert (kumuliert): %{y:.2f} kWh"
            "<extra></extra>"
        ),
    )


def _chart_legend() -> dict:
    return dict(
        orientation="h",
        yanchor="top",
        y=-0.22,
        x=0.5,
        xanchor="center",
        font=dict(size=10),
    )


def render_power_soc_chart(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
) -> None:
    """Leistungen (PV, Verbrauch, Batterie, Flex) und SoC-Verläufe."""
    bar_colors = get_bar_colors(df)
    slot_x = _chart_slot_x(len(df))
    extrap_start, extrap_end = _extrapolation_bounds(df)
    fig = go.Figure()

    add_power_traces(fig, df, bar_colors, slot_x, extrap_start, extrap_end)
    add_optimized_soc_trace(fig, df, slot_x, extrap_start=extrap_start, extrap_end=extrap_end)
    add_baseline_soc_traces(
        fig,
        baseline_df,
        matched_baseline_df,
        extrap_start=extrap_start,
        extrap_end=extrap_end,
    )
    add_price_on_soc_axis_trace(
        fig, df, slot_x, extrap_start=extrap_start, extrap_end=extrap_end
    )

    fig.update_layout(
        title="24-Stunden-Zeithorizont (Leistung, SoC & Preis)",
        xaxis=_chart_xaxis_config(df["Uhrzeit"]),
        barmode="overlay",
        yaxis=dict(title="Leistung (kW)", side="left"),
        yaxis2=dict(
            title="SoC (%) / Preis (skaliert 0–100)",
            side="right",
            overlaying="y",
            showgrid=False,
            range=[0, 100],
        ),
        legend=_chart_legend(),
        margin=dict(l=40, r=40, t=50, b=110),
    )
    extrap_caption = _extrapolation_caption(df)
    if extrap_caption:
        st.caption(extrap_caption)
    else:
        st.caption(
            "Preis rot auf der rechten Achse: relativ auf 0–100 skaliert "
            "(Hover zeigt Cent/kWh)."
        )
    st.plotly_chart(fig, width="stretch")


def render_cumulative_cost_chart(
    df: pd.DataFrame,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
) -> None:
    """Kumulierte Stromkosten und Verbrauch BL Ziel vs. optimiert."""
    slot_x = _chart_slot_x(len(df))
    extrap_start, extrap_end = _extrapolation_bounds(df)
    fig = go.Figure()
    has_costs = bool(hourly_matched_baseline_cost_euro and hourly_optimized_cost_euro)
    has_consumption = bool(
        hourly_matched_baseline_consumption_kwh and hourly_optimized_consumption_kwh
    )

    if has_costs:
        add_cumulative_cost_traces(
            fig,
            df["Uhrzeit"],
            slot_x,
            hourly_matched_baseline_cost_euro or [],
            hourly_optimized_cost_euro or [],
            extrap_start=extrap_start,
            extrap_end=extrap_end,
        )
    if has_consumption:
        add_cumulative_consumption_traces(
            fig,
            df["Uhrzeit"],
            slot_x,
            hourly_matched_baseline_consumption_kwh or [],
            hourly_optimized_consumption_kwh or [],
            extrap_start=extrap_start,
            extrap_end=extrap_end,
        )

    layout = dict(
        title="Kumulierte Kosten & Verbrauch",
        xaxis=_chart_xaxis_config(df["Uhrzeit"]),
        yaxis=dict(title="Kosten (€, kumuliert)"),
        legend=_chart_legend(),
        margin=dict(l=40, r=40, t=50, b=110),
    )
    if has_consumption:
        layout["yaxis2"] = dict(
            title="Verbrauch (kWh, kumuliert)",
            side="right",
            overlaying="y",
            showgrid=False,
        )
    fig.update_layout(**layout)
    extrap_caption = _extrapolation_caption(df)
    if has_costs or has_consumption:
        if extrap_caption:
            st.caption(extrap_caption)
        else:
            st.caption(
                "Durchgezogene Linien: Kosten. Gestrichelte Linien (rechte Achse): "
                "Gesamtverbrauch Grundlast + Flex. BL Ziel: historisches Profil skaliert."
            )
    st.plotly_chart(fig, width="stretch")


def render_price_savings_chart(
    df: pd.DataFrame,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
) -> None:
    """Alias für kumulierte Kosten- und Verbrauchslinien."""
    render_cumulative_cost_chart(
        df,
        hourly_matched_baseline_cost_euro,
        hourly_optimized_cost_euro,
        hourly_matched_baseline_consumption_kwh,
        hourly_optimized_consumption_kwh,
    )


def render_optimization_chart(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
    hourly_savings_euro: list[float] | None = None,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
) -> None:
    """Zeichnet Leistung/SoC/Preis und kumulierte Kosten/Verbrauch in zwei Charts."""
    render_power_soc_chart(df, baseline_df, matched_baseline_df)
    render_price_savings_chart(
        df,
        hourly_matched_baseline_cost_euro,
        hourly_optimized_cost_euro,
        hourly_matched_baseline_consumption_kwh,
        hourly_optimized_consumption_kwh,
    )

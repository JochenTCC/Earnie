"""Plotly-Charts für Optimierungsdarstellung (sunrise→sunrise Live, 24h Historie)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from data.planning_window import (
    UiChartWindow,
    normalize_hour_slot,
)
from optimizer.targets import consumer_pv_follow_column_name, consumer_immediate_charge_column_name
from optimizer import battery as bat
from optimizer.deviation_eval import DeviationEvent
from runtime_store.history_timeline import SLOT_MISSING
from ui.help_hint import render_title_with_help

_CONSUMER_BAR_OPACITY = 0.65
_CONSUMER_PV_FOLLOW_PATTERN = "/"
_CONSUMER_IMMEDIATE_CHARGE_PATTERN = "+"
_COLOR_BASELINE = "#7f8c8d"
_COLOR_OPTIMIZED = "#e67e22"
_COLOR_ACTUAL = "#3498db"
_COLOR_SAVINGS = "#27ae60"
_COLOR_GRID_POWER = "#7f8c8d"
_PV_LINE_COLOR = "#f1c40f"
_PV_FILL_COLOR = "rgba(241, 196, 15, 0.15)"
_ZONE_HISTORY_COLOR = "rgba(128, 128, 128, 0.18)"
_ZONE_FORECAST_COLOR = "rgba(76, 175, 80, 0.15)"
_MISSING_SLOT_FILL = "rgba(255, 224, 178, 0.55)"
_MARKER_NOW_COLOR = "#3498db"
_MARKER_SUNRISE_COLOR = "#f39c12"
_DEVIATION_MARKER_SIZE = 11
_DEVIATION_Y_STACK_FACTOR = 0.06
_CONSUMER_PALETTE_START = (194, 24, 91)
_CONSUMER_PALETTE_END = (0, 188, 212)


def _safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return number


def _optional_float(value) -> float | None:
    """Wie _safe_float, aber None/NaN bleiben None (kein Default)."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _line_plot_float(value) -> float:
    """Plotly-Linienwert: fehlende Messwerte als NaN (Lücken)."""
    parsed = _optional_float(value)
    return float("nan") if parsed is None else parsed


def _safe_int_flag(value) -> int:
    return int(_safe_float(value, 0.0))


@dataclass(frozen=True)
class ChartSunMarkers:
    now_x: datetime | None
    sa0_x: datetime | None
    sa1_x: datetime | None
    sa2_x: datetime | None


@dataclass(frozen=True)
class ChartSlotAxis:
    """
    Zeitbasierte Plotly-X-Achse (type=date).

    Jede Chart-Zeile hat ``slot_datetime`` = Slotbeginn (volle Stunde oder Viertelstunde).
    Plotly erhält echte Zeitstempel — kein Index 0..n-1 mehr.

    **Warum früher Index + Verschiebungen?**
    Historisch lief die X-Achse als ``linear`` mit Tick-Labels aus ``Uhrzeit``, während
    Traces intern mit Slot-Indizes 0..n-1 rechneten. Ein Slot i wurde als Mitte bei x=i
    dargestellt (sichtbarer Bereich [-0.5, n-0.5]). Daraus folgten die Korrekturen:

    | Trace / Element | Index-Offset | Bedeutung (jetzt: Anteil × ``step`` ab Slotbeginn) |
    |-----------------|--------------|-----------------------------------------------------|
    | HV-Linien (Verbrauch, Preis, kum. Kosten) | −0.5 | Wert gilt ab Slotbeginn (Treppenfunktion) |
    | Netz-Linie | 0 (Mitte) | Stundenmittelwert zentriert im Slot |
    | Batterie-Balken | +0.05 | Leichte Verschiebung nach rechts (optische Trennung von Linien) |
    | Flex-Balken nebeneinander | ± ``bar_width``/2 | Mehrere Verbraucher im selben Slot nebeneinander |
    | ``add_vrect`` / Jetzt-Linie | Index ± 0.5 | Zonen- und Marker-Grenzen zwischen Sloträndern |

    Konstanten unten (``_LINE_ANCHOR_*``, ``_BAR_CENTER_NUDGE``) sind die zeitliche
    Entsprechung dieser Index-Brüche.
    """

    starts: pd.Series
    step: timedelta

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        *,
        slot_datetimes: tuple[datetime, ...] | None = None,
    ) -> ChartSlotAxis:
        if "slot_datetime" in df.columns:
            starts = pd.to_datetime(df["slot_datetime"])
        elif slot_datetimes is not None:
            if len(slot_datetimes) != len(df):
                raise ValueError(
                    f"slot_datetimes ({len(slot_datetimes)} Einträge) "
                    f"passt nicht zur DataFrame-Länge ({len(df)})."
                )
            starts = pd.Series(list(slot_datetimes))
        else:
            raise ValueError(
                "Chart-Daten benötigen Spalte 'slot_datetime' "
                "oder explizites slot_datetimes-Tuple."
            )
        return cls(starts=starts, step=cls._infer_step(starts))

    @staticmethod
    def _infer_step(starts: pd.Series) -> timedelta:
        if len(starts) < 2:
            return timedelta(hours=1)
        diffs = starts.diff().dropna()
        positive = diffs[diffs > timedelta(0)]
        if positive.empty:
            return timedelta(hours=1)
        return timedelta(seconds=float(positive.dt.total_seconds().median()))

    def slot_duration(self, index: int) -> timedelta:
        """Dauer eines Slots (15 min oder 1 h — aus Nachbar-Slots abgeleitet)."""
        if index + 1 < len(self.starts):
            diff = self.starts.iloc[index + 1] - self.starts.iloc[index]
            if diff > timedelta(0):
                return diff
        if index > 0:
            diff = self.starts.iloc[index] - self.starts.iloc[index - 1]
            if diff > timedelta(0):
                return diff
        return self.step

    def _offset_for(self, index: int, fraction: float) -> pd.Timedelta:
        seconds = self.slot_duration(index).total_seconds() * fraction
        return pd.to_timedelta(seconds, unit="s")

    def at(self, index_slice, fraction: float) -> pd.Series:
        """Zeitpunkt = Slotbeginn + ``fraction`` × Slotdauer (0=Beginn, 0.5=Mitte, 1=Ende)."""
        if isinstance(index_slice, int):
            return pd.Series([self.starts.iloc[index_slice] + self._offset_for(index_slice, fraction)])
        indices = list(range(len(self.starts)))
        times = [
            self.starts.iloc[i] + self._offset_for(i, fraction)
            for i in indices
        ]
        return pd.Series(times)

    def legacy_index_time(self, index: float) -> datetime:
        """
        Altes Index-X (Slot k zentriert bei x=k, Bereich ±0.5) → Zeitstempel.

        Index −0.5 = ``starts[0]``; Index 0 = Slotmitte; Index k−0.5 = ``starts[k]``.
        Nutzt die echte Slot-Dauer je Zeile (gemischte 15-min/1-h-Auflösung).
        """
        if len(self.starts) == 0:
            raise ValueError("ChartSlotAxis.starts darf nicht leer sein.")
        slot_idx = int(math.floor(index + 0.5))
        if slot_idx < 0:
            return self.starts.iloc[0].to_pydatetime()
        if slot_idx >= len(self.starts):
            last = len(self.starts) - 1
            within = index - (last - 0.5)
            duration = self.slot_duration(last)
            return (self.starts.iloc[last] + duration * within).to_pydatetime()
        within = index - (slot_idx - 0.5)
        duration = self.slot_duration(slot_idx)
        return (self.starts.iloc[slot_idx] + duration * within).to_pydatetime()

    def bar_width_ms(self, width_fraction: float, index: int | None = None) -> float:
        """Plotly ``go.Bar``-Breite auf Datumsachse (Millisekunden)."""
        duration = self.slot_duration(index) if index is not None else self.step
        return duration.total_seconds() * 1000.0 * width_fraction

    def x_range(self, *, range_start: datetime | None = None) -> list[datetime]:
        """Sichtbarer X-Bereich; ``range_start`` = SA₀/SA₁-Fensteranfang (Spec §4)."""
        left = self.legacy_index_time(-0.5)
        if range_start is not None:
            anchor = pd.Timestamp(range_start)
            if anchor > left:
                left = anchor.to_pydatetime()
        return [
            left,
            self.legacy_index_time(len(self.starts) - 0.5),
        ]

    def slice(self, start: int, end: int) -> ChartSlotAxis:
        """Teilfenster für Segment-Traces (behält ``step`` bei)."""
        return ChartSlotAxis(
            starts=self.starts.iloc[start:end].reset_index(drop=True),
            step=self.step,
        )


# Anteile der Slot-Dauer (Entsprechung zum früheren Index-Modell, siehe ChartSlotAxis).
_LINE_ANCHOR_SLOT_START = 0.0
_LINE_ANCHOR_SLOT_CENTER = 0.5
_BAR_CENTER_NUDGE = 0.05
_BATTERY_BAR_WIDTH_FRACTION = 0.9
_EMPTY_FLOAT_SERIES = pd.Series(dtype=float)


def _empty_chart_time_series() -> pd.Series:
    return pd.Series(dtype=object)


def _chart_time_series(times: list[datetime]) -> pd.Series:
    """Plotly-X in Planungszeitzone — kein ``datetime64[ns, UTC]`` (sonst +2 h Versatz)."""
    if not times:
        return _empty_chart_time_series()
    return pd.Series(times)


def _anchor_fraction_from_legacy_shift(x_shift: float) -> float:
    """Legacy Index-Verschiebung (−0.5 = Slotbeginn, 0 = Mitte) → Anteil ab Slotbeginn."""
    return 0.5 + x_shift


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


def _soc_tail_y_from_row(row: pd.Series) -> float | None:
    """SoC am Ende der Stunde aus geplanter Batterieaktion (Optimierer/Huawei-Logik)."""
    if "Geplante Batterie-Aktion (kW)" not in row.index:
        return None
    soc = _optional_float(row.get("Simulierter SoC (%)"))
    action = _optional_float(row.get("Geplante Batterie-Aktion (kW)"))
    if soc is None or action is None:
        return None
    params = config.get_battery_params()
    new_soc, _ = bat.apply_soc_change(
        soc,
        action,
        params["battery_capacity_kwh"],
        params["efficiency"],
        params["min_soc"],
        params["max_soc"],
    )
    return round(new_soc, 1)


def _sunrise_chart_title(chart: UiChartWindow) -> str:
    return (
        "Sonnenaufgang→Sonnenaufgang "
        f"({chart.start.strftime('%d.%m.%Y %H:%M')} – "
        f"{chart.end.strftime('%d.%m.%Y %H:%M')})"
    )


_CHART2_S2_TITLE = "Kumulierte Kosten & Verbrauch (Sonnenaufgang→Sonnenaufgang)"
_CHART2_S2_HELP = (
    "Grauer Bereich: **Ist bisher** (blau, kumuliert aus Produktiv-Log). "
    "Neutral/Grün: **Prognose** (BL Ziel / optimiert, kumuliert ab Log-Grenze "
    "ohne Anschluss an Ist). Fehlende Log-Slots: orange, Lücken in Ist-Kurven."
)


def _slot_time_in_chart(
    slots: tuple[datetime, ...] | list[datetime],
    moment: datetime,
) -> datetime | None:
    if not slots:
        return None
    target = normalize_hour_slot(moment)
    if target in slots:
        return target
    for slot in slots:
        if slot == moment:
            return slot
    return None


def _slot_index_before(axis: ChartSlotAxis, moment: datetime) -> int:
    """Letzter Index mit Slotbeginn strikt vor ``moment``."""
    for index in range(len(axis.starts) - 1, -1, -1):
        if axis.starts.iloc[index] < moment:
            return index
    return -1


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
    for consumer in config.get_flexible_consumers(optimizer_only=True):
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


def _axis_x_bounds(
    axis: ChartSlotAxis,
    *,
    range_start: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Linker/rechter X-Achsenrand (inkl. ``range_start`` = SA₀/SA₁)."""
    return tuple(axis.x_range(range_start=range_start))  # type: ignore[return-value]


def _zone_slot_left(axis: ChartSlotAxis, index: int) -> datetime:
    return axis.legacy_index_time(index - 0.5)


def _zone_slot_right(axis: ChartSlotAxis, index: int) -> datetime:
    return axis.legacy_index_time(index + 0.5)


def _slot_index_at_or_after(axis: ChartSlotAxis, moment: datetime) -> int | None:
    for index, slot in enumerate(axis.starts):
        if slot >= moment:
            return index
    return None


def _zone_right_edge(axis: ChartSlotAxis, moment: datetime) -> datetime:
    """Rechter Rand des letzten Slots mit Beginn strikt vor ``moment``."""
    history_end_idx = _slot_index_before(axis, moment)
    if history_end_idx < 0:
        return moment
    return _zone_slot_right(axis, history_end_idx)


def _zone_left_edge(axis: ChartSlotAxis, moment: datetime) -> datetime:
    """Linker Rand des ersten Slots mit Beginn >= ``moment``."""
    index = _slot_index_at_or_after(axis, moment)
    if index is None:
        last = len(axis.starts) - 1
        if last < 0:
            raise ValueError("ChartSlotAxis.starts darf nicht leer sein.")
        return _zone_slot_right(axis, last)
    return _zone_slot_left(axis, index)


def _history_zone_x1(
    axis: ChartSlotAxis,
    history_end: datetime,
    *,
    x_right: datetime,
    fill_to_axis_end: bool,
) -> datetime:
    """Rechter Grauzonen-Rand: bis History-Grenze oder voller Achsenrand."""
    if fill_to_axis_end:
        return x_right
    return _zone_right_edge(axis, history_end)


def _forecast_zone_x0(
    axis: ChartSlotAxis,
    forecast_start: datetime,
    x_left: datetime,
) -> datetime:
    """Linker Grünzonen-Rand: ab ``forecast_start``, mindestens ``x_left``."""
    for index, slot in enumerate(axis.starts):
        if slot == forecast_start:
            return max(_zone_slot_left(axis, index), x_left)
    return max(forecast_start, x_left)


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
            fillcolor=_MISSING_SLOT_FILL,
            line_width=0,
            layer="below",
        )


def _add_sun_markers(fig: go.Figure, markers: ChartSunMarkers) -> None:
    if markers.now_x is not None:
        fig.add_vline(
            x=markers.now_x,
            line=dict(color=_MARKER_NOW_COLOR, width=1.5, dash="dot"),
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
            line=dict(color=_MARKER_SUNRISE_COLOR, width=1.5),
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
    for consumer in config.get_flexible_consumers(optimizer_only=True):
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


def _consumer_bar_pattern_shapes(
    segment: pd.DataFrame,
    power_col: str,
    pv_follow_col: str | None,
    immediate_col: str | None = None,
) -> list[str]:
    """Muster je Stunde: Sofort-Laden → Karo (+), pv_follow → Schräg (/), sonst Vollfläche."""
    shapes: list[str] = []
    for _, row in segment.iterrows():
        power = _safe_float(row.get(power_col, 0.0))
        if power <= 1e-6:
            shapes.append("")
            continue
        if immediate_col and immediate_col in segment.columns:
            if _safe_int_flag(row.get(immediate_col, 0)) == 1:
                shapes.append(_CONSUMER_IMMEDIATE_CHARGE_PATTERN)
                continue
        if pv_follow_col and pv_follow_col in segment.columns:
            if _safe_int_flag(row.get(pv_follow_col, 0)) == 1:
                shapes.append(_CONSUMER_PV_FOLLOW_PATTERN)
                continue
        shapes.append("")
    return shapes


def _consumer_bar_marker(
    color: str,
    pattern_shapes: list[str],
    opacity: float,
) -> dict:
    marker: dict = {"color": color, "opacity": opacity}
    if any(shape for shape in pattern_shapes):
        # fgcolor muss sich von bgcolor unterscheiden — sonst ist die Schraffur unsichtbar.
        marker["pattern"] = dict(
            shape=pattern_shapes,
            fgcolor="rgba(255, 255, 255, 0.8)",
            bgcolor=color,
            solidity=0.35,
            fillmode="overlay",
        )
    return marker


def _chart_has_immediate_charge_bars(df: pd.DataFrame) -> bool:
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        imm_col = consumer_immediate_charge_column_name(consumer)
        power_col = f"{consumer['name']} (kW)"
        if imm_col not in df.columns or power_col not in df.columns:
            continue
        mask = (df[imm_col].fillna(0).astype(int) == 1) & (df[power_col].fillna(0.0) > 0)
        if mask.any():
            return True
    return False


def _chart_has_pv_follow_bars(df: pd.DataFrame) -> bool:
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        pv_col = consumer_pv_follow_column_name(consumer)
        power_col = f"{consumer['name']} (kW)"
        if pv_col not in df.columns or power_col not in df.columns:
            continue
        mask = (df[pv_col].fillna(0).astype(int) == 1) & (df[power_col].fillna(0.0) > 0)
        if mask.any():
            return True
    return False


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
        if col in df.columns and df[col].fillna(0.0).sum() > 0:
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


def _slot_indices_for_hour(axis: ChartSlotAxis, hour: datetime) -> list[int]:
    indices: list[int] = []
    for index in range(len(axis.starts)):
        slot = axis.starts.iloc[index].to_pydatetime()
        if normalize_hour_slot(slot) == hour:
            indices.append(index)
    return indices


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
        line=dict(color=_PV_LINE_COLOR, width=2),
        fill="tozeroy",
        fillcolor=_PV_FILL_COLOR,
        yaxis="y",
        **_line_hover(uhrzeit, ".2f"),
    ))


def _chart_xaxis_config(axis: ChartSlotAxis, *, range_start: datetime | None = None) -> dict:
    step_minutes = axis.step.total_seconds() / 60.0
    if step_minutes >= 60:
        dtick = 3600000 * 4
        axis_title = "Uhrzeit (Stunden-Slots)"
    else:
        dtick = 3600000
        axis_title = "Uhrzeit (15-Min-Slots)"
    x0, x1 = axis.x_range(range_start=range_start)
    return dict(
        title=axis_title,
        type="date",
        tickformat="%d.%m. %H:%M",
        dtick=dtick,
        range=[x0, x1],
    )


def _consumer_bar_times(
    axis: ChartSlotAxis,
    index_slice,
    consumer_index: int,
    count: int,
    bar_width_fraction: float,
) -> pd.Series:
    """
    X-Zeitpunkte für Flex-Balken nebeneinander im Slot.

    Früher: Index-Mitte + base_offset + (i − (n−1)/2) × bar_width.
    """
    center_fraction = _LINE_ANCHOR_SLOT_CENTER + _BAR_CENTER_NUDGE
    if count <= 1:
        return axis.at(index_slice, center_fraction)
    shift = (consumer_index - (count - 1) / 2) * bar_width_fraction
    return axis.at(index_slice, center_fraction + shift)


def _battery_bar_times(axis: ChartSlotAxis, index_slice) -> pd.Series:
    """Batterie-Balken: leicht nach rechts versetzt (früher ``bar_offset`` +0.05)."""
    return axis.at(index_slice, _LINE_ANCHOR_SLOT_CENTER + _BAR_CENTER_NUDGE)


def add_power_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    bar_colors: list[str],
    axis: ChartSlotAxis,
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    uhrzeit = df["Uhrzeit"]
    segments = _trace_segments(len(df), extrap_start, extrap_end)
    active_consumers = _active_consumer_bar_columns(df)
    consumer_count = len(active_consumers)
    consumer_bar_width = (
        _BATTERY_BAR_WIDTH_FRACTION / consumer_count
        if consumer_count
        else _BATTERY_BAR_WIDTH_FRACTION
    )
    consumer_colors = _consumer_bar_palette(consumer_count)
    if "PV-Prognose (kW)" in df.columns:
        _add_pv_trace(fig, axis, df["PV-Prognose (kW)"], uhrzeit)

    if "Verbrauch-Prognose (kW)" in df.columns:
        _add_segmented_hv_line(
            fig,
            axis,
            df["Verbrauch-Prognose (kW)"],
            uhrzeit,
            segments,
            name="Verbrauch",
            line_kwargs=dict(color="#3498db", width=2, dash="dash"),
            y_format=".2f",
            base_opacity=1.0,
        )

    if "Netzbezug (kW)" in df.columns:
        _add_segmented_hv_line(
            fig,
            axis,
            df["Netzbezug (kW)"],
            uhrzeit,
            segments,
            name="Netz",
            line_kwargs=dict(color=_COLOR_GRID_POWER, width=2, dash="dash"),
            y_format=".2f",
            base_opacity=1.0,
            anchor_fraction=_LINE_ANCHOR_SLOT_CENTER,
        )

    for seg_index, (start, end, _is_extrapolated) in enumerate(segments):
        if start >= end:
            continue
        fig.add_trace(go.Bar(
            x=_battery_bar_times(axis, slice(start, end)),
            y=df["Geplante Batterie-Aktion (kW)"].iloc[start:end],
            name="Batterie" if seg_index == 0 else "Batterie",
            showlegend=seg_index == 0,
            marker=dict(color=bar_colors[start:end]),
            opacity=0.75,
            width=_bar_widths_ms(axis, start, end, _BATTERY_BAR_WIDTH_FRACTION),
            yaxis="y",
            customdata=uhrzeit.iloc[start:end],
            hovertemplate=(
                "Uhrzeit: %{customdata}<br>%{fullData.name}: "
                "%{y:.2f}<extra></extra>"
            ),
        ))

    for consumer_index, (consumer, col) in enumerate(active_consumers):
        pv_follow_col = consumer_pv_follow_column_name(consumer)
        if pv_follow_col not in df.columns:
            pv_follow_col = None
        immediate_col = consumer_immediate_charge_column_name(consumer)
        if immediate_col not in df.columns:
            immediate_col = None
        for seg_index, (start, end, _is_extrapolated) in enumerate(segments):
            if start >= end:
                continue
            segment = df.iloc[start:end]
            pattern_shapes = _consumer_bar_pattern_shapes(
                segment, col, pv_follow_col, immediate_col
            )
            hover_pv = (
                segment[pv_follow_col].fillna(0).astype(int).tolist()
                if pv_follow_col is not None
                else [0] * len(segment)
            )
            hover_imm = (
                segment[immediate_col].fillna(0).astype(int).tolist()
                if immediate_col is not None
                else [0] * len(segment)
            )
            fig.add_trace(go.Bar(
                x=_consumer_bar_times(
                    axis,
                    slice(start, end),
                    consumer_index,
                    consumer_count,
                    consumer_bar_width,
                ),
                y=segment[col],
                name=consumer["name"] if seg_index == 0 else consumer["name"],
                showlegend=seg_index == 0,
                marker=_consumer_bar_marker(
                    consumer_colors[consumer_index],
                    pattern_shapes,
                    _CONSUMER_BAR_OPACITY,
                ),
                width=_bar_widths_ms(axis, start, end, consumer_bar_width),
                yaxis="y",
                customdata=list(zip(segment["Uhrzeit"], hover_pv, hover_imm)),
                hovertemplate=(
                    "Uhrzeit: %{customdata[0]}<br>%{fullData.name}: "
                    "%{y:.2f} kW<br>pv_follow: %{customdata[1]}<br>"
                    "sofort_laden: %{customdata[2]}"
                    "<extra></extra>"
                ),
            ))


def add_optimized_soc_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
    history_slot_count: int | None = None,
) -> None:
    uhrzeit = df["Uhrzeit"]
    length = len(df)
    soc = df["Simulierter SoC (%)"]
    tail_y = _soc_tail_y_from_row(df.iloc[-1]) if not df.empty else None

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
            soc_x, soc_y = _segment_connected_line_xy(
                axis, soc, abs_start, abs_end, tail_y=seg_tail,
                step_line=False,
            )
            if soc_x.empty:
                continue
            show_legend = part_start == 0 and index == 0
            fig.add_trace(go.Scatter(
                x=soc_x,
                y=soc_y,
                name="SoC",
                showlegend=show_legend,
                mode="lines",
                line=dict(color=_COLOR_OPTIMIZED, width=2.5),
                opacity=1.0,
                yaxis=yaxis,
                connectgaps=False,
                customdata=_segment_hover_labels(
                    uhrzeit,
                    abs_start,
                    abs_end,
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
    matched_baseline_df: pd.DataFrame | None,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    if matched_baseline_df is None or matched_baseline_df.empty:
        return
    matched_axis = ChartSlotAxis.from_dataframe(matched_baseline_df)
    matched_segments = _trace_segments(len(matched_baseline_df), extrap_start, extrap_end)
    for index, (start, end, _is_extrapolated) in enumerate(matched_segments):
        if start >= end:
            continue
        seg_tail = None
        if end == len(matched_axis.starts):
            seg_tail = _soc_tail_y_from_row(matched_baseline_df.iloc[-1])
        matched_x, matched_y = _segment_connected_line_xy(
            matched_axis,
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
            line=dict(color=_COLOR_OPTIMIZED, width=2.5, dash="dot"),
            opacity=1.0,
            yaxis=yaxis,
            connectgaps=False,
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


def add_price_on_soc_axis_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    axis: ChartSlotAxis,
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Strompreis auf der SoC-Achse — stündliche Stufen, an Slot-Rändern ausgerichtet."""
    segments = _trace_segments(len(df), extrap_start, extrap_end)
    for index, (start, end, _is_extrapolated) in enumerate(segments):
        if start >= end:
            continue
        segment_df = df.iloc[start:end]
        segment_axis = axis.slice(start, end)
        line_x, line_y = _hourly_price_hv_xy(segment_axis, segment_df)
        if line_x.empty:
            continue
        hour_prices = _hour_prices_from_df(segment_df)
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
            name="Preis" if index == 0 else "Preis",
            showlegend=index == 0,
            mode="lines",
            line=dict(color="red", width=2.5, shape="hv"),
            opacity=1.0,
            yaxis=yaxis,
            text=_hourly_price_hover_labels(segment_df, line_x),
            customdata=customdata,
            hovertemplate=(
                "Uhrzeit: %{text}<br>Preis: %{customdata:.2f} Cent/kWh"
                "<extra></extra>"
            ),
        ))


def _hourly_cumsum_for_chart(
    hourly_values: list[float],
    slot_count: int,
) -> pd.Series | None:
    """Kumulierte Stundenreihe mit Länge slot_count (0-Padding bei kürzerer Liste)."""
    if not hourly_values or slot_count <= 0:
        return None
    padded = list(hourly_values[:slot_count])
    if len(padded) < slot_count:
        padded.extend([0.0] * (slot_count - len(padded)))
    return pd.Series(padded, dtype=float).cumsum()


def _increment_is_finite(value: float | None) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return not math.isnan(number)


def _region_cumulative_series(
    increments: list[float],
    length: int,
    region_start: int,
    region_end: int,
) -> pd.Series | None:
    """Kumulierte Slot-Reihe nur in [region_start, region_end); fehlende Slots = NaN."""
    if region_start >= region_end or region_end > length:
        return None
    values = [float("nan")] * length
    total = 0.0
    for index in range(region_start, region_end):
        increment = increments[index] if index < len(increments) else float("nan")
        if not _increment_is_finite(increment):
            values[index] = float("nan")
            continue
        total += float(increment)
        values[index] = total
    if not any(_increment_is_finite(values[i]) for i in range(region_start, region_end)):
        return None
    return pd.Series(values, dtype=float)


def _sum_slot_increments(
    increments: list[float] | None,
    region_start: int,
    region_end: int,
) -> float:
    if not increments:
        return 0.0
    total = 0.0
    for index in range(region_start, min(region_end, len(increments))):
        increment = increments[index]
        if _increment_is_finite(increment):
            total += float(increment)
    return total


def _add_region_cumulative_hv_trace(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    increments: list[float],
    region_start: int,
    region_end: int,
    *,
    name: str,
    line_kwargs: dict,
    yaxis: str = "y",
    y_format: str = ".3f",
    segment_hover_template: str,
    bridge_left: bool = True,
) -> None:
    length = len(axis.starts)
    cumulative = _region_cumulative_series(
        increments, length, region_start, region_end
    )
    if cumulative is None:
        return
    segments = [(region_start, region_end, False)]
    _add_segmented_hv_line(
        fig,
        axis,
        cumulative,
        uhrzeit,
        segments,
        name=name,
        line_kwargs=line_kwargs,
        yaxis=yaxis,
        y_format=y_format,
        segment_hover_template=segment_hover_template,
        bridge_left=bridge_left,
    )


def add_cumulative_s2_split_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    *,
    history_slot_count: int,
    slot_actual_cost_euro: list[float],
    slot_actual_consumption_kwh: list[float],
    hourly_matched_baseline_cost_euro: list[float],
    hourly_optimized_cost_euro: list[float],
    hourly_matched_baseline_consumption_kwh: list[float],
    hourly_optimized_consumption_kwh: list[float],
) -> None:
    """Chart 2 S-2 P3a: Ist (Log) und Prognose (MILP) ohne Brücke an der Grenze."""
    length = len(axis.starts)
    split = history_slot_count
    if split <= 0 or split > length:
        return

    if split < length:
        _add_region_cumulative_hv_trace(
            fig,
            uhrzeit,
            axis,
            hourly_matched_baseline_cost_euro,
            split,
            length,
            name="Kosten BL Ziel (Prognose)",
            line_kwargs=dict(color=_COLOR_BASELINE, width=2.5, shape="hv"),
            segment_hover_template=(
                "Uhrzeit: %{customdata}<br>Kosten BL Ziel (Prognose, kumuliert): "
                "%{y:.3f} €<extra></extra>"
            ),
            bridge_left=False,
        )
        _add_region_cumulative_hv_trace(
            fig,
            uhrzeit,
            axis,
            hourly_optimized_cost_euro,
            split,
            length,
            name="Kosten optimiert (Prognose)",
            line_kwargs=dict(color=_COLOR_OPTIMIZED, width=2.5, shape="hv"),
            segment_hover_template=(
                "Uhrzeit: %{customdata}<br>Kosten optimiert (Prognose, kumuliert): "
                "%{y:.3f} €<extra></extra>"
            ),
            bridge_left=False,
        )
        _add_region_cumulative_hv_trace(
            fig,
            uhrzeit,
            axis,
            hourly_matched_baseline_consumption_kwh,
            split,
            length,
            name="Verbrauch BL Ziel (Prognose)",
            line_kwargs=dict(color=_COLOR_BASELINE, width=2.5, dash="dash", shape="hv"),
            yaxis="y2",
            y_format=".2f",
            segment_hover_template=(
                "Uhrzeit: %{customdata}<br>Verbrauch BL Ziel (Prognose, kumuliert): "
                "%{y:.2f} kWh<extra></extra>"
            ),
            bridge_left=False,
        )
        _add_region_cumulative_hv_trace(
            fig,
            uhrzeit,
            axis,
            hourly_optimized_consumption_kwh,
            split,
            length,
            name="Verbrauch optimiert (Prognose)",
            line_kwargs=dict(color=_COLOR_OPTIMIZED, width=2.5, dash="dash", shape="hv"),
            yaxis="y2",
            y_format=".2f",
            segment_hover_template=(
                "Uhrzeit: %{customdata}<br>Verbrauch optimiert (Prognose, kumuliert): "
                "%{y:.2f} kWh<extra></extra>"
            ),
            bridge_left=False,
        )

    _add_region_cumulative_hv_trace(
        fig,
        uhrzeit,
        axis,
        slot_actual_cost_euro,
        0,
        split,
        name="Kosten (Ist bisher)",
        line_kwargs=dict(color=_COLOR_ACTUAL, width=2.5, shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten (Ist bisher, kumuliert): "
            "%{y:.3f} €<extra></extra>"
        ),
    )
    _add_region_cumulative_hv_trace(
        fig,
        uhrzeit,
        axis,
        slot_actual_consumption_kwh,
        0,
        split,
        name="Verbrauch (Ist bisher)",
        line_kwargs=dict(color=_COLOR_ACTUAL, width=2.5, dash="dash", shape="hv"),
        yaxis="y2",
        y_format=".2f",
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Verbrauch (Ist bisher, kumuliert): "
            "%{y:.2f} kWh<extra></extra>"
        ),
    )


def add_cumulative_cost_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    hourly_matched_cost_euro: list[float],
    hourly_optimized_cost_euro: list[float],
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierte Stromkosten: BL Ziel und optimiert."""
    length = len(axis.starts)
    matched_cum = _hourly_cumsum_for_chart(hourly_matched_cost_euro, length)
    optimized_cum = _hourly_cumsum_for_chart(hourly_optimized_cost_euro, length)
    if matched_cum is None or optimized_cum is None:
        return
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        axis,
        matched_cum,
        uhrzeit,
        segments,
        name="Kosten BL Ziel",
        line_kwargs=dict(color=_COLOR_BASELINE, width=2.5, shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten BL Ziel (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    )
    _add_segmented_hv_line(
        fig,
        axis,
        optimized_cum,
        uhrzeit,
        segments,
        name="Kosten optimiert",
        line_kwargs=dict(color=_COLOR_OPTIMIZED, width=2.5, shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten optimiert (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    )


def add_cumulative_consumption_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    hourly_matched_kwh: list[float],
    hourly_optimized_kwh: list[float],
    yaxis: str = "y2",
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierter Gesamtverbrauch (Grundlast + Flex) auf separater Achse."""
    length = len(axis.starts)
    matched_cum = _hourly_cumsum_for_chart(hourly_matched_kwh, length)
    optimized_cum = _hourly_cumsum_for_chart(hourly_optimized_kwh, length)
    if matched_cum is None or optimized_cum is None:
        return
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        axis,
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
        axis,
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


def _hv_line_endpoint_time(axis: ChartSlotAxis) -> datetime:
    """Zeitpunkt am Ende des letzten Slots (HV-Linien, früher Index n−0.5)."""
    return axis.legacy_index_time(len(axis.starts) - 0.5)


_COST_SUMMARY_FONT_SIZE = 14
_COST_SUMMARY_LINE_SHIFT = 20
_COST_SUMMARY_Y_TOP = 1.0


def _cost_summary_annotations(
    matched_baseline_cost_euro: float,
    optimized_cost_euro: float,
) -> list[dict]:
    """Plotly-Annotationen für die Gesamtkosten (oben links im Chart)."""
    savings_euro = optimized_cost_euro - matched_baseline_cost_euro
    if savings_euro < 0:
        savings_color = "#27ae60"
    elif savings_euro > 0:
        savings_color = "#e74c3c"
    else:
        savings_color = _COLOR_BASELINE

    summary_font = dict(size=_COST_SUMMARY_FONT_SIZE)
    base = dict(
        xref="paper",
        yref="y domain",
        x=0.01,
        y=_COST_SUMMARY_Y_TOP,
        showarrow=False,
        xanchor="left",
        yanchor="top",
        font=summary_font,
    )
    return [
        {
            **base,
            "text": f"BL Ziel: {matched_baseline_cost_euro:.2f} €",
            "font": {**summary_font, "color": _COLOR_BASELINE},
        },
        {
            **base,
            "text": f"Optimiert: {optimized_cost_euro:.2f} €",
            "yshift": -_COST_SUMMARY_LINE_SHIFT,
            "font": {**summary_font, "color": _COLOR_OPTIMIZED},
        },
        {
            **base,
            "text": f"Ersparnis: {savings_euro:+.2f} €",
            "yshift": -2 * _COST_SUMMARY_LINE_SHIFT,
            "font": {**summary_font, "color": savings_color},
        },
    ]


def _add_cost_summary_annotations(
    fig: go.Figure,
    matched_baseline_cost_euro: float,
    optimized_cost_euro: float,
) -> None:
    for annotation in _cost_summary_annotations(
        matched_baseline_cost_euro,
        optimized_cost_euro,
    ):
        fig.add_annotation(**annotation)


def _chart_range_start(chart_window: UiChartWindow | None) -> datetime | None:
    """Linker X-Rand = Fensteranfang SA₀ bzw. SA₁ (Spec ui-sunset2sunset §4)."""
    if chart_window is None:
        return None
    return chart_window.start


def build_power_soc_chart_figure(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
    *,
    chart_title: str | None = None,
    show_baseline_soc: bool = True,
    chart_window: UiChartWindow | None = None,
    chart_zones=None,
    sun_markers: ChartSunMarkers | None = None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    chart_header_label: str | None = None,
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...] | None = None,
) -> go.Figure:
    """Baut Chart 1 (Leistung, SoC, Preis) ohne Streamlit-Rendering."""
    plot_df = _mask_missing_log_slots(df, slot_qualities)
    bar_colors = get_bar_colors(plot_df)
    axis = ChartSlotAxis.from_dataframe(plot_df)
    extrap_start, extrap_end = _extrapolation_bounds(plot_df)
    range_start = _chart_range_start(chart_window)
    fig = go.Figure()

    if chart_zones is not None:
        _add_zone_backgrounds(fig, chart_zones, axis, range_start=range_start)
    _add_missing_slot_backgrounds(fig, axis, slot_qualities)

    add_power_traces(fig, plot_df, bar_colors, axis, extrap_start, extrap_end)
    add_optimized_soc_trace(
        fig, plot_df, axis, extrap_start=extrap_start, extrap_end=extrap_end,
        history_slot_count=history_slot_count,
    )
    if show_baseline_soc:
        add_baseline_soc_traces(
            fig,
            matched_baseline_df,
            extrap_start=extrap_start,
            extrap_end=extrap_end,
        )
    add_price_on_soc_axis_trace(
        fig, plot_df, axis, extrap_start=extrap_start, extrap_end=extrap_end
    )

    if sun_markers is not None:
        _add_sun_markers(fig, sun_markers)
    _add_deviation_markers(fig, axis, plot_df, slot_deviation_events)

    default_title = (
        _sunrise_chart_title(chart_window)
        if chart_window is not None
        else "24-Stunden-Zeithorizont (Leistung, SoC & Preis)"
    )
    plotly_title = None if chart_header_label else chart_title or default_title
    layout_title = plotly_title if plotly_title else ""
    top_margin = 20 if chart_header_label else 50
    fig.update_layout(
        title=layout_title,
        xaxis=_chart_xaxis_config(axis, range_start=range_start),
        barmode="overlay",
        yaxis=dict(title="Leistung (kW)", side="left"),
        yaxis2=dict(
            title="SoC (%) / Preis (Cent/kWh)",
            side="right",
            overlaying="y",
            showgrid=False,
            range=[-5, 105],
        ),
        legend=_chart_legend(),
        margin=dict(l=40, r=40, t=top_margin, b=110),
    )
    return fig


def render_power_soc_chart(
    df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    matched_baseline_df: pd.DataFrame | None = None,
    *,
    chart_title: str | None = None,
    show_baseline_soc: bool = True,
    chart_key: str | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    sun_markers: ChartSunMarkers | None = None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    chart_header_label: str | None = None,
    chart_header_help: str | None = None,
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...] | None = None,
) -> None:
    """Leistungen (PV, Verbrauch, Batterie, Flex) und SoC-Verläufe."""
    if chart_header_label and chart_header_help:
        render_title_with_help(
            chart_header_label,
            chart_header_help,
            key="s2_zone_help",
        )
    fig = build_power_soc_chart_figure(
        df,
        baseline_df,
        matched_baseline_df,
        chart_title=chart_title,
        show_baseline_soc=show_baseline_soc,
        chart_window=chart_window,
        chart_zones=chart_zones,
        sun_markers=sun_markers,
        slot_qualities=slot_qualities,
        history_slot_count=history_slot_count,
        chart_header_label=chart_header_label,
        slot_deviation_events=slot_deviation_events,
    )
    plotly_kwargs: dict = {"width": "stretch"}
    if chart_key:
        plotly_kwargs["key"] = chart_key
    st.plotly_chart(fig, **plotly_kwargs)


def add_cumulative_actual_traces(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    slot_costs_euro: list[float],
    slot_consumption_kwh: list[float],
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierte Ist-Kosten und Ist-Verbrauch (Produktiv-Historie)."""
    length = len(axis.starts)
    cost_cum = pd.Series(slot_costs_euro[:length], dtype=float).cumsum()
    kwh_cum = pd.Series(slot_consumption_kwh[:length], dtype=float).cumsum()
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        axis,
        cost_cum,
        uhrzeit,
        segments,
        name="Kosten (Ist)",
        line_kwargs=dict(color=_COLOR_OPTIMIZED, width=2.5, shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Kosten (Ist, kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
    )
    _add_segmented_hv_line(
        fig,
        axis,
        kwh_cum,
        uhrzeit,
        segments,
        name="Verbrauch (Ist)",
        line_kwargs=dict(color=_COLOR_OPTIMIZED, width=2.5, dash="dash", shape="hv"),
        yaxis="y2",
        y_format=".2f",
        base_opacity=1.0,
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Verbrauch (Ist, kumuliert): %{y:.2f} kWh"
            "<extra></extra>"
        ),
    )


def render_cumulative_cost_chart(
    df: pd.DataFrame,
    hourly_matched_baseline_cost_euro: list[float] | None = None,
    hourly_optimized_cost_euro: list[float] | None = None,
    hourly_matched_baseline_consumption_kwh: list[float] | None = None,
    hourly_optimized_consumption_kwh: list[float] | None = None,
    *,
    matched_baseline_cost_euro: float | None = None,
    optimized_cost_euro: float | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    slot_actual_cost_euro: list[float] | None = None,
    slot_actual_consumption_kwh: list[float] | None = None,
) -> None:
    """Kumulierte Stromkosten und Verbrauch BL Ziel vs. optimiert."""
    axis = ChartSlotAxis.from_dataframe(df)
    extrap_start, extrap_end = _extrapolation_bounds(df)
    range_start = _chart_range_start(chart_window)
    fig = go.Figure()
    if chart_zones is not None:
        _add_zone_backgrounds(fig, chart_zones, axis, range_start=range_start)
    _add_missing_slot_backgrounds(fig, axis, slot_qualities)
    length = len(axis.starts)
    split_mode = (
        history_slot_count is not None
        and history_slot_count > 0
        and slot_actual_cost_euro is not None
        and slot_actual_consumption_kwh is not None
    )
    has_costs = bool(hourly_matched_baseline_cost_euro and hourly_optimized_cost_euro)
    has_consumption = bool(
        hourly_matched_baseline_consumption_kwh and hourly_optimized_consumption_kwh
    )
    if split_mode:
        add_cumulative_s2_split_traces(
            fig,
            df["Uhrzeit"],
            axis,
            history_slot_count=history_slot_count,
            slot_actual_cost_euro=slot_actual_cost_euro or [],
            slot_actual_consumption_kwh=slot_actual_consumption_kwh or [],
            hourly_matched_baseline_cost_euro=hourly_matched_baseline_cost_euro or [],
            hourly_optimized_cost_euro=hourly_optimized_cost_euro or [],
            hourly_matched_baseline_consumption_kwh=(
                hourly_matched_baseline_consumption_kwh or []
            ),
            hourly_optimized_consumption_kwh=hourly_optimized_consumption_kwh or [],
        )
        has_costs = has_costs or history_slot_count > 0
        has_consumption = has_consumption or history_slot_count > 0
    elif has_costs:
        add_cumulative_cost_traces(
            fig,
            df["Uhrzeit"],
            axis,
            hourly_matched_baseline_cost_euro or [],
            hourly_optimized_cost_euro or [],
            extrap_start=extrap_start,
            extrap_end=extrap_end,
        )
    if not split_mode and has_consumption:
        add_cumulative_consumption_traces(
            fig,
            df["Uhrzeit"],
            axis,
            hourly_matched_baseline_consumption_kwh or [],
            hourly_optimized_consumption_kwh or [],
            extrap_start=extrap_start,
            extrap_end=extrap_end,
        )

    show_cost_summary = (
        has_costs
        and matched_baseline_cost_euro is not None
        and optimized_cost_euro is not None
    )
    if show_cost_summary:
        _add_cost_summary_annotations(
            fig,
            matched_baseline_cost_euro,
            optimized_cost_euro,
        )

    if split_mode:
        render_title_with_help(_CHART2_S2_TITLE, _CHART2_S2_HELP, key="chart2_s2_help")

    default_title = (
        _CHART2_S2_TITLE
        if chart_window is not None
        else "Kumulierte Kosten & Verbrauch"
    )
    plotly_title = "" if split_mode else default_title
    top_margin = 20 if split_mode else 50
    layout = dict(
        title=plotly_title,
        xaxis=_chart_xaxis_config(axis, range_start=range_start),
        yaxis=dict(title="Kosten (€, kumuliert)"),
        legend=_chart_legend(),
        margin=dict(l=40, r=40, t=top_margin, b=110),
    )
    if has_consumption:
        layout["yaxis2"] = dict(
            title="Verbrauch (kWh, kumuliert)",
            side="right",
            overlaying="y",
            showgrid=False,
        )
    fig.update_layout(**layout)
    if (has_costs or has_consumption) and not split_mode:
        extrap_start, _ = _extrapolation_bounds(df)
        if extrap_start is None:
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
    *,
    matched_baseline_cost_euro: float | None = None,
    optimized_cost_euro: float | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    slot_actual_cost_euro: list[float] | None = None,
    slot_actual_consumption_kwh: list[float] | None = None,
) -> None:
    """Alias für kumulierte Kosten- und Verbrauchslinien."""
    render_cumulative_cost_chart(
        df,
        hourly_matched_baseline_cost_euro,
        hourly_optimized_cost_euro,
        hourly_matched_baseline_consumption_kwh,
        hourly_optimized_consumption_kwh,
        matched_baseline_cost_euro=matched_baseline_cost_euro,
        optimized_cost_euro=optimized_cost_euro,
        chart_window=chart_window,
        chart_now=chart_now,
        chart_zones=chart_zones,
        slot_qualities=slot_qualities,
        history_slot_count=history_slot_count,
        slot_actual_cost_euro=slot_actual_cost_euro,
        slot_actual_consumption_kwh=slot_actual_consumption_kwh,
    )


def add_projected_savings_trace(
    fig: go.Figure,
    uhrzeit: pd.Series,
    axis: ChartSlotAxis,
    projected_savings_cumulative_euro: list[float],
    extrap_start: int | None = None,
    extrap_end: int | None = None,
) -> None:
    """Kumulierte prognostizierte Ersparnis (Produktiv-Historie)."""
    if not projected_savings_cumulative_euro:
        return
    length = len(axis.starts)
    savings_cum = pd.Series(projected_savings_cumulative_euro[:length], dtype=float)
    segments = _trace_segments(length, extrap_start, extrap_end)
    _add_segmented_hv_line(
        fig,
        axis,
        savings_cum,
        uhrzeit,
        segments,
        name="Ersparnis prognostiziert",
        line_kwargs=dict(color=_COLOR_SAVINGS, width=2.5, dash="dot", shape="hv"),
        segment_hover_template=(
            "Uhrzeit: %{customdata}<br>Ersparnis prognostiziert (kumuliert): %{y:.3f} €"
            "<extra></extra>"
        ),
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
    *,
    matched_baseline_cost_euro: float | None = None,
    optimized_cost_euro: float | None = None,
    chart_window: UiChartWindow | None = None,
    chart_now: datetime | None = None,
    chart_zones=None,
    sun_markers: ChartSunMarkers | None = None,
    slot_qualities: tuple[str, ...] | None = None,
    history_slot_count: int | None = None,
    slot_actual_cost_euro: list[float] | None = None,
    slot_actual_consumption_kwh: list[float] | None = None,
    chart_header_label: str | None = None,
    chart_header_help: str | None = None,
    slot_deviation_events: tuple[tuple[DeviationEvent, ...], ...] | None = None,
) -> None:
    """Zeichnet Leistung/SoC/Preis und kumulierte Kosten/Verbrauch in zwei Charts."""
    render_power_soc_chart(
        df,
        baseline_df,
        matched_baseline_df,
        chart_window=chart_window,
        chart_now=chart_now,
        chart_zones=chart_zones,
        sun_markers=sun_markers,
        slot_qualities=slot_qualities,
        history_slot_count=history_slot_count,
        chart_key="live_power_soc_chart",
        chart_header_label=chart_header_label,
        chart_header_help=chart_header_help,
        slot_deviation_events=slot_deviation_events,
    )
    render_price_savings_chart(
        df,
        hourly_matched_baseline_cost_euro,
        hourly_optimized_cost_euro,
        hourly_matched_baseline_consumption_kwh,
        hourly_optimized_consumption_kwh,
        matched_baseline_cost_euro=matched_baseline_cost_euro,
        optimized_cost_euro=optimized_cost_euro,
        chart_window=chart_window,
        chart_now=chart_now,
        chart_zones=chart_zones,
        slot_qualities=slot_qualities,
        history_slot_count=history_slot_count,
        slot_actual_cost_euro=slot_actual_cost_euro,
        slot_actual_consumption_kwh=slot_actual_consumption_kwh,
    )

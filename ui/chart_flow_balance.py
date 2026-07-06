"""
Chart 1 — Rauf/Runter-Energiebilanz (Spezifikation + Berechnung).

Sankey-analog: PV und Netzbezug kräftig nach oben, Verbrauch kräftig nach unten.
Laden, Entladen und Einspeisung gedämpft nach Flusstyp (Batterie→Last grün,
Netz→Batterie cyan, PV→Batterie gelb-grün, PV→Netz blassgelb). Up- und Down-Säule
gleich hoch.
Zeichenkonvention (Chart-/Simulationszeilen):

- ``Geplante Batterie-Aktion (kW)``: positiv = laden, negativ = entladen
- ``Netzbezug (kW)``: positiv = Bezug, negativ = Einspeisung
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
import plotly.graph_objects as go

import config
from optimizer.targets import (
    consumer_column_name,
    consumer_immediate_charge_column_name,
    consumer_pv_follow_column_name,
)

from ui.flow_balance_allocate import FlowAllocation, allocate_slot_flows

FLOW_BALANCE_BAR_WIDTH_FRACTION = 0.9

KIND_BASELOAD = "baseload"
KIND_BATTERY_CHARGE_GRID = "battery_charge_grid"
KIND_BATTERY_CHARGE_PV = "battery_charge_pv"
KIND_BATTERY_DISCHARGE_LOAD = "battery_discharge_load"
KIND_EXPORT_BATTERY = "export_battery"
KIND_EXPORT_PV = "export_pv"
KIND_FLEX = "flex"
KIND_GRID_IMPORT = "grid_import"
KIND_PV = "pv"

# Rückwärtskompatibilität (Tests)
KIND_BATTERY_CHARGE = KIND_BATTERY_CHARGE_PV
KIND_BATTERY_DISCHARGE_BALANCE = KIND_BATTERY_DISCHARGE_LOAD
KIND_BATTERY_DISCHARGE_OFFSET = KIND_BATTERY_DISCHARGE_LOAD
KIND_GRID_EXPORT = KIND_EXPORT_PV
KIND_SURPLUS_BALANCE = KIND_EXPORT_PV
KIND_SURPLUS_OFFSET = KIND_EXPORT_PV

Direction = Literal["up", "down"]


def hsl(h: float, s: float, l: float) -> str:
    """HSL → ``#RRGGBB`` (h: 0–360, s/l: 0–100)."""

    hue = h % 360.0
    sat = max(0.0, min(100.0, s)) / 100.0
    lig = max(0.0, min(100.0, l)) / 100.0

    if sat == 0.0:
        channel = round(lig * 255)
        return f"#{channel:02x}{channel:02x}{channel:02x}"

    def _hue_channel(p: float, q: float, t: float) -> float:
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = lig * (1 + sat) if lig < 0.5 else lig + sat - lig * sat
    p = 2 * lig - q
    hk = hue / 360.0
    red = round(_hue_channel(p, q, hk + 1 / 3) * 255)
    green = round(_hue_channel(p, q, hk) * 255)
    blue = round(_hue_channel(p, q, hk - 1 / 3) * 255)
    return f"#{red:02x}{green:02x}{blue:02x}"


def _lerp_hue(h_a: float, h_b: float, weight: float) -> float:
    """Farbton entlang des kürzesten Kreisbogens interpolieren."""
    delta = ((h_b - h_a + 180.0) % 360.0) - 180.0
    return (h_a + delta * weight) % 360.0


def blend_hsl(
    hsl_a: tuple[float, float, float],
    hsl_b: tuple[float, float, float],
    ratio_b: float,
    l_delta: float = 0.0,
) -> str:
    """
    Mischt zwei HSL-Tripel; ``ratio_b`` = Anteil von ``hsl_b`` (0…1).

    ``l_delta`` verschiebt die Lightness nach der Mischung in Prozentpunkten
    (positiv = heller, negativ = dunkler), begrenzt auf 0…100.
    """
    weight = max(0.0, min(1.0, ratio_b))
    hue = _lerp_hue(hsl_a[0], hsl_b[0], weight)
    sat = hsl_a[1] * (1.0 - weight) + hsl_b[1] * weight
    lig = hsl_a[2] * (1.0 - weight) + hsl_b[2] * weight
    lig = max(0.0, min(100.0, lig + l_delta))
    return hsl(hue, sat, lig)


# Basis-HSL (h: 0–360, s/l: 0–100) — Mischungen unten per ``blend_hsl`` anpassen.
_HSL_PV = (60.0, 90.0, 50.0) # Rein Gelb
_HSL_GRID = (240.0, 90.0, 50.0) # Rein Blau
_HSL_GRID_IMPORT = (240.0, 80.0, 60.0) 
_HSL_BASELOAD = (300.0, 60.0, 50.0) # Rein Magenta
_HSL_BATTERY = (120.0, 100.0, 50.0) # Rein Grün
_HSL_WHITE = (0.0, 0.0, 100.0)

_COLOR_PV = hsl(*_HSL_PV)
_COLOR_GRID = hsl(*_HSL_GRID)
_COLOR_BASELOAD = hsl(*_HSL_BASELOAD)
_COLOR_BATTERY = hsl(*_HSL_BATTERY)
_COLOR_GRID_IMPORT = hsl(*_HSL_GRID_IMPORT)

# Gedämpfte Bilanz-Segmente (Transparenz über Trace-Opacity _MUTED_BAR_OPACITY).
_MUTED_BATTERY_LOAD = blend_hsl(_HSL_BATTERY, _HSL_WHITE, 0.1, 25.0)
_MUTED_BATTERY_CHARGE_PV = blend_hsl(_HSL_PV, _HSL_BATTERY, 0.5, 25)
_MUTED_BATTERY_CHARGE_GRID = blend_hsl(_HSL_BATTERY, _HSL_GRID, 0.6, 35)
_MUTED_BATTERY_EXPORT = blend_hsl(_HSL_BATTERY, _HSL_GRID, 0.5, 0.8)
_MUTED_EXPORT_PV = blend_hsl(_HSL_PV, _HSL_WHITE, 0.1, 25)

COLOR_PV = _COLOR_PV
COLOR_GRID_IMPORT = _COLOR_GRID_IMPORT
COLOR_BASELOAD = _COLOR_BASELOAD
MUTED_BATTERY_CHARGE_PV = _MUTED_BATTERY_CHARGE_PV
MUTED_BATTERY_CHARGE_GRID = _MUTED_BATTERY_CHARGE_GRID
MUTED_BATTERY_LOAD = _MUTED_BATTERY_LOAD
MUTED_BATTERY_EXPORT = _MUTED_BATTERY_EXPORT
MUTED_EXPORT_PV = _MUTED_EXPORT_PV

FLOW_BALANCE_TRACE_ORDER: tuple[str, ...] = (
    KIND_EXPORT_PV,
    KIND_EXPORT_BATTERY,
    KIND_BATTERY_CHARGE_PV,
    KIND_BATTERY_CHARGE_GRID,
    KIND_BASELOAD,
    KIND_FLEX,
    KIND_BATTERY_DISCHARGE_LOAD,
    KIND_PV,
    KIND_GRID_IMPORT,
)
_FLEX_BAR_OPACITY = 0.65
_MUTED_BAR_OPACITY = 0.50
_BRIGHT_BAR_OPACITY = 0.75
_IMMEDIATE_CHARGE_PATTERN = "+"
_PV_FOLLOW_PATTERN = "/"


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return number


def _safe_int_flag(value: Any) -> int:
    return int(_safe_float(value, 0.0))


def _consumer_color(consumer: Mapping[str, Any]) -> str:
    configured = consumer.get("chart_color")
    if configured:
        return str(configured)
    return "#7f8c8d"


@dataclass(frozen=True)
class FlowBalanceSegment:
    """Ein sichtbares Stack-Segment (kW-Magnitude immer >= 0)."""

    kind: str
    label: str
    kw: float
    direction: Direction
    color: str
    consumer_id: str | None = None
    hover_lines: tuple[str, ...] = ()
    muted: bool = False


@dataclass(frozen=True)
class FlowBalanceSlot:
    """Energiebilanz eines Chart-Slots."""

    up: tuple[FlowBalanceSegment, ...]
    down: tuple[FlowBalanceSegment, ...]
    offset_kw: float
    offset_segment: FlowBalanceSegment | None
    up_external_kw: float
    down_primary_kw: float
    battery_discharge_kw: float

    @property
    def up_total_kw(self) -> float:
        return sum(segment.kw for segment in self.up)

    @property
    def down_total_kw(self) -> float:
        return sum(segment.kw for segment in self.down)

    @property
    def is_visually_balanced(self) -> bool:
        return abs(self.up_total_kw - self.down_total_kw) < 1e-6

    @property
    def is_balanced_externally(self) -> bool:
        return abs(self.offset_kw) < 1e-6

    @property
    def down_sinks_kw(self) -> float:
        """Gesamte Down-Säule (Kompatibilität zu älteren Tests)."""
        return self.down_total_kw


@dataclass(frozen=True)
class FlowBalanceTraceSpec:
    """Parameter-Set für einen ``go.Bar``-Trace (ein Segment-Typ pro Chart-Slice)."""

    kind: str
    name: str
    legendgroup: str
    showlegend: bool
    x: tuple[Any, ...]
    y: tuple[float, ...]
    base: tuple[float, ...]
    marker: dict[str, Any]
    customdata: tuple[Any, ...]
    hovertemplate: str
    widths: tuple[float, ...]
    opacity: float = 0.75


def _flex_total_kw(
    row: Mapping[str, Any],
    flex_consumers: Sequence[tuple[Mapping[str, Any], str]] | None,
) -> float:
    pairs = list(flex_consumers) if flex_consumers is not None else _default_flex_pairs(row)
    return sum(_safe_float(row.get(column)) for _, column in pairs)


def _muted_segment(
    *,
    kind: str,
    label: str,
    kw: float,
    direction: Direction,
    color: str,
    hover_lines: tuple[str, ...] = (),
) -> FlowBalanceSegment | None:
    if kw <= 1e-9:
        return None
    return FlowBalanceSegment(
        kind=kind,
        label=label,
        kw=kw,
        direction=direction,
        color=color,
        muted=True,
        hover_lines=hover_lines,
    )


def _segments_from_allocation(
    flows: FlowAllocation,
    *,
    surplus_export_pv: float = 0.0,
) -> tuple[list[FlowBalanceSegment], list[FlowBalanceSegment]]:
    up: list[FlowBalanceSegment] = []
    down: list[FlowBalanceSegment] = []

    export_pv = flows.export_from_pv + surplus_export_pv
    for segment in (
        _muted_segment(
            kind=KIND_BATTERY_CHARGE_PV,
            label="Batterie laden (PV)",
            kw=flows.charge_from_pv,
            direction="down",
            color=_MUTED_BATTERY_CHARGE_PV,
        ),
        _muted_segment(
            kind=KIND_BATTERY_CHARGE_GRID,
            label="Batterie laden (Netz)",
            kw=flows.charge_from_grid,
            direction="down",
            color=_MUTED_BATTERY_CHARGE_GRID,
        ),
        _muted_segment(
            kind=KIND_EXPORT_PV,
            label="Einspeisung (PV)",
            kw=export_pv,
            direction="down",
            color=_MUTED_EXPORT_PV,
        ),
        _muted_segment(
            kind=KIND_EXPORT_BATTERY,
            label="Einspeisung (Batterie)",
            kw=flows.export_from_battery,
            direction="down",
            color=_MUTED_BATTERY_EXPORT,
        ),
        _muted_segment(
            kind=KIND_BATTERY_DISCHARGE_LOAD,
            label="Batterie entladen (Verbrauch)",
            kw=flows.discharge_to_load,
            direction="up",
            color=_MUTED_BATTERY_LOAD,
        ),
    ):
        if segment is None:
            continue
        if segment.direction == "up":
            up.append(segment)
        else:
            down.append(segment)
    return up, down


def build_flow_balance_segments(
    row: Mapping[str, Any],
    *,
    flex_consumers: Sequence[tuple[Mapping[str, Any], str]] | None = None,
) -> FlowBalanceSlot:
    """
    Berechnet Quellen-, Senken- und Offset-Segmente für eine Chart-Zeile.

    Parameters
    ----------
    row:
        Chart-/Simulationszeile mit ``PV-Prognose (kW)``, ``Verbrauch-Prognose (kW)``,
        ``Geplante Batterie-Aktion (kW)``, ``Netzbezug (kW)`` und optional Flex-Spalten.
    flex_consumers:
        ``(consumer_cfg, spaltenname)`` in Stapelreihenfolge unten→oben
        (wie ``ordered_active_consumers_for_stack``). Fehlt die Liste, werden alle
        konfigurierten Optimizer-Verbraucher mit Wert > 0 in Config-Reihenfolge genutzt.

    Returns
    -------
    FlowBalanceSlot
        ``offset_kw``: externe Bilanz (PV + Netzbezug − Grundlast − Flex − Laden),
        vor Ausgleich. ``offset_kw > 0`` → Überschuss (gedämpft ↓), ``< 0`` → Defizit
        (Entladen gedämpft ↑). ``is_visually_balanced`` ist bei konsistenten Zeilen
        immer wahr.
    """
    pv = _safe_float(row.get("PV-Prognose (kW)"))
    baseload = _safe_float(row.get("Verbrauch-Prognose (kW)"))
    battery = _safe_float(row.get("Geplante Batterie-Aktion (kW)"))
    grid = _safe_float(row.get("Netzbezug (kW)"))
    load_kw = baseload + _flex_total_kw(row, flex_consumers)

    grid_import = max(grid, 0.0)
    grid_export = max(-grid, 0.0)
    battery_charge = max(battery, 0.0)
    battery_discharge = max(-battery, 0.0)

    up_segments: list[FlowBalanceSegment] = []
    if pv > 0:
        up_segments.append(
            FlowBalanceSegment(
                kind=KIND_PV,
                label="PV",
                kw=pv,
                direction="up",
                color=_COLOR_PV,
            )
        )
    if grid_import > 0:
        up_segments.append(
            FlowBalanceSegment(
                kind=KIND_GRID_IMPORT,
                label="Netzbezug",
                kw=grid_import,
                direction="up",
                color=_COLOR_GRID_IMPORT,
            )
        )

    down_segments: list[FlowBalanceSegment] = []
    if baseload > 0:
        down_segments.append(
            FlowBalanceSegment(
                kind=KIND_BASELOAD,
                label="Grundlast",
                kw=baseload,
                direction="down",
                color=_COLOR_BASELOAD,
            )
        )

    flex_pairs = list(flex_consumers) if flex_consumers is not None else _default_flex_pairs(row)
    for consumer, column in flex_pairs:
        flex_kw = _safe_float(row.get(column))
        if flex_kw <= 0:
            continue
        hover_lines = _flex_hover_lines(row, consumer, column)
        down_segments.append(
            FlowBalanceSegment(
                kind=KIND_FLEX,
                label=str(consumer.get("name", consumer.get("id", column))),
                kw=flex_kw,
                direction="down",
                color=_consumer_color(consumer),
                consumer_id=str(consumer.get("id", "")) or None,
                hover_lines=hover_lines,
            )
        )

    up_external = pv + grid_import
    down_primary = sum(segment.kw for segment in down_segments)
    offset_kw = up_external - down_primary - battery_charge

    flows = allocate_slot_flows(
        pv=pv,
        load_kw=load_kw,
        battery_charge=battery_charge,
        battery_discharge=battery_discharge,
        grid_import=grid_import,
        grid_export=grid_export,
    )
    surplus_export_pv = 0.0
    if grid_export < 1e-9 and offset_kw > 1e-9:
        surplus_export_pv = offset_kw

    balance_up, balance_down = _segments_from_allocation(
        flows,
        surplus_export_pv=surplus_export_pv,
    )
    up_segments.extend(balance_up)
    down_segments.extend(balance_down)

    return FlowBalanceSlot(
        up=tuple(up_segments),
        down=tuple(down_segments),
        offset_kw=offset_kw,
        offset_segment=None,
        up_external_kw=up_external,
        down_primary_kw=down_primary,
        battery_discharge_kw=battery_discharge,
    )

def build_flow_balance_slots_from_df(
    df: pd.DataFrame,
    flex_consumers: Sequence[tuple[Mapping[str, Any], str]] | None = None,
) -> list[FlowBalanceSlot]:
    """Slot-Bilanz für jede DataFrame-Zeile (gleiche Flex-Reihenfolge für alle Zeilen)."""
    return [
        build_flow_balance_segments(row, flex_consumers=flex_consumers)
        for _, row in df.iterrows()
    ]


def flow_balance_plotly_trace_specs(
    slots: Sequence[FlowBalanceSlot],
    *,
    x_values: Sequence[Any],
    uhrzeit: Sequence[str],
    start: int,
    end: int,
    df: pd.DataFrame | None = None,
    flex_consumers: Sequence[tuple[Mapping[str, Any], str]] | None = None,
    axis: Any = None,
) -> list[FlowBalanceTraceSpec]:
    """
    Erzeugt die geplante Plotly-``go.Bar``-Liste für ``slots[start:end]``.

    ``x_values`` und ``uhrzeit`` sind auf ``[start, end)`` gesliced (Länge ``end - start``).
    """
    buckets: dict[str, dict[str, list[Any]]] = {}

    for local_index, index in enumerate(range(start, end)):
        slot = slots[index]
        x_val = x_values[local_index]
        time_label = uhrzeit[local_index]
        row = df.iloc[index] if df is not None else None
        bar_width_ms = (
            axis.bar_width_ms(FLOW_BALANCE_BAR_WIDTH_FRACTION, index)
            if axis is not None
            else 0.0
        )
        _accumulate_slot_traces(
            buckets,
            slot,
            x_val,
            time_label,
            row=row,
            flex_consumers=flex_consumers,
            bar_width_ms=bar_width_ms,
        )

    return _bucket_specs_to_trace_specs(buckets)


def flow_balance_plotly_traces(
    df: pd.DataFrame,
    slots: Sequence[FlowBalanceSlot],
    axis: Any,
    start: int,
    end: int,
    *,
    flex_consumers: Sequence[tuple[Mapping[str, Any], str]] | None = None,
    showlegend_by_kind: dict[str, bool] | None = None,
    legend_shown: set[str] | None = None,
) -> tuple[list[go.Bar], set[str]]:
    """
    Konkrete ``go.Bar``-Traces für Chart-1-Einbindung.

    ``axis`` ist ``ui.charts.ChartSlotAxis`` (Any wegen Import-Zyklus).
    """
    from ui.charts import _battery_bar_times

    x_series = _battery_bar_times(axis, slice(start, end))
    uhrzeit = df["Uhrzeit"].iloc[start:end]
    specs = flow_balance_plotly_trace_specs(
        slots,
        x_values=list(x_series),
        uhrzeit=list(uhrzeit),
        start=start,
        end=end,
        df=df,
        flex_consumers=flex_consumers,
        axis=axis,
    )
    shown = set(legend_shown or ())
    traces: list[go.Bar] = []
    ordered_specs = sorted(
        specs,
        key=lambda spec: (
            FLOW_BALANCE_TRACE_ORDER.index(spec.kind)
            if spec.kind in FLOW_BALANCE_TRACE_ORDER
            else len(FLOW_BALANCE_TRACE_ORDER)
        ),
    )
    for spec in ordered_specs:
        show = showlegend_by_kind.get(spec.kind, True) if showlegend_by_kind else True
        if spec.legendgroup in shown:
            show = False
        elif show:
            shown.add(spec.legendgroup)
        traces.append(
            go.Bar(
                x=spec.x,
                y=spec.y,
                base=spec.base,
                name=spec.name,
                legendgroup=spec.legendgroup,
                showlegend=show,
                marker=spec.marker,
                opacity=spec.opacity,
                width=list(spec.widths),
                yaxis="y",
                customdata=spec.customdata,
                hovertemplate=spec.hovertemplate,
            )
        )
    return traces, shown


def add_flow_balance_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    slots: Sequence[FlowBalanceSlot],
    axis: Any,
    extrap_start: int | None = None,
    extrap_end: int | None = None,
    *,
    flex_consumers: Sequence[tuple[Mapping[str, Any], str]] | None = None,
) -> None:
    """
    Fügt Rauf/Runter-Balken zum Figure hinzu (ersetzt Batterie- + Flex-Balken).

    Extrapolations-Segmente analog ``add_power_traces`` / ``_trace_segments``.
    """
    from ui.charts import _trace_segments

    length = len(df)
    legend_shown: set[str] = set()
    for _seg_index, (seg_start, seg_end, _is_extrapolated) in enumerate(
        _trace_segments(length, extrap_start, extrap_end)
    ):
        if seg_start >= seg_end:
            continue
        traces, legend_shown = flow_balance_plotly_traces(
            df,
            slots,
            axis,
            seg_start,
            seg_end,
            flex_consumers=flex_consumers,
            legend_shown=legend_shown,
        )
        for trace in traces:
            fig.add_trace(trace)


def _default_flex_pairs(row: Mapping[str, Any]) -> list[tuple[dict, str]]:
    pairs: list[tuple[dict, str]] = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        column = consumer_column_name(consumer)
        if _safe_float(row.get(column)) > 0:
            pairs.append((consumer, column))
    return pairs


def _flex_hover_lines(
    row: Mapping[str, Any],
    consumer: Mapping[str, Any],
    column: str,
) -> tuple[str, ...]:
    pv_follow_col = consumer_pv_follow_column_name(consumer)
    immediate_col = consumer_immediate_charge_column_name(consumer)
    lines: list[str] = []
    if pv_follow_col in row:
        lines.append(f"pv_follow: {_safe_int_flag(row.get(pv_follow_col, 0))}")
    if immediate_col in row:
        lines.append(f"sofort_laden: {_safe_int_flag(row.get(immediate_col, 0))}")
    if not lines and column in row:
        return ()
    return tuple(lines)


def _flex_pattern_shape(
    row: Mapping[str, Any] | None,
    consumer: Mapping[str, Any],
    column: str,
) -> str:
    if row is None:
        return ""
    power = _safe_float(row.get(column))
    if power <= 1e-6:
        return ""
    immediate_col = consumer_immediate_charge_column_name(consumer)
    if immediate_col in row and _safe_int_flag(row.get(immediate_col, 0)) == 1:
        return _IMMEDIATE_CHARGE_PATTERN
    pv_follow_col = consumer_pv_follow_column_name(consumer)
    if pv_follow_col in row and _safe_int_flag(row.get(pv_follow_col, 0)) == 1:
        return _PV_FOLLOW_PATTERN
    return ""


def _accumulate_slot_traces(
    buckets: dict[str, dict[str, list[Any]]],
    slot: FlowBalanceSlot,
    x_val: Any,
    time_label: str,
    *,
    row: pd.Series | None = None,
    flex_consumers: Sequence[tuple[Mapping[str, Any], str]] | None = None,
    bar_width_ms: float,
) -> None:
    flex_by_id = {
        str(consumer.get("id", "")): (consumer, column)
        for consumer, column in (flex_consumers or ())
    }
    cumulative_up = 0.0
    for segment in slot.up:
        _append_stack_bucket(
            buckets,
            segment,
            x_val,
            time_label,
            direction="up",
            cumulative=cumulative_up,
            bar_width_ms=bar_width_ms,
        )
        cumulative_up += segment.kw

    cumulative_down = 0.0
    for segment in slot.down:
        pattern_shape = ""
        flex_meta: tuple[Any, ...] = ()
        if segment.kind == KIND_FLEX and segment.consumer_id in flex_by_id:
            consumer, column = flex_by_id[segment.consumer_id]
            pattern_shape = _flex_pattern_shape(
                row.to_dict() if row is not None else None,
                consumer,
                column,
            )
            if row is not None:
                pv_col = consumer_pv_follow_column_name(consumer)
                imm_col = consumer_immediate_charge_column_name(consumer)
                flex_meta = (
                    _safe_int_flag(row.get(pv_col, 0)) if pv_col in row else 0,
                    _safe_int_flag(row.get(imm_col, 0)) if imm_col in row else 0,
                )
        _append_stack_bucket(
            buckets,
            segment,
            x_val,
            time_label,
            direction="down",
            cumulative=cumulative_down,
            pattern_shape=pattern_shape,
            flex_meta=flex_meta,
            bar_width_ms=bar_width_ms,
        )
        cumulative_down += segment.kw


def _bucket_key(segment: FlowBalanceSegment) -> str:
    if segment.kind == KIND_FLEX and segment.consumer_id:
        return f"{segment.kind}:{segment.consumer_id}"
    return segment.kind


def _append_stack_bucket(
    buckets: dict[str, dict[str, list[Any]]],
    segment: FlowBalanceSegment,
    x_val: Any,
    time_label: str,
    *,
    direction: Direction,
    cumulative: float,
    pattern_shape: str = "",
    flex_meta: tuple[Any, ...] = (),
    bar_width_ms: float,
) -> None:
    key = _bucket_key(segment)
    bucket = buckets.setdefault(
        key,
        {
            "segment": segment,
            "x": [],
            "y": [],
            "base": [],
            "customdata": [],
            "pattern_shapes": [],
            "widths": [],
        },
    )
    signed_height = segment.kw if direction == "up" else -segment.kw
    signed_base = cumulative if direction == "up" else -cumulative
    bucket["x"].append(x_val)
    bucket["y"].append(signed_height)
    bucket["base"].append(signed_base)
    if segment.kind == KIND_FLEX and flex_meta:
        bucket["customdata"].append(
            (time_label, segment.kw, segment.label, flex_meta[0], flex_meta[1])
        )
    else:
        bucket["customdata"].append((time_label, segment.kw, segment.label))
    bucket["pattern_shapes"].append(pattern_shape)
    bucket["widths"].append(bar_width_ms)


def _bucket_specs_to_trace_specs(
    buckets: dict[str, dict[str, list[Any]]],
) -> list[FlowBalanceTraceSpec]:
    from ui.charts import _consumer_bar_marker

    specs: list[FlowBalanceTraceSpec] = []
    for bucket in buckets.values():
        segment: FlowBalanceSegment = bucket["segment"]
        pattern_shapes = list(bucket.get("pattern_shapes", []))
        if segment.kind == KIND_FLEX:
            marker = _consumer_bar_marker(
                segment.color,
                pattern_shapes,
                _FLEX_BAR_OPACITY,
            )
            hovertemplate = (
                "Uhrzeit: %{customdata[0]}<br>%{customdata[2]}: "
                "%{customdata[1]:.2f} kW<br>pv_follow: %{customdata[3]}<br>"
                "sofort_laden: %{customdata[4]}<extra></extra>"
            )
        else:
            marker = {"color": segment.color}
            hovertemplate = (
                "Uhrzeit: %{customdata[0]}<br>%{customdata[2]}: "
                "%{customdata[1]:.2f} kW<extra></extra>"
            )
        opacity = _MUTED_BAR_OPACITY if segment.muted else _BRIGHT_BAR_OPACITY
        specs.append(
            FlowBalanceTraceSpec(
                kind=segment.kind,
                name=segment.label,
                legendgroup=_bucket_key(segment),
                showlegend=True,
                x=tuple(bucket["x"]),
                y=tuple(bucket["y"]),
                base=tuple(bucket["base"]),
                marker=marker,
                customdata=tuple(bucket["customdata"]),
                hovertemplate=hovertemplate,
                widths=tuple(bucket["widths"]),
                opacity=opacity,
            )
        )
    return specs


def energy_balance_residual_kw(row: Mapping[str, Any]) -> float:
    """
    Prüfgröße: Abweichung von der Energiebilanz (sollte ≈ 0 sein).

    PV + Netz_import + Batt_entladen − Grundlast − Flex − Batt_laden − Einspeisung
    """
    pv = _safe_float(row.get("PV-Prognose (kW)"))
    baseload = _safe_float(row.get("Verbrauch-Prognose (kW)"))
    battery = _safe_float(row.get("Geplante Batterie-Aktion (kW)"))
    grid = _safe_float(row.get("Netzbezug (kW)"))
    flex_total = sum(kw for _, kw in _flex_kw_pairs(row))
    supply = pv + max(grid, 0.0) + max(-battery, 0.0)
    demand = baseload + flex_total + max(battery, 0.0) + max(-grid, 0.0)
    return supply - demand


def _flex_kw_pairs(row: Mapping[str, Any]) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    for consumer, column in _default_flex_pairs(row):
        pairs.append((column, _safe_float(row.get(column))))
    return pairs

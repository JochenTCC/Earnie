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
from datetime import datetime
from typing import Any, Literal

import pandas as pd
import plotly.graph_objects as go

import config
from data.planning_window import UiChartZones, chart_zone_kind_for_slot_start
from optimizer import battery as bat
from runtime_store.history_timeline import CHART_IST_BATTERY_KW_COLUMN, PV_IST_COLUMN
from optimizer.targets import (
    consumer_column_name,
    consumer_immediate_charge_column_name,
    consumer_pv_follow_column_name,
)

from ui.flow_balance_allocate import FlowAllocation, allocate_slot_flows
from ui.chart_colors import (
    COLOR_BASELOAD,
    COLOR_BATTERY,
    COLOR_GRID_IMPORT,
    COLOR_PV,
    MUTED_BATTERY_CHARGE_GRID,
    MUTED_BATTERY_CHARGE_PV,
    MUTED_BATTERY_EXPORT,
    MUTED_BATTERY_LOAD,
    MUTED_EXPORT_PV,
    blend_hsl,
    chart1_baseload_color_for_zone,
    chart1_pv_color_for_zone,
    flex_bar_chart_color,
    consumer_chart_saturation_for_zone,
    hsl,
)

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


def _optional_soc_percent(row: Mapping[str, Any]) -> float | None:
    if "Simulierter SoC (%)" not in row:
        return None
    value = row.get("Simulierter SoC (%)")
    if value is None:
        return None
    try:
        soc = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(soc):
        return None
    return soc


def _optional_column_float(row: Mapping[str, Any], column: str) -> float | None:
    if column not in row:
        return None
    value = row.get(column)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _battery_for_flow_balance(
    row: Mapping[str, Any],
    battery_plan_kw: float,
) -> tuple[float, float, float, bool]:
    """
    Batterieleistung für die Flusszuordnung.

    Produktiv-Log (grau): ``CHART_IST_BATTERY_KW_COLUMN`` aus Loxone-Snapshot.
    MILP/neutral: geplanter Wert, ggf. SoC-Rand-Korrektur.

    Returns
    -------
    battery_kw, charge_skipped_kw, discharge_skipped_kw, uses_logged_ist
    """
    ist = _optional_column_float(row, CHART_IST_BATTERY_KW_COLUMN)
    if ist is not None:
        return ist, 0.0, 0.0, True
    capped, charge_skipped, discharge_skipped = _soc_capped_battery_plan(
        row,
        battery_plan_kw,
    )
    return capped, charge_skipped, discharge_skipped, False


def _soc_capped_battery_plan(
    row: Mapping[str, Any],
    battery_kw: float,
) -> tuple[float, float, float]:
    """
    Begrenzt Batterieleistung nur am SoC-Rand (volle/leere Batterie) — nur MILP/neutral,
    nicht wenn ``CHART_IST_BATTERY_KW_COLUMN`` aus dem Produktiv-Log gesetzt ist.

    Returns
    -------
    capped_kw, charge_skipped_kw, discharge_skipped_kw
    """
    soc = _optional_soc_percent(row)
    if soc is None:
        return battery_kw, 0.0, 0.0
    params = config.get_battery_params()
    max_soc = float(params["max_soc"])
    min_soc = float(params["min_soc"])
    eps = bat.SOC_DELTA_THRESHOLD

    if battery_kw > 0 and soc >= max_soc - eps:
        return 0.0, battery_kw, 0.0
    if battery_kw < 0 and soc <= min_soc + eps:
        return 0.0, 0.0, -battery_kw
    return battery_kw, 0.0, 0.0


def _safe_int_flag(value: Any) -> int:
    return int(_safe_float(value, 0.0))


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
    legend_color: str | None = None


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
            color=MUTED_BATTERY_CHARGE_PV,
        ),
        _muted_segment(
            kind=KIND_BATTERY_CHARGE_GRID,
            label="Batterie laden (Netz)",
            kw=flows.charge_from_grid,
            direction="down",
            color=MUTED_BATTERY_CHARGE_GRID,
        ),
        _muted_segment(
            kind=KIND_EXPORT_PV,
            label="Einspeisung (PV)",
            kw=export_pv,
            direction="down",
            color=MUTED_EXPORT_PV,
        ),
        _muted_segment(
            kind=KIND_EXPORT_BATTERY,
            label="Einspeisung (Batterie)",
            kw=flows.export_from_battery,
            direction="down",
            color=MUTED_BATTERY_EXPORT,
        ),
        _muted_segment(
            kind=KIND_BATTERY_DISCHARGE_LOAD,
            label="Batterie entladen (Verbrauch)",
            kw=flows.discharge_to_load,
            direction="up",
            color=MUTED_BATTERY_LOAD,
        ),
    ):
        if segment is None:
            continue
        if segment.direction == "up":
            up.append(segment)
        else:
            down.append(segment)
    return up, down


def _pv_kw_from_row(row: Mapping[str, Any]) -> float:
    """PV für Flow-Balance: Ist aus Log-Snapshot, sonst Prognose."""
    if PV_IST_COLUMN in row:
        ist = _safe_float(row.get(PV_IST_COLUMN), default=float("nan"))
        if not math.isnan(ist):
            return ist
    return _safe_float(row.get("PV-Prognose (kW)"))


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
        ``Geplante Batterie-Aktion (kW)``, ``Netzbezug (kW)``, optional
        ``CHART_IST_BATTERY_KW_COLUMN`` (Produktiv-Log) und Flex-Spalten.
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
    pv = _pv_kw_from_row(row)
    baseload = _safe_float(row.get("Verbrauch-Prognose (kW)"))
    battery_raw = _safe_float(row.get("Geplante Batterie-Aktion (kW)"))
    grid = _safe_float(row.get("Netzbezug (kW)"))
    load_kw = baseload + _flex_total_kw(row, flex_consumers)

    battery, charge_skipped, discharge_skipped, _uses_ist = _battery_for_flow_balance(
        row,
        battery_raw,
    )
    grid_import = max(grid, 0.0) + discharge_skipped
    grid_export = max(-grid, 0.0) + charge_skipped
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
                color=COLOR_PV,
            )
        )
    if grid_import > 0:
        up_segments.append(
            FlowBalanceSegment(
                kind=KIND_GRID_IMPORT,
                label="Netzbezug",
                kw=grid_import,
                direction="up",
                color=COLOR_GRID_IMPORT,
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
                color=COLOR_BASELOAD,
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
                color=flex_bar_chart_color(consumer),
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
    chart_zones: UiChartZones | None = None,
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
        slot_start = None
        if row is not None and "slot_datetime" in row.index:
            slot_start = row["slot_datetime"]
            if hasattr(slot_start, "to_pydatetime"):
                slot_start = slot_start.to_pydatetime()
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
            chart_zones=chart_zones,
            slot_start=slot_start,
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
    chart_zones: UiChartZones | None = None,
) -> tuple[list[go.Bar], set[str]]:
    """
    Konkrete ``go.Bar``-Traces für Chart-1-Einbindung.

    ``axis`` ist ``ui.charts.ChartSlotAxis`` (Any wegen Import-Zyklus).
    """
    from ui.chart_slot_axis import _battery_bar_times

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
        chart_zones=chart_zones,
    )
    shown = set(legend_shown or ())
    traces: list[go.Bar] = []
    flex_legend_colors: dict[str, tuple[str, str]] = {}
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
        if chart_zones and spec.kind == KIND_FLEX:
            if spec.legend_color is not None:
                flex_legend_colors.setdefault(
                    spec.legendgroup,
                    (spec.name, spec.legend_color),
                )
            show = False
        elif spec.legendgroup in shown:
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
    if chart_zones:
        for legendgroup, (name, color) in flex_legend_colors.items():
            if legendgroup in shown:
                continue
            shown.add(legendgroup)
            traces.append(
                go.Bar(
                    x=[None],
                    y=[None],
                    name=name,
                    legendgroup=legendgroup,
                    showlegend=True,
                    marker=dict(color=color),
                    visible="legendonly",
                    hoverinfo="skip",
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
    chart_zones: UiChartZones | None = None,
) -> None:
    """
    Fügt Rauf/Runter-Balken zum Figure hinzu (ersetzt Batterie- + Flex-Balken).

    Extrapolations-Segmente analog ``add_power_traces`` / ``_trace_segments``.
    """
    from ui.chart_trace_segments import _trace_segments

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
            chart_zones=chart_zones,
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
    chart_zones: UiChartZones | None = None,
    slot_start: datetime | None = None,
) -> None:
    flex_by_id = {
        str(consumer.get("id", "")): (consumer, column)
        for consumer, column in (flex_consumers or ())
    }
    cumulative_up = 0.0
    for segment in slot.up:
        zone_kind = None
        bar_color = None
        if (
            chart_zones is not None
            and slot_start is not None
            and segment.kind == KIND_PV
        ):
            zone_kind = chart_zone_kind_for_slot_start(slot_start, chart_zones)
            bar_color = chart1_pv_color_for_zone(zone_kind)
        _append_stack_bucket(
            buckets,
            segment,
            x_val,
            time_label,
            direction="up",
            cumulative=cumulative_up,
            bar_width_ms=bar_width_ms,
            zone_kind=zone_kind,
            bar_color=bar_color,
        )
        cumulative_up += segment.kw

    cumulative_down = 0.0
    for segment in slot.down:
        pattern_shape = ""
        flex_meta: tuple[Any, ...] = ()
        zone_kind: str | None = None
        bar_color: str | None = None
        if chart_zones is not None and slot_start is not None:
            zone_kind = chart_zone_kind_for_slot_start(slot_start, chart_zones)
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
            if zone_kind is not None:
                saturation = consumer_chart_saturation_for_zone(zone_kind)
                bar_color = flex_bar_chart_color(
                    consumer,
                    saturation_factor=saturation,
                )
        elif segment.kind == KIND_BASELOAD and zone_kind is not None:
            bar_color = chart1_baseload_color_for_zone(zone_kind)
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
            zone_kind=zone_kind,
            bar_color=bar_color,
        )
        cumulative_down += segment.kw


def _bucket_key(segment: FlowBalanceSegment, *, zone_kind: str | None = None) -> str:
    if segment.kind in {KIND_PV, KIND_BASELOAD} and zone_kind is not None:
        return f"{segment.kind}:{zone_kind}"
    if segment.kind == KIND_FLEX and segment.consumer_id:
        if zone_kind is not None:
            return f"{segment.kind}:{segment.consumer_id}:{zone_kind}"
        return f"{segment.kind}:{segment.consumer_id}"
    return segment.kind


def _flex_legendgroup(segment: FlowBalanceSegment) -> str:
    if segment.kind == KIND_FLEX and segment.consumer_id:
        return f"{segment.kind}:{segment.consumer_id}"
    return _bucket_key(segment)


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
    zone_kind: str | None = None,
    bar_color: str | None = None,
) -> None:
    key = _bucket_key(segment, zone_kind=zone_kind)
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
    if bar_color is not None:
        bucket["bar_color"] = bar_color
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
    from ui.chart_consumer_stack import _consumer_bar_marker

    specs: list[FlowBalanceTraceSpec] = []
    for bucket in buckets.values():
        segment: FlowBalanceSegment = bucket["segment"]
        pattern_shapes = list(bucket.get("pattern_shapes", []))
        bar_color = bucket.get("bar_color", segment.color)
        if segment.kind == KIND_FLEX:
            marker = _consumer_bar_marker(
                bar_color,
                pattern_shapes,
                _FLEX_BAR_OPACITY,
            )
            hovertemplate = (
                "Uhrzeit: %{customdata[0]}<br>%{customdata[2]}: "
                "%{customdata[1]:.2f} kW<br>pv_follow: %{customdata[3]}<br>"
                "sofort_laden: %{customdata[4]}<extra></extra>"
            )
            legend_color = segment.color
        else:
            marker = {"color": bar_color}
            hovertemplate = (
                "Uhrzeit: %{customdata[0]}<br>%{customdata[2]}: "
                "%{customdata[1]:.2f} kW<extra></extra>"
            )
            legend_color = None
        opacity = _MUTED_BAR_OPACITY if segment.muted else _BRIGHT_BAR_OPACITY
        specs.append(
            FlowBalanceTraceSpec(
                kind=segment.kind,
                name=segment.label,
                legendgroup=_flex_legendgroup(segment),
                showlegend=True,
                x=tuple(bucket["x"]),
                y=tuple(bucket["y"]),
                base=tuple(bucket["base"]),
                marker=marker,
                customdata=tuple(bucket["customdata"]),
                hovertemplate=hovertemplate,
                widths=tuple(bucket["widths"]),
                opacity=opacity,
                legend_color=legend_color,
            )
        )
    return specs


def energy_balance_residual_kw(row: Mapping[str, Any]) -> float:
    """
    Prüfgröße: Abweichung von der Energiebilanz (sollte ≈ 0 sein).

    PV + Netz_import + Batt_entladen − Grundlast − Flex − Batt_laden − Einspeisung
    """
    pv = _pv_kw_from_row(row)
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

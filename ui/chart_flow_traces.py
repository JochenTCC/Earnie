"""Flow-balance Plotly traces (Chart 1); flex ghosts live in ``chart_flow_ghosts``."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import pandas as pd
import plotly.graph_objects as go

import config
from data.planning_window import UiChartZones, chart_zone_kind_for_slot_start, parse_chart_row_slot_datetime
from optimizer import battery as bat
from runtime_store.history_timeline import CHART_IST_BATTERY_KW_COLUMN, PV_IST_COLUMN
from optimizer.targets import (
    consumer_immediate_charge_column_name,
    consumer_immediate_charge_hover_label,
    consumer_pv_follow_column_name,
)

from ui.chart_flow_ghosts import add_matched_flex_ghost_traces  # noqa: F401
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
    manual_appliance_pattern_shape,
    consumer_chart_saturation_for_zone,
    hsl,
)
from ui.chart_flow_segments import (
    FLOW_BALANCE_BAR_WIDTH_FRACTION,
    KIND_BASELOAD,
    KIND_BATTERY_CHARGE_GRID,
    KIND_BATTERY_CHARGE_PV,
    KIND_BATTERY_DISCHARGE_LOAD,
    KIND_EXPORT_BATTERY,
    KIND_EXPORT_PV,
    KIND_FLEX,
    KIND_GRID_IMPORT,
    KIND_PV,
    FlowBalanceSegment,
    FlowBalanceSlot,
    FlowBalanceTraceSpec,
    _FLEX_BAR_OPACITY,
    _MUTED_BAR_OPACITY,
    _BRIGHT_BAR_OPACITY,
    _IMMEDIATE_CHARGE_PATTERN,
    _PV_FOLLOW_PATTERN,
    _default_flex_pairs,
    _flex_hover_lines,
    _flex_kw_pairs,
    _flex_pattern_shape,
    _safe_int_flag,
    build_flow_balance_slots_from_df,
)


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
            slot_start = parse_chart_row_slot_datetime(row.to_dict())
            if slot_start is None:
                raw_slot = row["slot_datetime"]
                if hasattr(raw_slot, "to_pydatetime"):
                    slot_start = raw_slot.to_pydatetime()
                elif isinstance(raw_slot, datetime):
                    slot_start = raw_slot
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

def _ordered_flow_specs(
    specs: Sequence[FlowBalanceTraceSpec],
) -> list[FlowBalanceTraceSpec]:
    return sorted(
        specs,
        key=lambda spec: (
            FLOW_BALANCE_TRACE_ORDER.index(spec.kind)
            if spec.kind in FLOW_BALANCE_TRACE_ORDER
            else len(FLOW_BALANCE_TRACE_ORDER)
        ),
    )


def _flow_spec_to_bar(spec: FlowBalanceTraceSpec, show: bool) -> go.Bar:
    return go.Bar(
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


def _flex_legend_placeholder_traces(
    flex_legend_colors: dict[str, tuple[str, str]],
    shown: set[str],
) -> list[go.Bar]:
    """Unsichtbare Legendeneinträge je Flex-Gruppe; ergänzt ``shown`` in-place."""
    traces: list[go.Bar] = []
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
    return traces


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
    for spec in _ordered_flow_specs(specs):
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
        traces.append(_flow_spec_to_bar(spec, show))
    if chart_zones:
        traces.extend(_flex_legend_placeholder_traces(flex_legend_colors, shown))
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




@dataclass(frozen=True)
class _SlotBucketContext:
    """Slot-Kontext für die Up-/Down-Stack-Akkumulation eines Zeitschritts."""

    x_val: Any
    time_label: str
    bar_width_ms: float
    chart_zones: UiChartZones | None
    slot_start: datetime | None
    row: pd.Series | None
    flex_by_id: Mapping[str, tuple[Mapping[str, Any], str]]


def _accumulate_up_segments(
    buckets: dict[str, dict[str, list[Any]]],
    slot: FlowBalanceSlot,
    ctx: _SlotBucketContext,
) -> None:
    cumulative_up = 0.0
    for segment in slot.up:
        zone_kind = None
        bar_color = None
        if (
            ctx.chart_zones is not None
            and ctx.slot_start is not None
            and segment.kind == KIND_PV
        ):
            zone_kind = chart_zone_kind_for_slot_start(ctx.slot_start, ctx.chart_zones)
            bar_color = chart1_pv_color_for_zone(zone_kind)
        _append_stack_bucket(
            buckets,
            segment,
            ctx.x_val,
            ctx.time_label,
            direction="up",
            cumulative=cumulative_up,
            power_kw=segment.kw,
            bar_width_ms=ctx.bar_width_ms,
            zone_kind=zone_kind,
            bar_color=bar_color,
        )
        cumulative_up += segment.kw


def _flex_segment_style(
    consumer: Mapping[str, Any],
    column: str,
    row: pd.Series | None,
    zone_kind: str | None,
) -> tuple[str, tuple[Any, ...], str | None]:
    """Pattern, Hover-Metadaten und Zonenfarbe eines Flex-Segments."""
    pattern_shape = _flex_pattern_shape(
        row.to_dict() if row is not None else None,
        consumer,
        column,
    )
    if not pattern_shape:
        from optimizer.appliance_schedule import is_manual_appliance_chart_consumer

        if is_manual_appliance_chart_consumer(consumer):
            pattern_shape = manual_appliance_pattern_shape(
                str(consumer.get("id", "")),
            )
    flex_meta: tuple[Any, ...] = ()
    if row is not None:
        pv_col = consumer_pv_follow_column_name(consumer)
        imm_col = consumer_immediate_charge_column_name(consumer)
        flex_meta = (
            _safe_int_flag(row.get(pv_col, 0)) if pv_col in row else 0,
            _safe_int_flag(row.get(imm_col, 0)) if imm_col in row else 0,
            consumer_immediate_charge_hover_label(consumer),
        )
    bar_color: str | None = None
    if zone_kind is not None:
        saturation = consumer_chart_saturation_for_zone(zone_kind)
        bar_color = flex_bar_chart_color(consumer, saturation_factor=saturation)
    return pattern_shape, flex_meta, bar_color


def _accumulate_down_segments(
    buckets: dict[str, dict[str, list[Any]]],
    slot: FlowBalanceSlot,
    ctx: _SlotBucketContext,
) -> None:
    cumulative_down = 0.0
    for segment in slot.down:
        pattern_shape = ""
        flex_meta: tuple[Any, ...] = ()
        zone_kind: str | None = None
        bar_color: str | None = None
        if ctx.chart_zones is not None and ctx.slot_start is not None:
            zone_kind = chart_zone_kind_for_slot_start(ctx.slot_start, ctx.chart_zones)
        if segment.kind == KIND_FLEX and segment.consumer_id in ctx.flex_by_id:
            consumer, column = ctx.flex_by_id[segment.consumer_id]
            pattern_shape, flex_meta, bar_color = _flex_segment_style(
                consumer, column, ctx.row, zone_kind
            )
        elif segment.kind == KIND_BASELOAD and zone_kind is not None:
            bar_color = chart1_baseload_color_for_zone(zone_kind)
        _append_stack_bucket(
            buckets,
            segment,
            ctx.x_val,
            ctx.time_label,
            direction="down",
            cumulative=cumulative_down,
            power_kw=segment.kw,
            pattern_shape=pattern_shape,
            flex_meta=flex_meta,
            bar_width_ms=ctx.bar_width_ms,
            zone_kind=zone_kind,
            bar_color=bar_color,
        )
        cumulative_down += segment.kw


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
    ctx = _SlotBucketContext(
        x_val=x_val,
        time_label=time_label,
        bar_width_ms=bar_width_ms,
        chart_zones=chart_zones,
        slot_start=slot_start,
        row=row,
        flex_by_id={
            str(consumer.get("id", "")): (consumer, column)
            for consumer, column in (flex_consumers or ())
        },
    )
    _accumulate_up_segments(buckets, slot, ctx)
    _accumulate_down_segments(buckets, slot, ctx)

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
    power_kw: float,
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
    signed_height = power_kw if direction == "up" else -power_kw
    signed_base = cumulative if direction == "up" else -cumulative
    bucket["x"].append(x_val)
    bucket["y"].append(signed_height)
    bucket["base"].append(signed_base)
    if segment.kind == KIND_FLEX and flex_meta:
        bucket["customdata"].append(
            (time_label, power_kw, segment.label, flex_meta[0], flex_meta[1])
        )
        if len(flex_meta) >= 3:
            bucket["immediate_hover_label"] = flex_meta[2]
    else:
        bucket["customdata"].append((time_label, power_kw, segment.label))
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
            imm_label = bucket.get("immediate_hover_label", "sofort_laden")
            hovertemplate = (
                f"Uhrzeit: %{{customdata[0]}}<br>%{{customdata[2]}}: "
                f"%{{customdata[1]:.2f}} kW<br>pv_follow: %{{customdata[3]}}<br>"
                f"{imm_label}: %{{customdata[4]}}<extra></extra>"
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

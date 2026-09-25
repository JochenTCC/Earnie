"""Ghost outlines for the matched-baseline flex schedule (Chart 1)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from optimizer.targets import consumer_column_name
from ui.chart_colors import flex_bar_chart_color
from ui.chart_consumer_stack import _chart_flex_consumers
from ui.chart_flow_segments import FLOW_BALANCE_BAR_WIDTH_FRACTION, _safe_float

_GHOST_LINE_WIDTH = 2.5

_GHOST_MIN_KWH = 1.0


def add_matched_flex_ghost_traces(
    fig: go.Figure,
    matched_baseline_df: pd.DataFrame | None,
    axis: Any,
    *,
    flex_consumers: Sequence[tuple[Mapping[str, Any], str]] | None = None,
    history_slot_count: int | None = None,
) -> None:
    """
    Umrandete (nicht gefüllte) Flex-Balken für Original-Schedule (BL-Ziel-Lastzeiten).

    Stackt nur die Matched-Baseline-Flex-Leistung (kW) ab ``history_slot_count``
    nach unten — unabhängig vom optimierten Stack. Segmente mit
    Energie-Äquivalent unter ``_GHOST_MIN_KWH`` (Roh-kW × Slotdauer) werden
    weggelassen. Balkenhöhe ist auf ``nominal_power_kw`` begrenzt, wenn gesetzt.
    """
    if matched_baseline_df is None or matched_baseline_df.empty:
        return
    length = len(matched_baseline_df)
    start = int(history_slot_count or 0)
    if start >= length:
        return
    pairs = _ghost_flex_pairs(matched_baseline_df, flex_consumers)
    if not pairs:
        return
    buckets = _collect_ghost_buckets(matched_baseline_df, axis, pairs, start)
    _add_ghost_bucket_traces(fig, buckets)


def _ghost_flex_pairs(
    matched_baseline_df: pd.DataFrame,
    flex_consumers: Sequence[tuple[Mapping[str, Any], str]] | None,
) -> list[tuple[Mapping[str, Any], str]]:
    if flex_consumers is not None:
        return list(flex_consumers)
    pairs: list[tuple[Mapping[str, Any], str]] = []
    for consumer in _chart_flex_consumers():
        column = consumer_column_name(consumer)
        if column in matched_baseline_df.columns:
            pairs.append((consumer, column))
    return pairs


def _collect_ghost_buckets(
    matched_baseline_df: pd.DataFrame,
    axis: Any,
    pairs: Sequence[tuple[Mapping[str, Any], str]],
    start: int,
) -> dict[str, dict[str, list[Any]]]:
    from ui.chart_slot_axis import _battery_bar_times

    buckets: dict[str, dict[str, list[Any]]] = {}
    for index in range(start, len(matched_baseline_df)):
        row = matched_baseline_df.iloc[index]
        x_val = list(_battery_bar_times(axis, slice(index, index + 1)))[0]
        time_label = str(row.get("Uhrzeit", ""))
        bar_width_ms = axis.bar_width_ms(FLOW_BALANCE_BAR_WIDTH_FRACTION, index)
        slot_hours = axis.slot_duration(index).total_seconds() / 3600.0
        cumulative = 0.0
        for consumer, column in pairs:
            raw_kw = _safe_float(row.get(column))
            if raw_kw <= 1e-9:
                continue
            if raw_kw * slot_hours < _GHOST_MIN_KWH:
                continue
            nominal = _safe_float(consumer.get("nominal_power_kw"))
            # Matched-baseline energy can concentrate into few slots above nominal
            # (shape-preserving scale). Ghost outlines are capped for chart realism.
            kw = min(raw_kw, nominal) if nominal > 0 else raw_kw
            bucket = _ghost_bucket_for(buckets, consumer, column)
            bucket["x"].append(x_val)
            bucket["y"].append(-kw)
            bucket["base"].append(-cumulative)
            bucket["customdata"].append((time_label, kw, bucket["label"]))
            bucket["widths"].append(bar_width_ms)
            cumulative += kw
    return buckets


def _ghost_bucket_for(
    buckets: dict[str, dict[str, list[Any]]],
    consumer: Mapping[str, Any],
    column: str,
) -> dict[str, Any]:
    cid = str(consumer.get("id", "")) or column
    return buckets.setdefault(
        cid,
        {
            "label": str(consumer.get("name", consumer.get("id", column))),
            "color": flex_bar_chart_color(consumer),
            "x": [],
            "y": [],
            "base": [],
            "customdata": [],
            "widths": [],
        },
    )


def _add_ghost_bucket_traces(
    fig: go.Figure,
    buckets: dict[str, dict[str, list[Any]]],
) -> None:
    legend_shown = False
    for bucket in buckets.values():
        if not bucket["x"]:
            continue
        showlegend = not legend_shown
        legend_shown = True
        fig.add_trace(
            go.Bar(
                x=bucket["x"],
                y=bucket["y"],
                base=bucket["base"],
                width=bucket["widths"],
                name="Original-Schedule",
                legendgroup="ghost_bl_ziel",
                showlegend=showlegend,
                marker=dict(
                    color="rgba(0,0,0,0)",
                    line=dict(color=bucket["color"], width=_GHOST_LINE_WIDTH),
                ),
                opacity=1.0,
                customdata=bucket["customdata"],
                hovertemplate=(
                    "Uhrzeit: %{customdata[0]}<br>Original-Schedule %{customdata[2]}: "
                    "%{customdata[1]:.2f} kW<extra></extra>"
                ),
            )
        )

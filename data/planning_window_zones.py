"""UI chart zone builders for S-2 planning windows."""
from __future__ import annotations

from datetime import datetime

from ui.chart_colors import CHART_ZONE_FORECAST_FILL, CHART_ZONE_HISTORY_FILL

from data.planning_window import (
    UiChartWindow,
    UiChartZone,
    UiChartZones,
    _clip_zone_end,
    first_extrapolated_slot,
    history_log_end_exclusive,
    slot_index_at_or_before,
)


def ui_chart_zone_indices(
    now: datetime,
    chart: UiChartWindow,
    sim_rows: list[dict] | None = None,
    *,
    is_live_segment: bool = True,
    slot_datetimes: tuple[datetime, ...] | None = None,
) -> tuple[int, int, int]:
    """
    Grenz-Indizes (inkl.) für Plotly-vrect im Chart.

    ``slot_datetimes``: Display-Slots (15-min/1-h gemischt); Default ``chart.slot_datetimes``.
    ``is_live_segment``: False bei vergangenen SA-Zyklen — volle Grauzone.

    Returns: (history_end, neutral_end, last_index)
    """
    slots = slot_datetimes if slot_datetimes is not None else chart.slot_datetimes
    zones = ui_chart_zones(
        now,
        chart,
        sim_rows=sim_rows,
        is_live_segment=is_live_segment,
        slot_datetimes=slots,
    )
    history_end = slot_index_at_or_before(slots, zones.history.end)
    neutral_end = slot_index_at_or_before(slots, zones.live_plan.end)
    return history_end, neutral_end, len(slots) - 1


def _make_ui_chart_zones(
    chart: UiChartWindow,
    *,
    history_end: datetime,
    neutral_end: datetime,
    green_start: datetime,
    green_color: str | None,
) -> UiChartZones:
    gray_color = CHART_ZONE_HISTORY_FILL
    return UiChartZones(
        history=UiChartZone(
            label="Vergangenheit",
            start=chart.start,
            end=history_end,
            fill_color=gray_color if history_end > chart.start else None,
        ),
        live_plan=UiChartZone(
            label="Aktuell/Plan",
            start=history_end,
            end=neutral_end,
            fill_color=None,
        ),
        forecast=UiChartZone(
            label="Vorausschau",
            start=green_start,
            end=chart.end,
            fill_color=green_color,
        ),
    )


def _sa0_sa1_live_bounds(
    now: datetime,
    chart: UiChartWindow,
    sim_rows: list[dict] | None,
    slot_datetimes: tuple[datetime, ...],
) -> tuple[datetime, datetime, datetime, str | None]:
    extrapolated = first_extrapolated_slot(slot_datetimes, sim_rows)
    green_color: str | None = CHART_ZONE_FORECAST_FILL
    if extrapolated is not None:
        green_start = extrapolated
    else:
        green_start = chart.end
        green_color = None
    neutral_end = _clip_zone_end(chart.start, chart.end, green_start)
    history_end = history_log_end_exclusive(now, chart)
    if history_end < chart.start:
        history_end = chart.start
    if neutral_end < history_end:
        neutral_end = history_end
    if green_start < neutral_end:
        green_start = neutral_end
    return history_end, neutral_end, green_start, green_color


def _ui_chart_zones_sa0_sa1(
    now: datetime,
    chart: UiChartWindow,
    sim_rows: list[dict] | None,
    *,
    is_live_segment: bool,
    slot_datetimes: tuple[datetime, ...],
) -> UiChartZones:
    """Segment SA₀→SA₁: grau / neutral / grün (Vergangenheit ab SA₀)."""
    if not is_live_segment:
        return _make_ui_chart_zones(
            chart,
            history_end=chart.end,
            neutral_end=chart.end,
            green_start=chart.end,
            green_color=None,
        )
    history_end, neutral_end, green_start, green_color = _sa0_sa1_live_bounds(
        now, chart, sim_rows, slot_datetimes
    )
    return _make_ui_chart_zones(
        chart,
        history_end=history_end,
        neutral_end=neutral_end,
        green_start=green_start,
        green_color=green_color,
    )


def _ui_chart_zones_sa1_sa2(
    chart: UiChartWindow,
    sim_rows: list[dict] | None,
    *,
    slot_datetimes: tuple[datetime, ...],
) -> UiChartZones:
    """Segment SA₁→SA₂: nur neutral und grün (keine Vergangenheit)."""
    extrapolated = first_extrapolated_slot(slot_datetimes, sim_rows)
    green_color = CHART_ZONE_FORECAST_FILL
    if extrapolated is not None:
        green_start = extrapolated
    else:
        green_start = chart.end
        green_color = None
    neutral_end = _clip_zone_end(chart.start, chart.end, green_start)
    if green_start < neutral_end:
        green_start = neutral_end
    return UiChartZones(
        history=UiChartZone(
            label="Vergangenheit",
            start=chart.start,
            end=chart.start,
            fill_color=None,
        ),
        live_plan=UiChartZone(
            label="Plan",
            start=chart.start,
            end=neutral_end,
            fill_color=None,
        ),
        forecast=UiChartZone(
            label="Vorausschau (gespiegelte Preise)",
            start=green_start,
            end=chart.end,
            fill_color=green_color,
        ),
    )


def ui_chart_zones(
    now: datetime,
    chart: UiChartWindow,
    sim_rows: list[dict] | None = None,
    *,
    is_live_segment: bool = True,
    slot_datetimes: tuple[datetime, ...] | None = None,
) -> UiChartZones:
    """
    Hintergrundzonen für den S-2-Chart.

    SA₀→SA₁ / SA₀→SA₂: grau (Vergangenheit) · neutral · grün (extrapolierte Preise)
    SA₁→SA₂ (segment): neutral · grün (nur gespiegelte/extrapolierte Preise)

    ``slot_datetimes``: Display-Slots (15-min/1-h gemischt); Default ``chart.slot_datetimes``.
    ``is_live_segment``: False nur wenn das Fenster vollständig vor der Log-Grenze liegt
    (volle Grauzone). Bei Desktop-Span SA₀→SA₂ und ``now`` im Fenster immer anhand von
    ``now`` clippen — auch bei cycle_offset > 0.
    """
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    slots = slot_datetimes if slot_datetimes is not None else chart.slot_datetimes
    if chart.span == "segment" and chart.segment_index == 1:
        return _ui_chart_zones_sa1_sa2(chart, sim_rows, slot_datetimes=slots)
    return _ui_chart_zones_sa0_sa1(
        now,
        chart,
        sim_rows,
        is_live_segment=is_live_segment,
        slot_datetimes=slots,
    )

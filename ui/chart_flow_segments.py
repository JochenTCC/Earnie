"""Flow-balance segment/slot builders (Chart 1)."""
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
    consumer_column_name,
    consumer_immediate_charge_column_name,
    consumer_immediate_charge_hover_label,
    consumer_pv_follow_column_name,
)

from ui.chart_consumer_stack import _chart_flex_consumers
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

KIND_BATTERY_CHARGE = KIND_BATTERY_CHARGE_PV

KIND_BATTERY_DISCHARGE_BALANCE = KIND_BATTERY_DISCHARGE_LOAD

KIND_BATTERY_DISCHARGE_OFFSET = KIND_BATTERY_DISCHARGE_LOAD

KIND_GRID_EXPORT = KIND_EXPORT_PV

KIND_SURPLUS_BALANCE = KIND_EXPORT_PV

KIND_SURPLUS_OFFSET = KIND_EXPORT_PV

Direction = Literal["up", "down"]

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

def _primary_up_segments(pv: float, grid_import: float) -> list[FlowBalanceSegment]:
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
    return up_segments


def _primary_down_segments(
    row: Mapping[str, Any],
    baseload: float,
    flex_pairs: Sequence[tuple[Mapping[str, Any], str]],
) -> list[FlowBalanceSegment]:
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
    return down_segments


def _assemble_balanced_slot(
    powers: dict[str, float],
    up_segments: list[FlowBalanceSegment],
    down_segments: list[FlowBalanceSegment],
) -> FlowBalanceSlot:
    up_external = powers["pv"] + powers["grid_import"]
    down_primary = sum(segment.kw for segment in down_segments)
    offset_kw = up_external - down_primary - powers["battery_charge"]
    flows = allocate_slot_flows(
        pv=powers["pv"],
        load_kw=powers["load_kw"],
        battery_charge=powers["battery_charge"],
        battery_discharge=powers["battery_discharge"],
        grid_import=powers["grid_import"],
        grid_export=powers["grid_export"],
    )
    surplus_export_pv = 0.0
    if powers["grid_export"] < 1e-9 and offset_kw > 1e-9:
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
        battery_discharge_kw=powers["battery_discharge"],
    )


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
    flex_pairs = list(flex_consumers) if flex_consumers is not None else _default_flex_pairs(row)
    return _assemble_balanced_slot(
        {
            "pv": pv,
            "load_kw": load_kw,
            "grid_import": grid_import,
            "grid_export": grid_export,
            "battery_charge": battery_charge,
            "battery_discharge": battery_discharge,
        },
        _primary_up_segments(pv, grid_import),
        _primary_down_segments(row, baseload, flex_pairs),
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

def _default_flex_pairs(row: Mapping[str, Any]) -> list[tuple[dict, str]]:
    pairs: list[tuple[dict, str]] = []
    for consumer in _chart_flex_consumers():
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
        label = consumer_immediate_charge_hover_label(consumer)
        lines.append(f"{label}: {_safe_int_flag(row.get(immediate_col, 0))}")
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

def _flex_kw_pairs(row: Mapping[str, Any]) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    for consumer, column in _default_flex_pairs(row):
        pairs.append((column, _safe_float(row.get(column))))
    return pairs

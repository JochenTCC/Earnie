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

from ui.chart_consumer_stack import _chart_flex_consumers  # noqa: F401
from ui.chart_colors import (  # noqa: F401
    COLOR_BASELOAD,
    COLOR_BATTERY,
    COLOR_GRID_IMPORT,
    COLOR_PV,
    MUTED_BATTERY_CHARGE_GRID,
    MUTED_BATTERY_CHARGE_PV,
    MUTED_BATTERY_EXPORT,
    MUTED_BATTERY_LOAD,
    MUTED_EXPORT_PV,
)
from ui.chart_flow_segments import (  # noqa: F401
    FLOW_BALANCE_BAR_WIDTH_FRACTION,
    KIND_BASELOAD,
    KIND_BATTERY_CHARGE,
    KIND_BATTERY_CHARGE_GRID,
    KIND_BATTERY_CHARGE_PV,
    KIND_BATTERY_DISCHARGE_BALANCE,
    KIND_BATTERY_DISCHARGE_LOAD,
    KIND_BATTERY_DISCHARGE_OFFSET,
    KIND_EXPORT_BATTERY,
    KIND_EXPORT_PV,
    KIND_FLEX,
    KIND_GRID_EXPORT,
    KIND_GRID_IMPORT,
    KIND_PV,
    KIND_SURPLUS_BALANCE,
    KIND_SURPLUS_OFFSET,
    Direction,
    FlowBalanceSegment,
    FlowBalanceSlot,
    FlowBalanceTraceSpec,
    build_flow_balance_segments,
    build_flow_balance_slots_from_df,
    energy_balance_residual_kw,
)
from ui.chart_flow_traces import (  # noqa: F401
    add_flow_balance_traces,
    add_matched_flex_ghost_traces,
    flow_balance_plotly_trace_specs,
    flow_balance_plotly_traces,
)

# Rückwärtskompatibilität (Tests)
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

# Re-Exports für API-Stabilität (from ui.chart_flow_balance import ...)
__all__ = [
    "COLOR_BASELOAD",
    "COLOR_BATTERY",
    "COLOR_GRID_IMPORT",
    "COLOR_PV",
    "FLOW_BALANCE_BAR_WIDTH_FRACTION",
    "FLOW_BALANCE_TRACE_ORDER",
    "KIND_BASELOAD",
    "KIND_BATTERY_CHARGE",
    "KIND_BATTERY_CHARGE_GRID",
    "KIND_BATTERY_CHARGE_PV",
    "KIND_BATTERY_DISCHARGE_BALANCE",
    "KIND_BATTERY_DISCHARGE_LOAD",
    "KIND_BATTERY_DISCHARGE_OFFSET",
    "KIND_EXPORT_BATTERY",
    "KIND_EXPORT_PV",
    "KIND_FLEX",
    "KIND_GRID_EXPORT",
    "KIND_GRID_IMPORT",
    "KIND_PV",
    "KIND_SURPLUS_BALANCE",
    "KIND_SURPLUS_OFFSET",
    "MUTED_BATTERY_CHARGE_GRID",
    "MUTED_BATTERY_CHARGE_PV",
    "MUTED_BATTERY_EXPORT",
    "MUTED_BATTERY_LOAD",
    "MUTED_EXPORT_PV",
    "Direction",
    "FlowBalanceSegment",
    "FlowBalanceSlot",
    "FlowBalanceTraceSpec",
    "_chart_flex_consumers",
    "add_flow_balance_traces",
    "add_matched_flex_ghost_traces",
    "build_flow_balance_segments",
    "build_flow_balance_slots_from_df",
    "energy_balance_residual_kw",
    "flow_balance_plotly_trace_specs",
    "flow_balance_plotly_traces",
]

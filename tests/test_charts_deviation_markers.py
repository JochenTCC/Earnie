"""Tests für Soll/Ist-Marker in Chart 1 (Epic Soll-Ist P3)."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer.deviation_eval import DeviationEvent
from ui.charts import ChartSlotAxis, build_deviation_marker_traces


def _event(category: str, symbol: str, color: str, message: str) -> DeviationEvent:
    return DeviationEvent(
        rule_id="test_rule",
        category=category,
        scope="eauto",
        message=message,
        label={"warning": "Warnung", "error": "Fehler"}[category],
        symbol=symbol,
        color=color,
    )


def test_build_deviation_marker_traces_empty_when_no_events():
    df = pd.DataFrame(
        {
            "slot_datetime": [datetime(2026, 7, 5, 10, 0, tzinfo=ZoneInfo("Europe/Vienna"))],
            "Uhrzeit": ["10:00"],
        }
    )
    axis = ChartSlotAxis.from_dataframe(df)
    traces = build_deviation_marker_traces(axis, ((),), power_ymax=2.0)
    assert traces == []


def test_build_deviation_marker_traces_creates_scatter_with_hover():
    slots = (
        datetime(2026, 7, 5, 10, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        datetime(2026, 7, 5, 10, 15, tzinfo=ZoneInfo("Europe/Vienna")),
    )
    df = pd.DataFrame({"slot_datetime": list(slots), "Uhrzeit": ["10:00", "10:15"]})
    axis = ChartSlotAxis.from_dataframe(df)
    events = (
        (),
        (
            _event(
                "error",
                "octagon",
                "#c0392b",
                "E-Auto: Soll 3.50 kW, Ist 0.00 kW",
            ),
        ),
    )
    traces = build_deviation_marker_traces(axis, events, power_ymax=4.0)
    assert len(traces) == 1
    trace = traces[0]
    assert isinstance(trace, go.Scatter)
    assert trace.mode == "markers"
    assert trace.marker.symbol == "octagon"
    assert "E-Auto" in trace.hovertemplate
    assert trace.y[0] > 4.0


def test_build_deviation_marker_traces_stacks_multiple_events():
    slots = (datetime(2026, 7, 5, 10, 0, tzinfo=ZoneInfo("Europe/Vienna")),)
    df = pd.DataFrame({"slot_datetime": list(slots), "Uhrzeit": ["10:00"]})
    axis = ChartSlotAxis.from_dataframe(df)
    slot_events = (
        (
            _event("warning", "diamond", "#e67e22", "Warnung A"),
            _event("error", "octagon", "#c0392b", "Fehler B"),
        ),
    )
    traces = build_deviation_marker_traces(axis, slot_events, power_ymax=2.0)
    assert len(traces) == 2
    assert traces[1].y[0] > traces[0].y[0]


def test_build_deviation_marker_traces_length_mismatch_returns_empty():
    df = pd.DataFrame(
        {
            "slot_datetime": [datetime(2026, 7, 5, 10, 0, tzinfo=ZoneInfo("Europe/Vienna"))],
            "Uhrzeit": ["10:00"],
        }
    )
    axis = ChartSlotAxis.from_dataframe(df)
    traces = build_deviation_marker_traces(axis, ((), ()), power_ymax=2.0)
    assert traces == []

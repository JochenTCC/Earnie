"""Zeitbasis-Verlaufskurven Chart 1 + Chart 2 (gemeinsame ChartSlotAxis)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from ui.charts import (
    ChartSlotAxis,
    _COLOR_SOC,
    _LINE_ANCHOR_SLOT_CENTER,
    _LINE_ANCHOR_SLOT_START,
    add_cumulative_s2_split_traces,
    add_optimized_soc_trace,
    add_power_traces,
    get_bar_colors,
)

_TZ = ZoneInfo("Europe/Vienna")


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 5, hour, minute, tzinfo=_TZ)


def _mixed_slots() -> list[datetime]:
    quarters = [_dt(14, 0), _dt(14, 15), _dt(14, 30), _dt(14, 45)]
    hours = [_dt(h, 0) for h in (15, 16, 17)]
    return quarters + hours


def _trace_x_vienna(raw_x) -> datetime:
    ts = pd.Timestamp(raw_x)
    if ts.tzinfo is None:
        return ts.tz_localize(_TZ).to_pydatetime()
    return ts.tz_convert(_TZ).to_pydatetime()


def _slot_start(axis: ChartSlotAxis, index: int) -> datetime:
    return axis.at(index, _LINE_ANCHOR_SLOT_START).iloc[0].to_pydatetime()


def _slot_center(axis: ChartSlotAxis, index: int) -> datetime:
    return axis.at(index, _LINE_ANCHOR_SLOT_CENTER).iloc[0].to_pydatetime()


def _points_at_y(trace, y_value: float) -> list[tuple[datetime, float]]:
    return [
        (_trace_x_vienna(x), float(y))
        for x, y in zip(trace.x, trace.y)
        if float(y) == float(y_value)
    ]


def _build_chart1_df(slots: list[datetime]) -> pd.DataFrame:
    rows = []
    for index, slot in enumerate(slots):
        rows.append({
            "slot_datetime": slot,
            "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
            "PV-Prognose (kW)": 1.0 + index * 0.1,
            "Verbrauch-Prognose (kW)": 2.0 + index * 0.2,
            "Netzbezug (kW)": 0.5 + index * 0.05,
            "Geplante Batterie-Aktion (kW)": 0.0,
            "Steuerbefehl": "IDLE",
            "Simulierter SoC (%)": 40.0 + index,
            "Preis extrapoliert": index >= 5,
        })
    return pd.DataFrame(rows)


def test_chart1_has_no_verbrauch_or_netz_line_traces():
    slots = _mixed_slots()
    df = _build_chart1_df(slots)
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_power_traces(fig, df, get_bar_colors(df), axis)
    trace_names = {trace.name for trace in fig.data}
    assert "Verbrauch" not in trace_names
    assert "Netz" not in trace_names


def test_chart1_pv_uses_slot_center_anchor():
    slots = _mixed_slots()
    df = _build_chart1_df(slots)
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_power_traces(fig, df, get_bar_colors(df), axis)
    pv = next(t for t in fig.data if t.name == "PV")

    for index, slot in enumerate(slots):
        pv_value = float(df.iloc[index]["PV-Prognose (kW)"])
        expected_start = _slot_start(axis, index)
        expected_center = _slot_center(axis, index)
        pv_points = _points_at_y(pv, pv_value)
        assert expected_center in [p[0] for p in pv_points], f"PV Slot {slot}"
        assert expected_start not in [p[0] for p in pv_points], (
            f"PV bewusst Slotmitte, nicht Beginn ({slot})"
        )


def test_chart1_pv_uses_smooth_line_not_hv_steps():
    slots = _mixed_slots()[:3]
    df = _build_chart1_df(slots)
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_power_traces(fig, df, get_bar_colors(df), axis)
    pv = next(t for t in fig.data if t.name == "PV")
    assert getattr(pv.line, "shape", None) in (None, "linear")


def test_chart1_pv_center_anchor_avoids_early_morning_ramp():
    """Stündliche PV=0 bis 06:00 — Mitte-Anker: kein sichtbarer Anstieg vor 05:30."""
    slots = [
        datetime(2026, 7, 6, hour, 0, tzinfo=_TZ) for hour in (5, 6, 7)
    ]
    df = pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "PV-Prognose (kW)": [0.0, 0.105, 0.268],
        "Verbrauch-Prognose (kW)": [0.3, 0.3, 0.3],
        "Geplante Batterie-Aktion (kW)": [0.0, 0.0, 0.0],
        "Netzbezug (kW)": [0.0, 0.0, 0.0],
        "Steuerbefehl": "IDLE",
        "Simulierter SoC (%)": [10.0, 10.0, 10.0],
        "Preis extrapoliert": [False, False, False],
    })
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_power_traces(fig, df, get_bar_colors(df), axis)
    pv = next(t for t in fig.data if t.name == "PV")
    sunrise = datetime(2026, 7, 6, 5, 31, tzinfo=_TZ)

    def interp_at(moment: datetime) -> float:
        xs = [_trace_x_vienna(x) for x in pv.x]
        ys = [float(y) for y in pv.y]
        for i in range(len(xs) - 1):
            if xs[i] <= moment <= xs[i + 1]:
                frac = (moment - xs[i]) / (xs[i + 1] - xs[i])
                return ys[i] + float(frac) * (ys[i + 1] - ys[i])
        return float("nan")

    assert _slot_center(axis, 0) in [p[0] for p in _points_at_y(pv, 0.0)]
    assert interp_at(sunrise) < 0.01


def test_chart1_soc_uses_slot_start_anchor():
    slots = _mixed_slots()
    df = _build_chart1_df(slots)
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_optimized_soc_trace(fig, df, axis)
    soc = next(t for t in fig.data if t.name == "SoC")
    assert soc.line.color == _COLOR_SOC
    for index, slot in enumerate(slots):
        soc_value = float(df.iloc[index]["Simulierter SoC (%)"])
        expected = _slot_start(axis, index)
        soc_points = _points_at_y(soc, soc_value)
        assert expected in [p[0] for p in soc_points], f"SoC Slot {slot}"


def test_chart2_cumulative_traces_use_slot_start_anchor():
    slots = _mixed_slots()
    n = len(slots)
    split = 4
    uhrzeit = pd.Series(slot.strftime("%d.%m. %H:%M") for slot in slots)
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": slots}))
    increments = [0.1 * (index + 1) for index in range(n)]
    fig = go.Figure()
    add_cumulative_s2_split_traces(
        fig,
        uhrzeit,
        axis,
        history_slot_count=split,
        slot_actual_cost_euro=increments,
        slot_actual_consumption_kwh=increments,
        hourly_matched_baseline_cost_euro=[1.0] * n,
        hourly_optimized_cost_euro=[0.8] * n,
        hourly_matched_baseline_consumption_kwh=[2.0] * n,
        hourly_optimized_consumption_kwh=[1.5] * n,
    )
    history_cost = next(t for t in fig.data if t.name == "Kosten (Ist bisher)")
    for index in range(split):
        expected = _slot_start(axis, index)
        y_value = sum(increments[: index + 1])
        points = _points_at_y(history_cost, y_value)
        assert expected in [p[0] for p in points], f"Ist-Kosten Slot {slots[index]}"

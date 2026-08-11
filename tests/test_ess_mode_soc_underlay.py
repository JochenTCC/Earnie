"""Chart 1: ESS-mode SoC underlay (hold / Zwangsladen / Zwangsentladen)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from optimizer import battery as bat
from ui.chart_soc import (
    ESS_UNDERLAY_CHARGE,
    ESS_UNDERLAY_DISCHARGE,
    ESS_UNDERLAY_HOLD,
    _ESS_UNDERLAY_TRACE_NAMES,
    add_ess_mode_soc_underlay_traces,
    add_optimized_soc_trace,
    classify_ess_soc_underlay,
)
from ui.charts import ChartSlotAxis, build_power_soc_chart_figure

_TZ = ZoneInfo("Europe/Vienna")
_BATTERY = {"max_power_kw": 5.0, "battery_capacity_kwh": 10.0, "efficiency": 0.95,
            "min_soc": 10.0, "max_soc": 90.0}


def _slot(hour: int) -> datetime:
    return datetime(2026, 7, 6, hour, 0, tzinfo=_TZ)


def _chart_df(commands: list[str], soc_values: list[float]) -> pd.DataFrame:
    slots = [_slot(h) for h in range(len(commands))]
    return pd.DataFrame({
        "slot_datetime": slots,
        "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
        "PV-Prognose (kW)": [0.0] * len(slots),
        "Verbrauch-Prognose (kW)": [1.0] * len(slots),
        "Netzbezug (kW)": [0.5] * len(slots),
        "Geplante Batterie-Aktion (kW)": [0.0] * len(slots),
        "Steuerbefehl": commands,
        "Simulierter SoC (%)": soc_values,
        "Preis extrapoliert": [False] * len(slots),
    })


def test_classify_automatik_has_no_underlay():
    cmd = bat.steuerbefehl_for_mode(bat.MODE_AUTOMATIK, 0.0)
    assert classify_ess_soc_underlay(cmd, 5.0) is None


def test_classify_entladesperre_is_hold():
    cmd = bat.steuerbefehl_for_mode(bat.MODE_ENTLADESPERRE, 0.0)
    assert classify_ess_soc_underlay(cmd, 5.0) == ESS_UNDERLAY_HOLD


def test_classify_zwangsladen_near_zero_is_hold():
    cmd = bat.steuerbefehl_for_mode(bat.MODE_ZWANGS_LADEN, 0.1)
    assert classify_ess_soc_underlay(cmd, 5.0) == ESS_UNDERLAY_HOLD


def test_classify_zwangsladen_above_threshold_is_charge():
    cmd = bat.steuerbefehl_for_mode(bat.MODE_ZWANGS_LADEN, 1.0)
    assert classify_ess_soc_underlay(cmd, 5.0) == ESS_UNDERLAY_CHARGE


def test_classify_zwangsentladen_near_zero_is_hold():
    cmd = bat.steuerbefehl_for_mode(bat.MODE_ZWANGS_ENTLADEN, 0.1)
    assert classify_ess_soc_underlay(cmd, 5.0) == ESS_UNDERLAY_HOLD


def test_classify_zwangsentladen_above_threshold_is_discharge():
    cmd = bat.steuerbefehl_for_mode(bat.MODE_ZWANGS_ENTLADEN, 1.0)
    assert classify_ess_soc_underlay(cmd, 5.0) == ESS_UNDERLAY_DISCHARGE


def test_automatik_draws_no_underlay():
    commands = [bat.steuerbefehl_for_mode(bat.MODE_AUTOMATIK, 0.0)]
    df = _chart_df(commands, [50.0])
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_ess_mode_soc_underlay_traces(fig, df, axis, battery_params=_BATTERY)
    names = {_ESS_UNDERLAY_TRACE_NAMES[k] for k in (
        ESS_UNDERLAY_HOLD, ESS_UNDERLAY_CHARGE, ESS_UNDERLAY_DISCHARGE
    )}
    assert not any(trace.name in names for trace in fig.data)


def test_entladesperre_underlay_no_legacy_bar():
    commands = [bat.steuerbefehl_for_mode(bat.MODE_ENTLADESPERRE, 0.0)]
    df = _chart_df(commands, [60.0])
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_ess_mode_soc_underlay_traces(fig, df, axis, battery_params=_BATTERY)
    assert any(
        trace.name == _ESS_UNDERLAY_TRACE_NAMES[ESS_UNDERLAY_HOLD]
        for trace in fig.data
    )
    assert not any(trace.name == "Entladesperre" for trace in fig.data)


def test_underlay_drawn_before_soc_trace():
    commands = [bat.steuerbefehl_for_mode(bat.MODE_ENTLADESPERRE, 0.0)]
    df = _chart_df(commands, [42.0])
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_ess_mode_soc_underlay_traces(fig, df, axis, battery_params=_BATTERY)
    add_optimized_soc_trace(fig, df, axis, battery_params=_BATTERY)
    assert fig.data[0].name == _ESS_UNDERLAY_TRACE_NAMES[ESS_UNDERLAY_HOLD]
    assert fig.data[-1].name == "SoC"


def test_zwangsladen_and_zwangsentladen_underlay_colors():
    commands = [
        bat.steuerbefehl_for_mode(bat.MODE_ZWANGS_LADEN, 1.0),
        bat.steuerbefehl_for_mode(bat.MODE_ZWANGS_ENTLADEN, 1.0),
    ]
    df = _chart_df(commands, [55.0, 50.0])
    axis = ChartSlotAxis.from_dataframe(df)
    fig = go.Figure()
    add_ess_mode_soc_underlay_traces(fig, df, axis, battery_params=_BATTERY)
    names = {trace.name for trace in fig.data}
    assert _ESS_UNDERLAY_TRACE_NAMES[ESS_UNDERLAY_CHARGE] in names
    assert _ESS_UNDERLAY_TRACE_NAMES[ESS_UNDERLAY_DISCHARGE] in names


def test_build_power_soc_chart_includes_underlay():
    commands = [
        bat.steuerbefehl_for_mode(bat.MODE_AUTOMATIK, 0.0),
        bat.steuerbefehl_for_mode(bat.MODE_ENTLADESPERRE, 0.0),
    ]
    df = _chart_df(commands, [55.0, 58.0])
    fig = build_power_soc_chart_figure(
        df, show_baseline_soc=False, battery_params=_BATTERY,
    )
    assert any(
        trace.name == _ESS_UNDERLAY_TRACE_NAMES[ESS_UNDERLAY_HOLD]
        for trace in fig.data
    )
    assert not any(trace.name == "Entladesperre" for trace in fig.data)

"""Tests for Live Monitor SOC plausibility: BL Ziel SOC, no flex ghost outlines."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import pytest

from runtime_store.live_display_loader import savings_info_from_snapshot
from runtime_store.live_optimization_debug import build_debug_payload
from ui.chart_slot_axis import ChartSlotAxis
from ui.charts import build_power_soc_chart_figure
from ui.history_navigation import s2_zone_help_text

_TZ = ZoneInfo("Europe/Vienna")


def _slot_df(
    *,
    length: int = 4,
    soc: float = 40.0,
    flex_kw: float = 0.0,
) -> pd.DataFrame:
    start = datetime(2026, 7, 6, 10, 0, tzinfo=_TZ)
    slots = [start + timedelta(hours=index) for index in range(length)]
    return pd.DataFrame(
        {
            "slot_datetime": slots,
            "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
            "PV-Prognose (kW)": [2.0] * length,
            "Verbrauch-Prognose (kW)": [1.0] * length,
            "Geplante Batterie-Aktion (kW)": [0.0] * length,
            "Netzbezug (kW)": [0.0] * length,
            "Steuerbefehl": ["IDLE"] * length,
            "Simulierter SoC (%)": [soc + index for index in range(length)],
            "E-Auto (kW)": [flex_kw] * length,
            "Preis extrapoliert": [False] * length,
        }
    )


def test_build_debug_payload_persists_baseline_same_flex_rows():
    same_flex = [{"Simulierter SoC (%)": 55.0, "hour": 12}]
    payload = build_debug_payload(
        {"baseline_same_flex_rows": same_flex, "applied_targets": []},
        [{"hour": 12}],
        [{"hour": 12}],
        kind="live",
        initial_soc=50.0,
        matched_baseline_rows=[{"hour": 12}],
        baseline_same_flex_rows=same_flex,
        quarter_hour_slot="2026-07-06T12:00",
        sync_reason="test",
    )
    assert payload["baseline_same_flex_rows"] == same_flex


def test_savings_info_from_snapshot_loads_same_flex_rows():
    snapshot = {
        "savings": {"optimized_cost_euro": 1.0},
        "simulation_rows": [{"hour": 10}],
        "baseline_rows": [],
        "matched_baseline_rows": [{"hour": 10}],
        "baseline_same_flex_rows": [{"Simulierter SoC (%)": 42.0}],
        "applied_targets": [],
        "energy_comparison": [],
    }
    info = savings_info_from_snapshot(snapshot)
    assert info["baseline_same_flex_rows"] == [{"Simulierter SoC (%)": 42.0}]


def test_savings_info_from_snapshot_missing_same_flex_is_empty():
    snapshot = {
        "savings": {},
        "simulation_rows": [{"hour": 10}],
        "baseline_rows": [],
        "matched_baseline_rows": [],
    }
    info = savings_info_from_snapshot(snapshot)
    assert info["baseline_same_flex_rows"] == []


def test_chart_has_bl_ziel_not_opt_last_when_plausibility_enabled():
    opt = _slot_df(soc=50.0)
    matched = _slot_df(soc=45.0)
    fig = build_power_soc_chart_figure(
        opt,
        matched_baseline_df=matched,
        show_soc_plausibility=True,
        history_slot_count=1,
        chart_now=opt["slot_datetime"].iloc[1].to_pydatetime(),
    )
    names = {trace.name for trace in fig.data if isinstance(trace, go.Scatter)}
    assert "SoC" in names
    assert "SoC BL Ziel" in names
    assert "SoC bei Opt-Last" not in names


def test_live_chart_draws_no_original_schedule_outlines():
    """Live Chart 1 shows only the optimized flex; matched-baseline flex gets no outline."""
    opt = _slot_df(soc=50.0)
    matched = _slot_df(soc=45.0, flex_kw=3.5)
    fig = build_power_soc_chart_figure(
        opt,
        matched_baseline_df=matched,
        show_soc_plausibility=True,
        history_slot_count=1,
        chart_now=opt["slot_datetime"].iloc[1].to_pydatetime(),
    )
    assert not [trace for trace in fig.data if trace.name == "Original-Schedule"]
    assert not [trace for trace in fig.data if getattr(trace, "legendgroup", None) == "ghost_bl_ziel"]


def test_s2_zone_help_includes_soc_plausibility_when_requested():
    plain = s2_zone_help_text()
    assert "SoC-Plausibilität" not in plain
    rich = s2_zone_help_text(include_soc_plausibility=True)
    assert "SoC BL Ziel" in rich
    assert "SoC bei Opt-Last" not in rich
    assert "Original-Schedule" not in rich

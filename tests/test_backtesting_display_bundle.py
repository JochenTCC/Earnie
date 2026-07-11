"""Tests für Backtesting-DisplayBundle-Adapter (1.25.f)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import pytest

from simulation import engine
from simulation.backtesting_snapshots import build_window_snapshot, write_window_snapshots_jsonl
from simulation.engine import PlausibilityResult, run_simulation
from simulation.horizon_mode import FIXED_24H, SUNSET_WINDOW
from ui.backtesting_display_bundle import (
    VIEW_MODE_24H,
    VIEW_MODE_SUNSET,
    build_backtesting_display_bundle,
    format_backtesting_window_range,
    load_backtesting_display_bundle,
    log_supports_sunset_chart_view,
)
from ui.backtesting_deviation_list import _format_deviation_window, _resolve_chart_view
from ui.chart_decorations import _chart_range_start
from ui.chart_slot_axis import ChartSlotAxis, _chart_xaxis_config
from tests.fixtures.backtesting_fixtures import (
    SOC_CHAIN_END_DAY,
    SOC_CHAIN_START_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")


def _force_plausibility_failure(monkeypatch) -> None:
    original = engine.validate_window_consumption

    def _always_fail(chart_rows, meta):
        result = original(chart_rows, meta)
        return PlausibilityResult(
            window_end=result.window_end,
            historical_kwh=result.historical_kwh,
            optimized_kwh=result.optimized_kwh,
            diff_kwh=result.diff_kwh,
            ok=False,
            historical_baseload_kwh=result.historical_baseload_kwh,
            optimized_baseload_kwh=result.optimized_baseload_kwh,
            historical_flex_kwh=result.historical_flex_kwh,
            optimized_flex_kwh=result.optimized_flex_kwh,
            baseload_diff_kwh=result.baseload_diff_kwh,
            flex_diff_kwh=result.flex_diff_kwh,
        )

    monkeypatch.setattr(engine, "validate_window_consumption", _always_fail)


class TestBacktestingDisplayBundle:
    @pytest.fixture(autouse=True)
    def _fixtures(self, monkeypatch):
        with activate_backtesting_fixtures(monkeypatch):
            _force_plausibility_failure(monkeypatch)
            yield

    def _collect_snapshots(self, horizon_mode: str) -> list[dict]:
        cache = load_fixture_cache()
        scenario = fixture_scenario_params()
        prices = build_synthetic_prices_df(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
        )
        snapshots: list[dict] = []
        run_simulation(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
            scenario,
            prices,
            cache=cache,
            scenario_id="live",
            horizon_mode=horizon_mode,
            snapshot_collector=snapshots,
        )
        return snapshots

    def test_build_backtesting_display_bundle_has_chart_context(self):
        snapshots = self._collect_snapshots(FIXED_24H)
        bundle = build_backtesting_display_bundle(snapshots[0], view_mode=VIEW_MODE_24H)
        assert bundle.chart_context is not None
        assert bundle.battery_params is not None
        assert float(bundle.battery_params["battery_capacity_kwh"]) > 0
        assert not bundle.display_df.empty
        assert bundle.savings_view.get("hourly_optimized_cost_euro")
        assert "PV-Prognose (kW)" in bundle.display_df.columns
        assert bundle.chart_header_label is not None
        assert "24h Backtesting" in bundle.chart_header_label
        assert "SA" not in bundle.chart_header_label
        anchor = snapshots[0]["window_anchor"]
        planning_start = pd.Timestamp(anchor) - pd.Timedelta(hours=24)
        if planning_start.tzinfo is None:
            planning_start = planning_start.tz_localize("Europe/Vienna")
        anchor_ts = pd.Timestamp(anchor)
        if anchor_ts.tzinfo is None:
            anchor_ts = anchor_ts.tz_localize("Europe/Vienna")
        assert planning_start.strftime("%d.%m.%Y %H:%M") in bundle.chart_header_label
        assert anchor_ts.strftime("%d.%m.%Y %H:%M") in bundle.chart_header_label
        assert bundle.chart_context.chart_window.end == anchor_ts.to_pydatetime()
        assert bundle.chart_context.now == planning_start.to_pydatetime()
        assert len(bundle.display_df) == 24
        axis = ChartSlotAxis.from_dataframe(bundle.display_df)
        x0, x1 = _chart_xaxis_config(
            axis,
            range_start=_chart_range_start(bundle.chart_context.chart_window),
        )["range"]
        assert x0 == bundle.chart_context.chart_window.start
        assert x1 == anchor_ts.to_pydatetime()

    def test_build_backtesting_display_bundle_sunset_uses_full_rows(self):
        snapshots = self._collect_snapshots(SUNSET_WINDOW)
        snapshot = snapshots[0]
        assert len(snapshot["chart_rows_24h"]) == 24
        assert snapshot.get("chart_rows_full") is not None
        assert len(snapshot["chart_rows_full"]) > 24
        bundle_24h = build_backtesting_display_bundle(snapshot, view_mode=VIEW_MODE_24H)
        bundle_sunset = build_backtesting_display_bundle(
            snapshot,
            view_mode=VIEW_MODE_SUNSET,
            segment_index=0,
        )
        assert not bundle_24h.display_df.empty
        assert not bundle_sunset.display_df.empty
        assert bundle_sunset.chart_context is not None
        anchor = snapshot["window_anchor"]
        assert "Sunset Backtesting" in (bundle_sunset.chart_header_label or "")
        assert "(Live)" not in (bundle_sunset.chart_header_label or "")
        assert pd.Timestamp(anchor).strftime("%d.%m.%Y %H:%M") in (
            bundle_sunset.chart_header_label or ""
        )
        assert len(bundle_sunset.display_df) == len(
            bundle_sunset.chart_context.chart_window.slot_datetimes
        )
        planning_start = pd.Timestamp(anchor) - pd.Timedelta(hours=24)
        if planning_start.tzinfo is None:
            planning_start = planning_start.tz_localize("Europe/Vienna")
        assert bundle_sunset.chart_context.chart_window.start >= planning_start.to_pydatetime()
        snapshot_first = pd.Timestamp(snapshot["chart_rows_full"][0]["slot_datetime"])
        if snapshot_first.tzinfo is None:
            snapshot_first = snapshot_first.tz_localize("Europe/Vienna")
        assert bundle_sunset.chart_context.chart_window.start >= snapshot_first.to_pydatetime()


def test_soc_tail_y_uses_explicit_battery_params_when_live_capacity_zero(monkeypatch):
    from ui.chart_soc import _soc_tail_y_from_row

    monkeypatch.setattr(
        "ui.chart_soc.config.get_battery_params",
        lambda: {
            "battery_capacity_kwh": 0.0,
            "efficiency": 0.95,
            "min_soc": 10.0,
            "max_soc": 95.0,
            "max_power_kw": 5.0,
        },
    )
    row = pd.Series(
        {
            "Simulierter SoC (%)": 50.0,
            "Geplante Batterie-Aktion (kW)": 2.0,
        }
    )
    scenario_params = {
        "battery_capacity_kwh": 10.0,
        "efficiency": 0.95,
        "min_soc": 10.0,
        "max_soc": 95.0,
        "max_power_kw": 5.0,
    }
    tail_y = _soc_tail_y_from_row(row, battery_params=scenario_params)
    assert tail_y is not None
    assert tail_y > 50.0


def test_battery_params_from_snapshot_prefers_stored():
    from ui.backtesting_display_bundle import _battery_params_from_snapshot

    params = {
        "battery_capacity_kwh": 12.5,
        "min_soc": 10.0,
        "max_soc": 95.0,
        "max_power_kw": 5.0,
        "efficiency": 0.95,
    }
    resolved = _battery_params_from_snapshot({"battery_params": params, "scenario_id": "x"})
    assert resolved["battery_capacity_kwh"] == 12.5


def test_log_supports_sunset_chart_view():
    assert log_supports_sunset_chart_view({"period": {"horizon_mode": SUNSET_WINDOW}})
    assert not log_supports_sunset_chart_view({"period": {"horizon_mode": FIXED_24H}})


def test_resolve_chart_view_modes():
    fixed_meta = {"period": {"horizon_mode": FIXED_24H}}
    sunset_meta = {"period": {"horizon_mode": SUNSET_WINDOW}}
    assert _resolve_chart_view(
        fixed_meta,
        segment_toggle="SA₁→SA₂",
    ) == (VIEW_MODE_24H, 0)
    assert _resolve_chart_view(
        sunset_meta,
        segment_toggle="SA₀→SA₁",
    ) == (VIEW_MODE_SUNSET, 0)
    assert _resolve_chart_view(
        sunset_meta,
        segment_toggle="SA₁→SA₂",
    ) == (VIEW_MODE_SUNSET, 1)


def test_format_backtesting_window_range_matches_anchor_minus_24h():
    label = format_backtesting_window_range(
        "2025-01-06T00:00:00",
        "Europe/Vienna",
    )
    assert label == "2025-01-05 00:00 – 2025-01-06 00:00"


def test_format_deviation_window_fixed_24h_shows_slot_range():
    meta = {"period": {"horizon_mode": FIXED_24H}}
    case = {"window_anchor": "2025-01-06T00:00:00"}
    assert _format_deviation_window(case, meta) == (
        "2025-01-05 00:00 – 2025-01-06 00:00"
    )


def test_load_backtesting_display_bundle_rejects_horizon_mismatch(tmp_path):
    chart_rows, matrix = _sample_rows_for_snapshot()
    snapshot = build_window_snapshot(
        window_anchor=datetime(2026, 6, 23, 7, 0),
        scenario_id="live",
        horizon_mode=FIXED_24H,
        kind="consumption_tolerance",
        initial_soc=50.0,
        meta={"window_end": datetime(2026, 6, 23, 7, 0), "historical_total_kwh": 10.0},
        chart_rows_24h=chart_rows,
        matrix_24h=matrix,
    )
    write_window_snapshots_jsonl(str(tmp_path), [snapshot])
    with pytest.raises(ValueError, match="Fenster-Snapshot gehört zu Horizont"):
        load_backtesting_display_bundle(
            str(tmp_path),
            "2026-06-23T07:00:00",
            "live",
            log_horizon_mode=SUNSET_WINDOW,
        )


def _sample_rows_for_snapshot(count: int = 24, start: datetime | None = None):
    anchor = start or datetime(2026, 6, 23, 7, 0)
    window_start = anchor - timedelta(hours=count)
    matrix: list[dict] = []
    chart_rows: list[dict] = []
    for index in range(count):
        slot = window_start + timedelta(hours=index)
        matrix.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "expected_p_pv": 1.0,
                "expected_p_act": 0.5,
                "k_act": 12.0,
                "consumption_mode": "logged_day",
            }
        )
        chart_rows.append(
            {
                "slot_datetime": slot,
                "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
                "PV-Prognose (kW)": 1.0,
                "Verbrauch-Prognose (kW)": 0.5,
                "Geplante Batterie-Aktion (kW)": 0.0,
                "Netzbezug (kW)": 0.0,
                "Simulierter SoC (%)": 50.0,
                "Steuerbefehl": "Automatik",
            }
        )
    return chart_rows, matrix

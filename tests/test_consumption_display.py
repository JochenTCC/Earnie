# tests/test_consumption_display.py
"""Tests für Verbrauchs-UI-Kern (1.25.a)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from data.consumption_profiles import (
    build_modeled_hourly_kw_by_consumer,
    build_modeled_hourly_kw_profile,
)
from ui.consumption_display.adapters import bundle_from_cons_data, bundle_from_csv_validation, bundle_from_modeled_profile
from ui.consumption_display.aggregation import (
    iso_weeks_in_timestamps,
    months_in_timestamps,
    monthly_kwh_by_consumer,
    monthly_total_kwh,
    slice_bundle_for_iso_week,
    slice_bundle_for_month,
)
from ui.consumption_display.charts import (
    stack_monthly_sum_matches_total,
    stacked_monthly_chart,
    week_scenario_consumer_timeseries_chart,
    week_timeseries_chart,
)
from ui.backtesting_scenario_consumption import build_scenario_consumer_overlays
from ui.consumption_display.navigation import (
    parse_iso_week_jump,
    parse_iso_week_number_only,
    resolve_iso_week_jump_target,
    week_index_for_iso,
)


def _sample_profile() -> dict:
    return {
        "annual_kwh": 120.0,
        "baseload_kwh": 48.0,
        "consumers": [
            {"id": "pool", "type": "generic", "annual_kwh": 72.0},
        ],
    }


def test_build_modeled_hourly_kw_by_consumer_sums_to_profile():
    profile = _sample_profile()
    hours = 48
    by_consumer = build_modeled_hourly_kw_by_consumer(profile, hours=hours)
    total = build_modeled_hourly_kw_profile(profile, hours=hours)
    assert "baseload" in by_consumer
    assert "pool" in by_consumer
    summed = [0.0] * hours
    for series in by_consumer.values():
        summed = [a + b for a, b in zip(summed, series)]
    assert summed == pytest.approx(total)


def test_build_modeled_hourly_kw_by_consumer_baseload_constant():
    profile = {"annual_kwh": 24.0, "baseload_kwh": 24.0, "consumers": []}
    by_consumer = build_modeled_hourly_kw_by_consumer(profile, hours=24)
    assert by_consumer["baseload"] == pytest.approx([1.0] * 24)


def test_modeled_bundle_monthly_stack_matches_total():
    bundle = bundle_from_modeled_profile(_sample_profile(), hours=48)
    assert stack_monthly_sum_matches_total(bundle)
    totals = monthly_total_kwh(bundle)
    by_month = monthly_kwh_by_consumer(bundle)
    for month, total in totals.items():
        assert sum(by_month[month].values()) == pytest.approx(total)


def test_months_in_timestamps_respects_nav_bounds():
    start = datetime(2024, 2, 28, 0, 0, 0)
    timestamps = [
        (start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S")
        for index in range(96)
    ]
    bounds = (datetime(2024, 3, 1), datetime(2024, 3, 31, 23, 59, 59))
    months = months_in_timestamps(timestamps, nav_bounds=bounds)
    assert months == ["2024-03"]


def test_iso_weeks_in_timestamps_nav_bounds():
    start = datetime(2024, 3, 18, 0, 0, 0)
    timestamps = [
        (start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S")
        for index in range(336)
    ]
    bounds = (datetime(2024, 3, 20), datetime(2024, 3, 27, 23, 59, 59))
    weeks = iso_weeks_in_timestamps(timestamps, nav_bounds=bounds)
    assert weeks == [(2024, 12), (2024, 13)]


def test_slice_bundle_for_month():
    bundle = bundle_from_modeled_profile(_sample_profile(), hours=72)
    sliced = slice_bundle_for_month(bundle, "2023-01")
    assert sliced.hour_count() == 72
    assert all(ts.startswith("2023-01") for ts in sliced.timestamps)


def test_slice_bundle_for_iso_week_full_week():
    start = datetime(2024, 3, 18, 0, 0, 0)
    timestamps = [
        (start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S")
        for index in range(168)
    ]
    bundle = bundle_from_modeled_profile(_sample_profile(), hours=168)
    bundle = bundle.__class__(
        timestamps=timestamps,
        consumer_series=bundle.consumer_series,
        baseload=bundle.baseload,
        consumer_labels=bundle.consumer_labels,
    )
    sliced = slice_bundle_for_iso_week(bundle, iso_year=2024, iso_week=12)
    assert sliced.hour_count() == 168


def test_cons_data_bundle_pv_not_in_stack():
    idx = pd.date_range("2024-01-01", periods=3, freq="h", name="timestamp")
    df = pd.DataFrame(
        {
            "total_kw": [3.0, 3.0, 3.0],
            "baseload_kw": [1.0, 1.0, 1.0],
            "pv_kw": [0.5, 1.0, 0.0],
            "pool_kw": [2.0, 2.0, 2.0],
        },
        index=idx,
    )
    bundle = bundle_from_cons_data(df)
    assert bundle.pv is not None
    assert sum(bundle.pv) == pytest.approx(1.5)
    fig = stacked_monthly_chart(bundle)
    trace_names = [trace.name for trace in fig.data]
    assert "PV-Erzeugung" in trace_names
    bar_names = [trace.name for trace in fig.data if trace.type == "bar"]
    assert "PV-Erzeugung" not in bar_names
    assert stack_monthly_sum_matches_total(bundle)


def test_build_modeled_hourly_kw_by_consumer_ev_sums_to_profile():
    ev_consumer = {
        "id": "ev",
        "type": "ev",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "min_on_quarterhours": 4,
        "battery_capacity_kwh": 60.0,
        "charging_schedule": {
            "target_soc_percent": 100.0,
            "charging_efficiency": 0.95,
            "forecast_when_absent": True,
            "weekday": {
                "car_available_from_hour": 18,
                "ready_by_hour": 7,
                "daily_rest_soc": 40.0,
            },
            "weekend": {
                "car_available_from_hour": 20,
                "ready_by_hour": 9,
                "daily_rest_soc": 30.0,
            },
        },
    }
    profile = {
        "annual_kwh": 5000.0,
        "baseload_kwh": 1000.0,
        "consumers": [ev_consumer],
    }
    hours = 168
    by_consumer = build_modeled_hourly_kw_by_consumer(profile, hours=hours)
    total = build_modeled_hourly_kw_profile(profile, hours=hours)
    summed = [0.0] * hours
    for series in by_consumer.values():
        summed = [a + b for a, b in zip(summed, series)]
    assert summed == pytest.approx(total)
    assert "ev" in by_consumer


def test_cons_data_monthly_total_matches_total_kw_column():
    idx = pd.date_range("2024-01-01", periods=24, freq="h", name="timestamp")
    df = pd.DataFrame(
        {
            "total_kw": [2.0] * 24,
            "baseload_kw": [0.5] * 24,
            "pv_kw": [0.0] * 24,
            "pool_kw": [1.5] * 24,
        },
        index=idx,
    )
    bundle = bundle_from_cons_data(df)
    monthly = monthly_total_kwh(bundle)
    assert monthly["2024-01"] == pytest.approx(48.0)


def test_week_timeseries_chart_uses_datetime_axis_and_lines():
    start = datetime(2024, 3, 18, 0, 0, 0)
    timestamps = [
        (start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S")
        for index in range(168)
    ]
    profile = _sample_profile()
    series = [(ts, 2.0) for ts in timestamps]
    bundle = bundle_from_csv_validation(series, profile)
    fig = week_timeseries_chart(bundle, iso_year=2024, iso_week=12)
    assert fig.layout.xaxis.type == "date"
    for trace in fig.data:
        assert trace.mode == "lines"
        assert getattr(trace, "stackgroup", None) is None
    trace_names = {trace.name for trace in fig.data}
    assert "Ist (CSV)" in trace_names
    assert "pool" in trace_names


def test_week_scenario_consumer_timeseries_chart_uses_consumer_color_and_scenario_dash():
    start = datetime(2024, 3, 18, 0, 0, 0)
    timestamps = [
        (start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S")
        for index in range(168)
    ]
    profile_a = _sample_profile()
    profile_b = {
        "annual_kwh": 240.0,
        "baseload_kwh": 48.0,
        "consumers": [{"id": "other", "type": "generic", "annual_kwh": 192.0}],
    }
    overlay_bundle = build_scenario_consumer_overlays(
        {
            "a": {"_house_profile": profile_a},
            "b": {"_house_profile": profile_b},
        },
        {"a": "Szenario A", "b": "Szenario B"},
        timestamps,
    )
    assert overlay_bundle is not None
    fig = week_scenario_consumer_timeseries_chart(
        timestamps,
        overlay_bundle,
        iso_year=2024,
        iso_week=12,
    )
    pool_traces = [trace for trace in fig.data if trace.name.endswith("— pool")]
    assert len(pool_traces) == 2
    assert pool_traces[0].line.color == pool_traces[1].line.color
    assert pool_traces[0].line.dash != pool_traces[1].line.dash
    other_traces = [trace for trace in fig.data if trace.name.endswith("— other")]
    assert len(other_traces) == 2
    assert other_traces[0].line.dash != other_traces[1].line.dash
    assert max(other_traces[0].y) == 0.0
    assert max(other_traces[1].y) > 0.0


def test_parse_iso_week_jump_formats():
    assert parse_iso_week_jump("12/2025") == (2025, 12)
    assert parse_iso_week_jump("KW 12/2025") == (2025, 12)
    assert parse_iso_week_jump("2025-W12") == (2025, 12)
    assert parse_iso_week_jump("2025/12") == (2025, 12)
    assert parse_iso_week_jump("") is None
    assert parse_iso_week_jump("invalid") is None
    assert parse_iso_week_jump("12") is None


def test_parse_iso_week_number_only():
    assert parse_iso_week_number_only("12") == 12
    assert parse_iso_week_number_only("KW 12") == 12
    assert parse_iso_week_number_only("53") == 53
    assert parse_iso_week_number_only("0") is None
    assert parse_iso_week_number_only("54") is None
    assert parse_iso_week_number_only("") is None


def test_resolve_iso_week_jump_target_week_only():
    weeks = [(2024, 11), (2024, 12), (2025, 12), (2025, 13)]
    assert resolve_iso_week_jump_target("12", weeks, current_idx=1) == (2024, 12)
    assert resolve_iso_week_jump_target("12", weeks, current_idx=3) == (2025, 12)
    assert resolve_iso_week_jump_target("99", weeks) is None
    assert resolve_iso_week_jump_target("12/2025", weeks) == (2025, 12)


def test_week_index_for_iso():
    weeks = [(2024, 11), (2024, 12), (2024, 13)]
    assert week_index_for_iso(weeks, 2024, 12) == 1
    assert week_index_for_iso(weeks, 2024, 99) is None

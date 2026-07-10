# tests/test_consumption_validation.py
"""Tests für Ist-vs-Modell-Verbrauchsvergleich."""
from __future__ import annotations

from datetime import datetime, timedelta

from ui.consumption_validation_charts import (
    cons_data_columns_timeseries_chart,
    cons_dataframe_to_navigation_series,
    cons_dataframe_to_series,
    csv_series_to_monthly_kwh,
    format_iso_week_label,
    iso_weeks_in_series,
    modeled_monthly_kwh,
    slice_cons_dataframe_for_iso_week,
    slice_series_for_iso_week,
    timeseries_comparison_chart,
    timeseries_comparison_from_series,
)


def test_csv_series_to_monthly_kwh():
    series = [
        ("2023-01-01 00:00:00", 1.0),
        ("2023-01-01 01:00:00", 2.0),
        ("2023-02-01 00:00:00", 3.0),
    ]
    monthly = csv_series_to_monthly_kwh(series)
    assert monthly["2023-01"] == 3.0
    assert monthly["2023-02"] == 3.0


def test_modeled_monthly_kwh_from_baseload():
    profile = {
        "annual_kwh": 48.0,
        "baseload_kwh": 48.0,
        "consumers": [],
    }
    monthly = modeled_monthly_kwh(profile, hours=48)
    assert sum(monthly.values()) == 48.0


def test_iso_weeks_in_series_two_weeks():
    start = datetime(2024, 3, 18, 0, 0, 0)
    series = [
        ((start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S"), 1.0)
        for index in range(200)
    ]
    weeks = iso_weeks_in_series(series)
    assert len(weeks) >= 2
    assert weeks[0] == (2024, 12)
    assert weeks[1] == (2024, 13)


def test_format_iso_week_label():
    label = format_iso_week_label(2024, 1)
    assert label.startswith("KW 1/2024 (")
    assert "2024)" in label


def test_slice_series_for_iso_week_full_week():
    start = datetime(2024, 3, 18, 0, 0, 0)
    series = [
        ((start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S"), float(index))
        for index in range(168)
    ]
    modeled = [float(index) * 0.5 for index in range(168)]
    iso_year, iso_week = start.isocalendar()[:2]
    timestamps, actual, modeled_slice = slice_series_for_iso_week(
        series, modeled, iso_year, iso_week
    )
    assert len(actual) == 168
    assert len(modeled_slice) == 168
    assert actual[0] == 0.0
    assert modeled_slice[-1] == modeled[-1]
    assert len(timestamps) == 168


def test_slice_series_for_iso_week_partial_at_start():
    start = datetime(2024, 3, 20, 0, 0, 0)
    series = [
        ((start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S"), 2.0)
        for index in range(24)
    ]
    modeled = [1.0] * 24
    iso_year, iso_week = start.isocalendar()[:2]
    _, actual, _ = slice_series_for_iso_week(series, modeled, iso_year, iso_week)
    assert len(actual) == 24


def test_timeseries_comparison_chart_title_contains_kw(tmp_path):
    csv_path = tmp_path / "week.csv"
    start = datetime(2024, 3, 18, 0, 0, 0)
    lines = ["timestamp;power_kw"]
    for index in range(168):
        ts = (start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{ts};1.0")
    csv_path.write_text("\n".join(lines), encoding="utf-8")
    iso_year, iso_week = start.isocalendar()[:2]
    profile = {"annual_kwh": 8760.0, "baseload_kwh": 8760.0, "consumers": []}
    fig = timeseries_comparison_chart(
        str(csv_path),
        profile,
        iso_year=iso_year,
        iso_week=iso_week,
    )
    assert f"KW {iso_week}/{iso_year}" in fig.layout.title.text


def test_timeseries_comparison_from_series_matches_csv_chart(tmp_path):
    csv_path = tmp_path / "week.csv"
    start = datetime(2024, 3, 18, 0, 0, 0)
    lines = ["timestamp;power_kw"]
    series: list[tuple[str, float]] = []
    for index in range(168):
        ts = (start + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{ts};1.0")
        series.append((ts, 1.0))
    csv_path.write_text("\n".join(lines), encoding="utf-8")
    iso_year, iso_week = start.isocalendar()[:2]
    profile = {"annual_kwh": 8760.0, "baseload_kwh": 8760.0, "consumers": []}
    from_csv = timeseries_comparison_chart(
        str(csv_path),
        profile,
        iso_year=iso_year,
        iso_week=iso_week,
    )
    from_series = timeseries_comparison_from_series(
        series,
        profile,
        iso_year=iso_year,
        iso_week=iso_week,
    )
    assert from_csv.layout.title.text == from_series.layout.title.text
    assert from_csv.data[0].y == from_series.data[0].y


def test_cons_dataframe_to_series_empty():
    import pandas as pd

    assert cons_dataframe_to_series(pd.DataFrame()) == []


def test_cons_data_columns_timeseries_chart_three_traces():
    import pandas as pd

    start = datetime(2024, 3, 18, 0, 0, 0)
    index = pd.date_range(start, periods=168, freq="h", name="timestamp")
    df = pd.DataFrame(
        {
            "total_kw": [1.0] * 168,
            "baseload_kw": [0.5] * 168,
            "pv_kw": [0.2] * 168,
        },
        index=index,
    )
    iso_year, iso_week = start.isocalendar()[:2]
    sliced = slice_cons_dataframe_for_iso_week(df, iso_year=iso_year, iso_week=iso_week)
    assert len(sliced) == 168
    fig = cons_data_columns_timeseries_chart(df, iso_year=iso_year, iso_week=iso_week)
    assert len(fig.data) == 3
    assert {trace.name for trace in fig.data} == {"total_kw", "baseload_kw", "pv_kw"}


def test_cons_dataframe_to_navigation_series_uses_index():
    import pandas as pd

    index = pd.date_range("2024-01-01", periods=3, freq="h", name="timestamp")
    df = pd.DataFrame({"total_kw": [1.0, 2.0, 3.0]}, index=index)
    series = cons_dataframe_to_navigation_series(df)
    assert len(series) == 3
    assert series[0][0].startswith("2024-01-01")

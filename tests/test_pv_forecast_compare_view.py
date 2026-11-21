"""PV forecasts of the comparison logger for Chart 1 (rule a: latest run before the hour)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import pytest

from runtime_store import pv_forecast_compare_view as view
from ui.chart_pv_compare import add_pv_compare_traces
from ui.chart_slot_axis import ChartSlotAxis

import pandas as pd

UTC = timezone.utc
VIENNA = ZoneInfo("Europe/Vienna")


def _line(fetched_at: str, source: str, system: str, kwh: dict) -> str:
    return json.dumps(
        {"run_id": fetched_at, "fetched_at": fetched_at, "source": source,
         "system_id": system, "kwh": kwh},
        separators=(",", ":"),
    )


def _write(path, lines) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture()
def forecasts(tmp_path):
    path = tmp_path / view.FORECASTS_FILENAME
    _write(path, [
        # 08:05 run: 09 and 10 UTC; 09:05 run changes both.
        _line("2026-11-21T08:05:00+00:00", "forecast_solar", "sued", {"2026-11-21T09:00Z": 1.0, "2026-11-21T10:00Z": 2.0}),
        _line("2026-11-21T08:05:00+00:00", "forecast_solar", "nord", {"2026-11-21T09:00Z": 0.5, "2026-11-21T10:00Z": 0.5}),
        _line("2026-11-21T09:05:00+00:00", "forecast_solar", "sued", {"2026-11-21T09:00Z": 9.0, "2026-11-21T10:00Z": 3.0}),
        _line("2026-11-21T09:05:00+00:00", "forecast_solar", "nord", {"2026-11-21T09:00Z": 9.0, "2026-11-21T10:00Z": 1.0}),
        # Solcast only for one system in this hour: no partial sum.
        _line("2026-11-21T05:00:00+00:00", "solcast", "sued", {"2026-11-21T09:00Z": 1.2, "2026-11-21T10:00Z": 1.4}),
        _line("2026-11-21T05:00:00+00:00", "solcast", "nord", {"2026-11-21T10:00Z": 0.3}),
    ])
    return path


def _hour(h: int) -> datetime:
    return datetime(2026, 11, 21, h, tzinfo=UTC)


def test_each_hour_uses_the_latest_run_before_it_starts(forecasts):
    out = view.series_by_source(forecasts, [_hour(9), _hour(10)])
    # 09 UTC: the 09:05 run came after the hour started, so the 08:05 run counts.
    assert out["forecast_solar"]["2026-11-21T09:00Z"] == 1.5
    # 10 UTC: the 09:05 run is the latest before 10:00.
    assert out["forecast_solar"]["2026-11-21T10:00Z"] == 4.0


def test_a_missing_system_leaves_the_hour_empty(forecasts):
    out = view.series_by_source(forecasts, [_hour(9), _hour(10)])
    assert out["solcast"]["2026-11-21T09:00Z"] is None
    assert out["solcast"]["2026-11-21T10:00Z"] == 1.7


def test_hours_before_any_run_have_no_line(forecasts):
    # Only later runs exist: no source has a run before these hours, so nothing is drawn.
    assert view.series_by_source(forecasts, [_hour(4)]) == {}


def test_hour_without_a_value_in_the_latest_run_is_empty(forecasts):
    out = view.series_by_source(forecasts, [_hour(9), _hour(12)])
    assert out["forecast_solar"]["2026-11-21T12:00Z"] is None


def test_future_hours_use_the_latest_run(forecasts):
    out = view.series_by_source(forecasts, [_hour(10) + timedelta(days=0)])
    assert out["forecast_solar"]["2026-11-21T10:00Z"] == 4.0


def test_quarter_hour_slots_in_local_time_take_the_hour_value(forecasts):
    # 11:00 and 11:45 Vienna (CET) = 10 UTC.
    slots = [datetime(2026, 11, 21, 11, 0, tzinfo=VIENNA), datetime(2026, 11, 21, 11, 45, tzinfo=VIENNA)]
    by_source = view.series_by_source(forecasts, slots)
    assert view.slot_series(by_source, slots)["forecast_solar"] == [4.0, 4.0]


def test_naive_times_fail_loud():
    with pytest.raises(ValueError, match="Zeitzone"):
        view.hour_key(datetime(2026, 11, 21, 10))


def test_missing_file_fails_loud(tmp_path):
    with pytest.raises(view.PvForecastCompareError, match="fehlt"):
        view.cached_series_by_source(tmp_path / view.FORECASTS_FILENAME, [_hour(9)])


def test_broken_line_names_file_and_line(tmp_path):
    path = tmp_path / view.FORECASTS_FILENAME
    _write(path, ['{"fetched_at":"2026-11-21T08:05:00+00:00", broken'])
    with pytest.raises(view.PvForecastCompareError, match=":1:"):
        view.series_by_source(path, [_hour(9)])


def test_cache_reads_again_after_the_file_grows(forecasts):
    first = view.cached_series_by_source(forecasts, [_hour(11)])
    assert first["forecast_solar"]["2026-11-21T11:00Z"] is None
    with forecasts.open("a", encoding="utf-8") as handle:
        handle.write(_line("2026-11-21T10:05:00+00:00", "forecast_solar", "sued", {"2026-11-21T11:00Z": 2.0}) + "\n")
        handle.write(_line("2026-11-21T10:05:00+00:00", "forecast_solar", "nord", {"2026-11-21T11:00Z": 1.0}) + "\n")
    second = view.cached_series_by_source(forecasts, [_hour(11)])
    assert second["forecast_solar"]["2026-11-21T11:00Z"] == 3.0


def test_env_switch_off_by_default(monkeypatch):
    monkeypatch.delenv(view.ENV_DIR, raising=False)
    assert view.compare_dir_from_env() is None


def test_chart_draws_one_dotted_line_per_source_from_hour_centre_to_hour_centre():
    # 10:30 to 12:30 in quarter hours: half of hour 10, all of 11, half of hour 12.
    start = datetime(2026, 11, 21, 10, 30, tzinfo=VIENNA)
    starts = [start + timedelta(minutes=15 * i) for i in range(8)]
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": starts}))
    fig = go.Figure()
    solcast = [1.0, 1.0, None, None, None, None, 3.0, 3.0]
    add_pv_compare_traces(fig, axis, {"solcast": solcast, "forecast_solar": [2.0] * 8})
    names = [trace.name for trace in fig.data]
    assert names == ["forecast.solar (Stundenenergie)", "Solcast"]
    trace = fig.data[1]
    assert trace.line.shape is None and trace.line.dash == "dot"
    assert trace.connectgaps is False
    # One point per hour, in the middle of the hour's shown slots.
    assert list(trace.x) == [
        datetime(2026, 11, 21, 10, 45, tzinfo=VIENNA),
        datetime(2026, 11, 21, 11, 30, tzinfo=VIENNA),
        datetime(2026, 11, 21, 12, 15, tzinfo=VIENNA),
    ]
    assert list(trace.y) == [1.0, None, 3.0]


def test_chart_rejects_different_values_within_one_hour():
    starts = [datetime(2026, 11, 21, 10, 0, tzinfo=VIENNA) + timedelta(minutes=15 * i) for i in range(4)]
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": starts}))
    with pytest.raises(ValueError, match="derselben Stunde"):
        add_pv_compare_traces(go.Figure(), axis, {"solcast": [1.0, 1.0, None, 1.0]})


def test_chart_rejects_series_of_the_wrong_length():
    starts = [datetime(2026, 11, 21, 10, 0, tzinfo=VIENNA)]
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": starts}))
    with pytest.raises(ValueError, match="Slots"):
        add_pv_compare_traces(go.Figure(), axis, {"solcast": [1.0, 2.0]})

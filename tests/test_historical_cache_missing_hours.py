"""SE / backtesting cache: hours missing in cons_data abort instead of counting as 0 kW."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

import config
from data import profile_manager as pm
from simulation import historical_cache as hc
from simulation.historical_cache import HistoricalDataCache


@pytest.fixture(autouse=True)
def vienna(monkeypatch):
    monkeypatch.setattr(config, "get_planning_timezone", lambda: "Europe/Vienna")
    monkeypatch.setattr(
        "data.cons_data_house_profile.expected_cons_data_consumer_ids", lambda: []
    )


def _frame(start: str, hours: int, *, drop: tuple[str, ...] = (), pv: float = 1.0) -> pd.DataFrame:
    idx = pd.date_range(start, periods=hours, freq="h")
    frame = pd.DataFrame({"Total": 2.0, "BaseLoad": 1.5, "pv_kw": pv}, index=idx)
    return frame.drop(index=[pd.Timestamp(ts) for ts in drop])


def _cache(frame: pd.DataFrame) -> HistoricalDataCache:
    cache = HistoricalDataCache()
    cache._consumption_df = frame[["Total", "BaseLoad"]]
    cache._pv_series = frame["pv_kw"]
    cache._consumption_df_hourly = hc._floor_dedup_to_hour(cache._consumption_df)
    cache._pv_series_hourly = hc._floor_dedup_to_hour(cache._pv_series)
    return cache


def _day_slots(day: str) -> list[datetime]:
    start = datetime.fromisoformat(day)
    return [start + timedelta(minutes=15 * i) for i in range(96)]


def test_complete_day_holds_the_hour_values():
    cache = _cache(_frame("2024-06-01", 24))

    baseload, _totals, total, _flex = cache.get_window_consumption(_day_slots("2024-06-01"))

    assert baseload == [1.5] * 96
    assert total == [2.0] * 96


def test_day_without_rows_raises():
    cache = _cache(_frame("2024-06-01", 24))

    with pytest.raises(pm.MissingConsumptionDataError, match="02.06.2024: keine Daten"):
        cache.get_window_consumption(_day_slots("2024-06-02"))


def test_day_with_missing_hours_names_them():
    cache = _cache(_frame("2024-06-01", 24, drop=("2024-06-01 03:00", "2024-06-01 17:00")))

    with pytest.raises(
        pm.MissingConsumptionDataError, match=r"01.06.2024: 2 Stunden fehlen \(03, 17 Uhr\)"
    ):
        cache.get_window_consumption(_day_slots("2024-06-01"))


def test_window_over_two_days_names_only_the_missing_part():
    """A ready_by window (07:00 to 07:00) needs the evening of the day before."""
    cache = _cache(_frame("2024-06-02", 24))
    slots = [datetime(2024, 6, 1, 7) + timedelta(minutes=15 * i) for i in range(96)]

    with pytest.raises(pm.MissingConsumptionDataError, match="01.06.2024: keine Daten") as err:
        cache.get_window_consumption(slots)
    assert "02.06.2024" not in str(err.value)


def test_spring_dst_day_is_complete_without_the_skipped_hour():
    cache = _cache(_frame("2026-03-29", 24, drop=("2026-03-29 02:00",)))

    _baseload, _totals, total, _flex = cache.get_window_consumption(_day_slots("2026-03-29"))

    assert total[8:12] == [0.0] * 4
    assert sum(total) * 0.25 == pytest.approx(23 * 2.0)


def test_autumn_dst_day_is_complete_with_one_0200_row():
    cache = _cache(_frame("2026-10-25", 24))

    _baseload, _totals, total, _flex = cache.get_window_consumption(_day_slots("2026-10-25"))

    assert total == [2.0] * 96


def test_pv_raises_for_a_missing_hour():
    cache = _cache(_frame("2024-06-01", 24, drop=("2024-06-01 12:00",)))

    with pytest.raises(pm.MissingConsumptionDataError, match=r"1 Stunden fehlen \(12 Uhr\)"):
        cache.get_pv_for_slots(_day_slots("2024-06-01"))


def test_pv_zero_at_night_is_a_value_not_a_gap():
    cache = _cache(_frame("2024-06-01", 24, pv=0.0))

    assert cache.get_pv_for_slots(_day_slots("2024-06-01")) == [0.0] * 96


def test_consumer_series_raise_for_a_missing_hour(monkeypatch):
    monkeypatch.setattr(
        "data.cons_data_house_profile.consumer_labels_for_ids", lambda ids: {"ev": "Total"}
    )
    cache = _cache(_frame("2024-06-01", 24, drop=("2024-06-01 05:00",)))

    with pytest.raises(pm.MissingConsumptionDataError, match=r"\(05 Uhr\)"):
        cache.get_consumer_kw_for_slots(_day_slots("2024-06-01"), ["ev"])


def test_anchor_list_raises_for_a_day_without_data(monkeypatch):
    from simulation import engine

    monkeypatch.setattr(engine, "_charging_schedule_consumer", lambda: None)
    cache = _cache(_frame("2024-06-01", 24))

    with pytest.raises(pm.MissingConsumptionDataError, match="02.06.2024: keine Daten"):
        engine.list_simulation_anchors(
            pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-02"), cache
        )


def test_season_mirror_covers_one_day_around_the_period(monkeypatch):
    monkeypatch.setattr("data.cons_data_season_mirror.is_season_mirror_enabled", lambda: True)
    source = _frame("2025-01-01", 24 * 365)
    cache = HistoricalDataCache(
        season_mirror_window=(pd.Timestamp("2026-02-01"), pd.Timestamp("2026-02-28"))
    )

    mirrored = cache._maybe_season_mirror(source)

    assert mirrored.index.min() == pd.Timestamp("2026-01-31 00:00")
    assert mirrored.index.max() == pd.Timestamp("2026-03-01 23:00")
    assert len(mirrored) == 30 * 24


def test_hold_reindex_has_no_gap_after_a_complete_mirror(monkeypatch):
    monkeypatch.setattr("data.cons_data_season_mirror.is_season_mirror_enabled", lambda: True)
    source = _frame("2025-01-01", 24 * 365)
    cache = HistoricalDataCache(
        season_mirror_window=(pd.Timestamp("2026-02-01"), pd.Timestamp("2026-02-28"))
    )
    mirrored = cache._maybe_season_mirror(source)
    slots = [datetime(2026, 1, 31, 7) + timedelta(minutes=15 * i) for i in range(96)]

    held = hc._hour_hold_reindex(mirrored["Total"], slots)

    assert held.tolist() == [2.0] * 96

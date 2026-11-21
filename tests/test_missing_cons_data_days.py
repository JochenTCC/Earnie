"""A day missing in cons_data: Live uses the configured target, logged-day runs fail loud."""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import pytest

import config
from data import consumer_targets as ct
from data import profile_manager as pm

EV = {"id": "ev", "name": "EV", "daily_target_source": "historical", "daily_target_kwh": 7.0}


@pytest.fixture(autouse=True)
def vienna(monkeypatch):
    monkeypatch.setattr(config, "get_planning_timezone", lambda: "Europe/Vienna")
    monkeypatch.setattr(pm.config, "get_flexible_consumers", lambda optimizer_only=False: [EV])
    monkeypatch.setattr(ct.config, "get_flexible_consumers", lambda optimizer_only=False: [EV])
    monkeypatch.setattr(
        "data.cons_data_house_profile.consumer_labels_for_ids", lambda ids: {i: "EV" for i in ids}
    )


def _frame(start: str, hours: int, *, drop: tuple[str, ...] = ()) -> pd.DataFrame:
    idx = pd.date_range(start, periods=hours, freq="h")
    frame = pd.DataFrame({"Total": 2.0, "BaseLoad": 1.0, "EV": 0.5}, index=idx)
    return frame.drop(index=[pd.Timestamp(ts) for ts in drop])


def test_live_historical_target_uses_the_configured_target_for_a_missing_day(monkeypatch, caplog):
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: _frame("2024-06-01", 24))

    with caplog.at_level(logging.WARNING):
        target = ct._resolve_single_consumer_daily_target_kwh(EV, date(2024, 6, 5))

    assert target == 7.0
    assert any("daily_target_kwh" in rec.getMessage() for rec in caplog.records)


def test_live_historical_target_uses_the_logged_day(monkeypatch):
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: _frame("2024-06-01", 24))

    assert ct._resolve_single_consumer_daily_target_kwh(EV, date(2024, 6, 1)) == pytest.approx(12.0)


def test_logged_day_without_data_raises(monkeypatch):
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: _frame("2024-06-01", 24))

    with pytest.raises(pm.MissingConsumptionDataError, match="05.06.2024 keine Daten"):
        ct.resolve_historical_consumer_daily_targets(date(2024, 6, 5))


def test_logged_day_with_missing_hours_raises(monkeypatch):
    frame = _frame("2024-06-01", 24, drop=("2024-06-01 03:00", "2024-06-01 17:00"))
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: frame)

    with pytest.raises(pm.MissingConsumptionDataError, match="2 von 24 Stunden fehlen \\(03, 17 Uhr\\)"):
        ct.resolve_historical_consumer_daily_targets(date(2024, 6, 1))


def test_spring_dst_day_is_complete_with_23_hours(monkeypatch):
    frame = _frame("2026-03-29", 24, drop=("2026-03-29 02:00",))
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: frame)

    totals = ct.resolve_historical_consumer_daily_targets(date(2026, 3, 29))

    assert totals == {"ev": pytest.approx(11.5)}


def test_live_partial_day_counts_missing_hours_as_zero_with_a_warning(monkeypatch, caplog):
    frame = _frame("2024-06-01", 24, drop=("2024-06-01 03:00",))
    monkeypatch.setattr(pm, "_load_profile_source_dataframe", lambda: frame)

    with caplog.at_level(logging.WARNING):
        _base, totals, _total = pm.get_historical_day_data(date(2024, 6, 1))

    assert totals == {"ev": pytest.approx(11.5)}
    assert any("fehlen 1 Stunden" in rec.getMessage() for rec in caplog.records)

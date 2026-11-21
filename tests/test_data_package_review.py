"""Findings of the code review of ``data/`` (2026-11-21)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data import consumption_profiles as cp
from data import cons_data_house_profile as chp
from data import cons_data_store as store
from data import outdoor_forecast as of
from data import pv_forecast as pf

VIENNA = ZoneInfo("Europe/Vienna")


@pytest.fixture
def vienna(monkeypatch):
    monkeypatch.setattr(of.config, "get_planning_timezone", lambda: "Europe/Vienna")
    monkeypatch.setattr(pf.config, "get_planning_timezone", lambda: "Europe/Vienna")


# --- Open-Meteo substitute with timezone-aware Live slots ----------------------------------


def test_open_meteo_pv_vector_accepts_aware_live_slots(monkeypatch, vienna):
    base = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)

    def fake_fetch(lat, lon, *, forecast_days, hourly_vars, extra_params=None, payload_transform=None):
        return {var: [(base + timedelta(hours=i), 500.0) for i in range(72)] for var in hourly_vars}

    monkeypatch.setattr(of, "_fetch_open_meteo_hourly_vars", fake_fetch)
    of._TILTED_CACHE.clear()
    now = datetime.now(VIENNA).replace(minute=0, second=0, microsecond=0)
    slots = [now + timedelta(minutes=15 * i) for i in range(8)]

    vector = pf._open_meteo_pv_vector(
        lat=47.0, lon=9.7, tilt=30, azimuth=0, kwp=10.0, target_hours=slots, shading=None
    )

    assert vector == [5.0] * 8


def test_outdoor_forecast_accepts_aware_start(monkeypatch, vienna):
    base = datetime(2026, 11, 21, 0)
    monkeypatch.setattr(
        of,
        "_fetch_open_meteo_hourly",
        lambda lat, lon, *, forecast_days: [(base + timedelta(hours=i), float(i)) for i in range(72)],
    )
    of._CACHE.clear()

    values = of.get_hourly_outdoor_forecast_c(
        horizon=3, latitude=47.0, longitude=9.7, start=datetime(2026, 11, 21, 10, 20, tzinfo=VIENNA)
    )

    assert values == [10.0, 11.0, 12.0]


# --- cons_data: atomic writes, unreadable pending buffer -----------------------------------


def _hours(n: int = 3) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="h", name="timestamp")
    return pd.DataFrame(
        {"total_kw": [1.0] * n, "baseload_kw": [1.0] * n, "pv_kw": [0.0] * n, "source": ["measured"] * n},
        index=idx,
    )


@pytest.fixture
def no_house_profile(monkeypatch):
    monkeypatch.setattr(store, "_consumer_column_ids", lambda: [])
    monkeypatch.setattr(store, "get_retention_months", lambda: 0)
    monkeypatch.setattr(chp, "expected_cons_data_consumer_ids", lambda: [])
    monkeypatch.setattr(chp, "current_cons_data_synthesis_fingerprint", lambda: None)


def test_failed_cons_data_write_keeps_the_previous_file(tmp_path, monkeypatch, no_house_profile):
    path = str(tmp_path / "cons_data.csv")
    store.save_cons_data(_hours(), path)
    before = (tmp_path / "cons_data.csv").read_text(encoding="utf-8")

    def broken_to_csv(self, target, *args, **kwargs):
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("timestamp;total_kw\n2026-01-0")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_csv", broken_to_csv)
    with pytest.raises(OSError):
        store.save_cons_data(_hours(5), path)

    assert (tmp_path / "cons_data.csv").read_text(encoding="utf-8") == before


def test_unreadable_pending_buffer_is_kept_aside(tmp_path, monkeypatch, caplog):
    pending = tmp_path / "cons_data_pending.json"
    pending.write_text('{"samples": [{"ts": "2026-01-01T10:00"', encoding="utf-8")
    monkeypatch.setattr(store, "PENDING_STATE_FILE", str(pending))

    state = store._load_pending_state()

    assert state == {"samples": [], "last_daily_flush": None}
    kept = list(tmp_path.glob("cons_data_pending.json.unreadable-*"))
    assert len(kept) == 1
    assert kept[0].read_text(encoding="utf-8").startswith('{"samples"')
    assert not pending.exists()
    assert any("unreadable" in rec.message for rec in caplog.records)


# --- forecast.solar: cache age and coverage of the daylight days ---------------------------


def test_memory_cache_older_than_the_limit_is_dropped(monkeypatch):
    url = "https://api.forecast.solar/estimate/1/2/3/4/5"
    monkeypatch.setattr(pf, "_CACHED_HOURLY_WATTS_BY_URL", {url: {"2026-11-20 12:00:00": 1000}})
    monkeypatch.setattr(
        pf,
        "_LAST_API_CALL_BY_URL",
        {url: datetime.now() - pf.DISK_CACHE_MAX_AGE - timedelta(minutes=1)},
    )

    assert pf._fresh_memory_cache(url, datetime.now()) is None
    assert url not in pf._CACHED_HOURLY_WATTS_BY_URL


def test_fresh_memory_cache_is_kept(monkeypatch):
    url = "https://api.forecast.solar/estimate/1/2/3/4/5"
    watts = {"2026-11-20 12:00:00": 1000}
    monkeypatch.setattr(pf, "_CACHED_HOURLY_WATTS_BY_URL", {url: watts})
    monkeypatch.setattr(pf, "_LAST_API_CALL_BY_URL", {url: datetime.now() - timedelta(hours=1)})

    assert pf._fresh_memory_cache(url, datetime.now()) is watts


def test_daylight_day_without_forecast_points_is_uncovered(vienna):
    watts = {
        "2026-11-21 07:30:00": 0,
        "2026-11-21 12:00:00": 3000,
        "2026-11-21 16:30:00": 0,
    }
    start = datetime(2026, 11, 21, 18, 0, tzinfo=VIENNA)
    slots = [start + timedelta(minutes=15 * i) for i in range(4 * 36)]  # to 22.11. 06:00 + 30 h

    uncovered = pf._uncovered_daylight_days(watts, slots, lat=47.4, lon=9.7)

    assert uncovered == [date(2026, 11, 22)]


def test_night_only_day_without_points_is_not_needed(vienna):
    watts = {"2026-11-21 12:00:00": 3000, "2026-11-21 16:30:00": 0}
    start = datetime(2026, 11, 21, 18, 0, tzinfo=VIENNA)
    slots = [start + timedelta(minutes=15 * i) for i in range(4 * 12)]  # to 22.11. 06:00

    assert pf._uncovered_daylight_days(watts, slots, lat=47.4, lon=9.7) == []


# --- profile column labels -----------------------------------------------------------------


def test_consumer_labels_are_unique_over_all_consumers(monkeypatch):
    monkeypatch.setattr(chp, "expected_cons_data_consumer_ids", lambda: ["wb1", "wb2", "pool"])
    monkeypatch.setattr(
        chp,
        "_raw_consumer_labels",
        lambda ids: {cid: {"wb1": "Wallbox", "wb2": "Wallbox", "pool": "Total"}.get(cid, cid) for cid in ids},
    )

    assert chp.consumer_labels_for_ids(["wb2"]) == {"wb2": "Wallbox (wb2)"}
    assert chp.consumer_labels_for_ids(["wb1", "pool"]) == {
        "wb1": "Wallbox (wb1)",
        "pool": "Total (pool)",
    }


# --- modeled reference year ----------------------------------------------------------------


def test_slot_after_a_leap_reference_year_keeps_its_calendar_day(monkeypatch):
    monkeypatch.setattr(cp, "modeled_profile_ref_start", lambda: datetime(2028, 1, 1))

    assert cp._modeled_hour_index(datetime(2029, 1, 10, 5)) == 9 * 24 + 5
    assert cp._modeled_hour_index(datetime(2029, 12, 31, 23)) == 364 * 24 + 23


def test_leap_day_maps_to_28_february_of_a_common_reference_year(monkeypatch):
    monkeypatch.setattr(cp, "modeled_profile_ref_start", lambda: datetime(2025, 1, 1))

    assert cp._modeled_hour_index(datetime(2028, 2, 29, 12)) == 58 * 24 + 12
    assert cp._modeled_hour_index(datetime(2028, 3, 1, 0)) == 59 * 24


def test_last_day_of_a_leap_reference_year_stays_inside_the_profile(monkeypatch):
    monkeypatch.setattr(cp, "modeled_profile_ref_start", lambda: datetime(2028, 1, 1))

    index = cp._modeled_hour_index(datetime(2028, 12, 31, 23))

    assert index == 364 * 24 + 23
    assert index < cp.MODELED_PROFILE_HOURS_PER_YEAR

"""Tests für die Slot-Zuordnung und Auswertung in scripts/pv_forecast_compare."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from scripts import pv_forecast_compare as pfc

# Dornbirn-like site.
LAT, LON = 47.4, 9.7
VIENNA = ZoneInfo("Europe/Vienna")


def test_forecast_solar_period_energy_goes_to_containing_hour():
    # Winter time: local 08:00 = 07:00Z. Period ending 07:31 (sunrise) and 08:00 both lie in 07:xx local.
    slots = pfc.forecast_solar_period_slots(
        {"2026-10-29 07:31:00": 0, "2026-10-29 08:00:00": 120, "2026-10-29 09:00:00": 900},
        VIENNA,
    )
    assert slots == {"2026-10-29T06:00Z": 0.12, "2026-10-29T07:00Z": 0.9}


def test_forecast_solar_earnie_uses_watts_at_slot_start_only():
    slots = pfc.forecast_solar_earnie_slots(
        {"2026-10-29 07:31:00": 0, "2026-10-29 08:00:00": 400, "2026-10-29 09:00:00": 1500},
        VIENNA,
    )
    assert slots == {"2026-10-29T07:00Z": 0.4, "2026-10-29T08:00Z": 1.5}


def test_solcast_half_hours_sum_into_clock_hour():
    slots = pfc.solcast_slots(
        [
            {"period_end": "2026-10-29T10:30:00.0000000Z", "period": "PT30M", "pv_estimate": 2.0},
            {"period_end": "2026-10-29T11:00:00.0000000Z", "period": "PT30M", "pv_estimate": 3.0},
        ]
    )
    assert slots == {"2026-10-29T10:00Z": 2.5}


def test_solcast_rejects_unexpected_period():
    with pytest.raises(ValueError, match="PT30M"):
        pfc.solcast_slots(
            [{"period_end": "2026-10-29T11:00:00Z", "period": "PT15M", "pv_estimate": 1.0}]
        )


def test_open_meteo_preceding_hour_mean_and_horizon_gaps():
    slots = pfc.open_meteo_slots(
        ["2026-10-29T11:00", "2026-10-29T12:00"], [500.0, None], kwp=10.0, performance_ratio=0.8
    )
    assert slots == {"2026-10-29T10:00Z": 4.0}


def test_actual_slots_need_four_quarter_hours():
    rows = [
        {"closed_interval": {"interval_start": f"2026-10-29T12:{m:02d}:00", "pv_energy_kwh": 0.5}}
        for m in (0, 15, 30, 45)
    ] + [
        {"closed_interval": {"interval_start": "2026-10-29T13:00:00", "pv_energy_kwh": 0.5}},
        {"closed_interval": None},
    ]
    assert pfc.actual_slots(rows, VIENNA) == {"2026-10-29T11:00Z": 2.0}


def test_plant_runs_sum_systems_and_drop_incomplete_runs():
    records = [
        {"run_id": "2026-10-29T08:00:00+00:00", "source": "a", "system_id": "s", "kwh": {"k1": 1.0, "k2": 1.0}},
        {"run_id": "2026-10-29T08:00:00+00:00", "source": "a", "system_id": "n", "kwh": {"k1": 0.5}},
        {"run_id": "2026-10-29T09:00:00+00:00", "source": "a", "system_id": "s", "kwh": {"k1": 9.0}},
    ]
    runs = pfc.plant_runs(records, {"s", "n"})
    assert runs["a"] == [(datetime(2026, 10, 29, 8, tzinfo=timezone.utc), {"k1": 1.5})]


def test_latest_in_bucket_prefers_shortest_lead():
    slot = "2026-10-29T12:00Z"
    runs = [
        (datetime(2026, 10, 29, 2, tzinfo=timezone.utc), {slot: 1.0}),
        (datetime(2026, 10, 29, 8, tzinfo=timezone.utc), {slot: 2.0}),
        (datetime(2026, 10, 29, 11, tzinfo=timezone.utc), {slot: 3.0}),
    ]
    assert pfc.latest_in_bucket(runs, 0, 6) == {slot: 3.0}
    assert pfc.latest_in_bucket(runs, 6, 24) == {slot: 1.0}


def test_metrics_scale_removes_constant_bias():
    m = pfc.metrics([(2.0, 1.0), (4.0, 2.0)])
    assert m["bias"] == pytest.approx(1.5)
    assert m["scale"] == pytest.approx(0.5)
    assert m["mae_scaled"] == pytest.approx(0.0)


def test_daily_day_ahead_uses_last_run_before_local_midnight():
    day = date(2026, 10, 30)
    keys = pfc._day_slot_keys(day, VIENNA)
    early = {k: 1.0 for k in keys}
    late = {k: 2.0 for k in keys}
    runs = [
        (datetime(2026, 10, 29, 12, tzinfo=timezone.utc), early),
        (datetime(2026, 10, 29, 23, 30, tzinfo=timezone.utc), late),  # 00:30 local on the day itself
    ]
    assert pfc.daily_day_ahead(runs, day, VIENNA, LAT, LON) == pytest.approx(24.0)


def test_daily_day_ahead_counts_night_hours_a_run_leaves_out_as_zero():
    # forecast.solar in November: keys only from the sunrise hour to the sunset hour.
    day = date(2026, 11, 20)
    keys = pfc._day_slot_keys(day, VIENNA)
    daylight = [k for k in keys if pfc._is_daylight_hour(k, LAT, LON)]
    assert 7 <= len(daylight) <= 9
    run = (datetime(2026, 11, 19, 22, tzinfo=timezone.utc), {k: 1.0 for k in daylight})
    assert pfc.daily_day_ahead([run], day, VIENNA, LAT, LON) == pytest.approx(len(daylight))


def test_daily_day_ahead_rejects_a_run_without_a_daylight_hour():
    day = date(2026, 11, 20)
    keys = pfc._day_slot_keys(day, VIENNA)
    daylight = [k for k in keys if pfc._is_daylight_hour(k, LAT, LON)]
    run = (datetime(2026, 11, 19, 22, tzinfo=timezone.utc), {k: 1.0 for k in daylight[1:]})
    assert pfc.daily_day_ahead([run], day, VIENNA, LAT, LON) is None


def test_daylight_follows_the_sun_not_a_fixed_window():
    # 20 Nov: 06:00 local (05 UTC) is before sunrise, the sunrise hour 07:00 (06 UTC) is not
    # daylight for the whole hour; 12:00 local is.
    assert not pfc._is_daylight_hour("2026-11-20T05:00Z", LAT, LON)
    assert not pfc._is_daylight_hour("2026-11-20T06:00Z", LAT, LON)
    assert pfc._is_daylight_hour("2026-11-20T11:00Z", LAT, LON)


def test_solcast_sites_parsing():
    assert pfc._solcast_sites("dach_sued=aaaa-1, dach_nord=bbbb-2") == {
        "dach_sued": "aaaa-1",
        "dach_nord": "bbbb-2",
    }
    with pytest.raises(ValueError):
        pfc._solcast_sites("dach_sued")

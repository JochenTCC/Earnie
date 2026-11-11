"""Savings ledger v2, Ledger P10b: consumers without their own meter keep their logged timing (D6)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_flex as slf

TZ = ZoneInfo("Europe/Vienna")
DAY1 = datetime(2026, 11, 1, 7, 0, tzinfo=TZ)
STEP = timedelta(minutes=15)
BATTERY = {
    "battery_capacity_kwh": 10.0,
    "efficiency": 1.0,
    "min_soc": 10.0,
    "max_soc": 90.0,
    "max_power_kw": 2.0,
    "standby_power_kw": 0.0,
}
# A dryer Earnie controls but cannot measure: no key in closed_interval.flex_kw (spec § 7).
DRYER = {
    "id": "trockner",
    "nominal_power_kw": 2.0,
    "generic_flex_window": {"start_hour": 18, "start_shift_h": 0, "duration_h": 2},
}
HP = {"id": "wp", "nominal_power_kw": 3.0, "daily_target_source": "thermal_annual"}


def day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    start = moment.replace(hour=7, minute=0, second=0, microsecond=0)
    if moment < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def _closed(i: int, flex_kw: dict[str, float]) -> dict:
    pv = 3.0 if 16 <= i < 40 else 0.0
    dryer = 2.0 if 20 <= i < 28 else 0.0  # ran at noon; only in the house load
    house = 0.5 + dryer + sum(flex_kw.values())
    return {
        "sample_count": 30,
        "pv_kw": pv,
        "grid_kw": house - pv,
        "battery_kw": 0.0,
        "house_kw": house,
        "soc_start_percent": 50.0,
        "soc_end_percent": 50.0,
        "flex_kw": flex_kw,
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
    }


def _inputs(flex) -> list[sl.LedgerInput]:
    inputs = []
    for day in range(2):
        for i in range(96):
            start = DAY1 + timedelta(days=day) + i * STEP
            inputs.append(sl.LedgerInput(start, _closed(i, flex(i)), 35.0 if 44 <= i < 52 else 25.0, 8.0))
    inputs.append(sl.LedgerInput(DAY1 + timedelta(days=2), _closed(0, flex(0)), 25.0, 8.0))
    return inputs


def _run(inputs, *, savings_v, consumers, profiles):
    def day_flex(state: sl.LedgerState) -> slf.FlexDayInputs:
        n = len(state.slots)
        return slf.FlexDayInputs(
            consumers=consumers,
            profiles_kw={cid: profile(state, n) for cid, profile in profiles.items()},
            windows={c["id"]: slf.ConsumerWindows(enable_slots=None, native_slots=None) for c in consumers},
        )

    state = sl.start_chain(inputs[0], day_bounds, reason=sl.CHAIN_FIRST_RUN, savings_v=savings_v)
    closes = []
    for inp in inputs:
        state, closed_day = sl.advance_with_slots(
            state, inp, BATTERY, day_bounds, app_version="test", day_flex=day_flex
        )
        if closed_day is not None:
            closes.append(closed_day)
    return closes


_V2_ONLY = {
    "savings_v",
    "flex_retimed_kwh",
    "flex_timing",
    "flex_logged_reasons",
    "flex_native_window_source",
    "saving_logged_timing_eur",
    "fuel_saved_kwh",
    "fuel_saved_eur",
}


def _flat_profile(state, n):
    return [1.0] * n


def test_consumer_without_meter_changes_nothing_against_v1_and_is_named():
    inputs = _inputs(lambda i: {})
    v1 = _run(inputs, savings_v=1, consumers=[DRYER], profiles={})
    v2 = _run(inputs, savings_v=2, consumers=[DRYER], profiles={"trockner": _flat_profile})

    assert len(v1) == len(v2) == 2
    for v1_day, v2_day in zip(v1, v2):
        assert {k: v for k, v in v2_day.row.items() if k not in _V2_ONLY} == {
            k: v for k, v in v1_day.row.items() if k != "savings_v"
        }
        assert v2_day.row["flex_timing"] == {"trockner": slf.TIMING_LOGGED_NO_METER}
        assert v2_day.row["flex_logged_reasons"] == {}
        assert v2_day.row["saving_eur"] == v2_day.row["saving_logged_timing_eur"]
        assert sl.day_slots_record(v2_day.closing)["slots"] == sl.day_slots_record(v1_day.closing)["slots"]


def test_unmetered_consumer_beside_a_retimed_one_keeps_its_energy_in_place():
    """Only the metered heat pump moves; the dryer's 4 kWh at noon stay in the shadow load."""
    evening = lambda state, n: [1.0 if 44 <= i < 52 else 0.0 for i in range(n)]  # noqa: E731
    flex = lambda i: {"wp": 2.0 if 24 <= i < 28 else 0.0}  # noqa: E731
    v2 = _run(_inputs(flex), savings_v=2, consumers=[DRYER, HP], profiles={"trockner": _flat_profile, "wp": evening})

    row = v2[0].row
    assert row["flex_timing"] == {"trockner": slf.TIMING_LOGGED_NO_METER, "wp": slf.TIMING_PROFILE}
    assert row["flex_retimed_kwh"] == {"wp": 2.0}
    assert "trockner" not in row["flex_delivered_kwh"]
    sl.check_day_slots(row, sl.day_slots_record(v2[0].closing))
    # Shadow load per slot, replayed without battery so grid = load − pv shows it directly:
    slots = v2[0].closing.slots
    retimed = slf.retime_flex_day(
        slots,
        [DRYER, HP],
        {"trockner": [1.0] * len(slots), "wp": evening(None, len(slots))},
        {c["id"]: slf.ConsumerWindows(None, None) for c in (DRYER, HP)},
        dt_h=0.25,
    )
    no_battery, _ = sl.replay_day(slots, None, None, retimed.per_slot_kw, dt_h=0.25)
    # 12:00, dryer only: 0.5 + 2 − 3 kW PV → 0.125 kWh export; the dryer stays in the load
    assert no_battery[20]["export_kwh_without"] == pytest.approx(0.125)
    # 13:00, dryer and heat pump ran: the heat pump moved away, the dryer stays → 0.5 + 2 − 3
    assert no_battery[24]["export_kwh_without"] == pytest.approx(0.125)
    # 18:00: the heat pump's 2 kWh over the 8 profile slots → 0.5 + 1 kW import
    assert no_battery[44]["import_kwh_without"] == pytest.approx(0.375)

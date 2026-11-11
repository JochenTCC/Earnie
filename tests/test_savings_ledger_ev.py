"""Savings ledger v2, Ledger P10a: EV charged from plug-in in the day replay (plan § 4.3, D5)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_flex as slf
from runtime_store import savings_ledger_store as store

TZ = ZoneInfo("Europe/Vienna")
DAY1 = datetime(2026, 11, 1, 7, 0, tzinfo=TZ)
STEP = timedelta(minutes=15)
DT = 0.25
N = 96
EV = {"id": "auto", "type": "ev", "nominal_power_kw": 11.0}
PLUG_18 = 44  # 18:00 in a day from 07:00
NIGHT = range(76, 88)  # 02:00–05:00, where Earnie charged
EVENING = range(44, 56)  # 18:00–21:00


def day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    start = moment.replace(hour=7, minute=0, second=0, microsecond=0)
    if moment < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def _rows(charge_kw: dict[int, float], plugged: dict[int, bool | None]) -> list[dict]:
    """Slot rows of one day; ``plugged[i] is None`` leaves the plug state out of slot ``i``."""
    rows = []
    for i in range(N):
        row = {"counted": True, "flex_delivered_kwh": {"auto": charge_kw.get(i, 0.0) * DT}}
        state = plugged.get(i, False)
        if state is not None:
            row["plugged_in"] = {"auto": state}
        rows.append(row)
    return rows


def _windows() -> dict[str, slf.ConsumerWindows]:
    return {"auto": slf.ConsumerWindows(enable_slots=None, native_slots=None)}


def _kw(result: slf.FlexRetiming) -> list[float]:
    return [slot["auto"] for slot in result.per_slot_kw]


def test_car_plugged_at_18_charged_at_night_is_charged_from_18_in_the_reference():
    rows = _rows({i: 11.0 for i in NIGHT}, {i: True for i in range(PLUG_18, N)})
    result = slf.retime_flex_day(rows, [EV], {}, _windows(), dt_h=DT)
    assert result.timing == {"auto": slf.TIMING_PLUG_IN}
    assert _kw(result) == pytest.approx([11.0 if i in EVENING else 0.0 for i in range(N)])
    assert sum(_kw(result)) * DT == pytest.approx(33.0)


def test_session_across_the_sa_boundary_is_retimed_per_day():
    """D5: plugged in at 03:00 of day N, charged 05:00–08:00. Day N's energy from 03:00; day N+1's
    energy starts at its first slot (the car is still plugged in), which is where it charged."""
    day_n = _rows({i: 11.0 for i in range(88, 96)}, {i: True for i in range(80, N)})
    day_n1 = _rows({i: 11.0 for i in range(0, 4)}, {i: i < 4 for i in range(N)})
    ref_n = slf.retime_flex_day(day_n, [EV], {}, _windows(), dt_h=DT)
    ref_n1 = slf.retime_flex_day(day_n1, [EV], {}, _windows(), dt_h=DT)
    assert _kw(ref_n) == pytest.approx([11.0 if 80 <= i < 88 else 0.0 for i in range(N)])
    assert _kw(ref_n1) == pytest.approx([11.0 if i < 4 else 0.0 for i in range(N)])


def test_slot_charged_while_the_plug_read_false_still_counts_as_plugged():
    """The plug state is read when the cycle starts; a car plugged in during the slot reads False there."""
    rows = _rows({60: 4.0, 61: 11.0}, {60: False, 61: True})
    result = slf.retime_flex_day(rows, [EV], {}, _windows(), dt_h=DT)
    assert result.timing == {"auto": slf.TIMING_PLUG_IN}
    assert _kw(result)[60] == pytest.approx(11.0)
    assert _kw(result)[61] == pytest.approx(4.0)


def test_unplugged_slots_are_skipped_by_the_reference():
    # plugged 18:00–19:00 and again 23:00–24:00; charged 23:00–24:00 at 11 kW (11 kWh)
    plugged = {i: True for i in [*range(44, 48), *range(64, 68)]}
    rows = _rows({i: 11.0 for i in range(64, 68)}, plugged)
    result = slf.retime_flex_day(rows, [EV], {}, _windows(), dt_h=DT)
    expected = [11.0 if 44 <= i < 48 else 0.0 for i in range(N)]
    assert _kw(result) == pytest.approx(expected)


def test_day_without_plug_state_keeps_the_logged_timing():
    rows = _rows({i: 11.0 for i in NIGHT}, {i: None for i in range(N)})
    result = slf.retime_flex_day(rows, [EV], {}, _windows(), dt_h=DT)
    assert result.timing == {"auto": slf.TIMING_LOGGED_NO_PLUG_STATE}
    assert result.logged_reasons == {}
    assert _kw(result) == [11.0 if i in NIGHT else 0.0 for i in range(N)]


def test_more_energy_than_the_plugged_slots_hold_keeps_the_logged_timing():
    rows = _rows({i: 11.0 for i in NIGHT}, {i: i in NIGHT for i in range(N)} | {80: True})
    rows[76]["flex_delivered_kwh"]["auto"] = 20.0  # 80 kW in one slot: more than nominal
    result = slf.retime_flex_day(rows, [EV], {}, _windows(), dt_h=DT)
    assert result.logged_reasons == {"auto": slf.REASON_EXCEEDS_ELIGIBLE}


# --- through the log, the slot rows and the replay -------------------------------------


def _closed(ev_kw: float) -> dict:
    house = 0.5 + ev_kw
    return {
        "sample_count": 30,
        "pv_kw": 0.0,
        "grid_kw": house,
        "battery_kw": 0.0,
        "house_kw": house,
        "soc_start_percent": 50.0,
        "soc_end_percent": 50.0,
        "flex_kw": {"auto": ev_kw},
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
    }


def _price(i: int) -> float:
    return 35.0 if i in EVENING else 20.0


def test_plug_state_flows_from_the_entry_to_the_hand_computed_saving():
    entries = []
    for i in range(N):
        plugged = i >= PLUG_18
        entries.append(
            {
                "k_push_act": 8.0,
                "market_price_cent": _price(i),
                "charging_contexts": {"auto": {"plugged_in": plugged, "active": plugged}, "pool_ev": {"active": False}},
            }
        )
    inputs = []
    for i, entry in enumerate(entries):
        start = DAY1 + i * STEP
        pending = store.pending_slot_from_entry(start, entry)
        inputs.append(store.ledger_input_from_pending(start, _closed(11.0 if i in NIGHT else 0.0), pending))
    assert inputs[PLUG_18].plugged_in == {"auto": True}
    assert inputs[0].plugged_in == {"auto": False}
    inputs.append(sl.LedgerInput(DAY1 + timedelta(days=1), _closed(0.0), 20.0, 8.0))

    def day_flex(state):
        return slf.FlexDayInputs(consumers=[EV], profiles_kw={}, windows=_windows())

    state = sl.start_chain(inputs[0], day_bounds, reason=sl.CHAIN_FIRST_RUN, savings_v=2, with_battery=False)
    closes = []
    for inp in inputs:
        state, closed_day = sl.advance_with_slots(state, inp, None, day_bounds, app_version="t", day_flex=day_flex)
        if closed_day is not None:
            closes.append(closed_day)
    row = closes[0].row
    assert closes[0].closing.slots[PLUG_18]["plugged_in"] == {"auto": True}
    assert row["flex_timing"] == {"auto": slf.TIMING_PLUG_IN}
    # 33 kWh at 35 ct from plug-in instead of 20 ct at night: 33 · 0.15 = 4.95 EUR
    assert row["saving_eur"] == pytest.approx(4.95, abs=1e-9)
    sl.check_day_slots(row, sl.day_slots_record(closes[0].closing))


def test_backfill_keeps_the_charging_contexts():
    from scripts import build_savings_ledger as cli

    entry = {"completed_at": "2026-11-01T07:00:00", "charging_contexts": {"auto": {"plugged_in": True}}}
    assert cli._slim(entry)["charging_contexts"] == {"auto": {"plugged_in": True}}

"""Savings ledger v2, Ledger P9c: day replay with re-timed flex (plan savings-ledger-v2-plan.md § 4.1)."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_flex as slf
from runtime_store import savings_ledger_store as store

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
HP = {"id": "wp", "nominal_power_kw": 3.0, "daily_target_source": "thermal_annual"}
CHEAP = range(20, 24)  # 12:00–13:00, where Earnie ran the heat pump
EVENING = range(44, 48)  # 18:00–19:00, the heat pump's profile


def day_bounds(moment: datetime) -> tuple[datetime, datetime]:
    start = moment.replace(hour=7, minute=0, second=0, microsecond=0)
    if moment < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def _closed(*, pv=0.0, base=0.5, flex=None, battery=0.0, soc=50.0) -> dict:
    flex = {} if flex is None else flex
    house = base + sum(flex.values())
    return {
        "sample_count": 30,
        "pv_kw": pv,
        "grid_kw": house - pv - battery,
        "battery_kw": battery,
        "house_kw": house,
        "soc_start_percent": soc,
        "soc_end_percent": soc,
        "flex_kw": flex,
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
    }


def _price(index: int) -> float:
    if index in CHEAP:
        return 10.0
    if index in EVENING:
        return 40.0
    return 30.0


def _shifted_day(start: datetime, *, pv=None) -> list[sl.LedgerInput]:
    """96 slots: base 0.5 kW, heat pump 2 kW in the cheap hour (2 kWh), metered all day."""
    inputs = []
    for i in range(96):
        flex = {"wp": 2.0 if i in CHEAP else 0.0}
        closed = _closed(pv=(pv or (lambda _i: 0.0))(i), flex=flex)
        inputs.append(sl.LedgerInput(start + i * STEP, closed, _price(i), 8.0))
    return inputs


def _closing_slot(start: datetime) -> sl.LedgerInput:
    return sl.LedgerInput(start, _closed(flex={"wp": 0.0}), 30.0, 8.0)


def _evening_flex(state: sl.LedgerState) -> slf.FlexDayInputs:
    """Profile 1 kW 18:00–19:00 local, no window; aligned with the state's slot rows."""
    profile = []
    for slot in state.slots:
        index = int((datetime.fromisoformat(slot["slot_start"]) - state.day_start) / STEP)
        profile.append(1.0 if index in EVENING else 0.0)
    return slf.FlexDayInputs(
        consumers=[HP],
        profiles_kw={"wp": profile},
        windows={"wp": slf.ConsumerWindows(enable_slots=None, native_slots=None)},
    )


def _no_flex(_state: sl.LedgerState) -> slf.FlexDayInputs:
    return slf.FlexDayInputs(consumers=[], profiles_kw={}, windows={})


def _run(inputs, battery, day_flex, *, savings_v, with_battery=True):
    state = sl.start_chain(
        inputs[0], day_bounds, reason=sl.CHAIN_FIRST_RUN, savings_v=savings_v, with_battery=with_battery
    )
    closes = []
    for inp in inputs:
        state, closed_day = sl.advance_with_slots(
            state, inp, battery, day_bounds, app_version="test", day_flex=day_flex
        )
        if closed_day is not None:
            closes.append(closed_day)
    return state, closes


# --- hand-computed saving --------------------------------------------------------


def test_moved_consumer_without_battery_gives_the_hand_computed_saving():
    inputs = _shifted_day(DAY1) + [_closing_slot(DAY1 + timedelta(days=1))]
    state, closes = _run(inputs, None, _evening_flex, savings_v=2, with_battery=False)

    (closed,) = closes
    row = closed.row
    # Without Earnie the 2 kWh run at 40 ct instead of 10 ct: 2 · (0.40 − 0.10) = 0.60 EUR.
    assert row["saving_eur"] == pytest.approx(0.60, abs=1e-9)
    assert row["saving_adjusted_eur"] == pytest.approx(0.60, abs=1e-9)
    assert row["saving_logged_timing_eur"] == 0.0
    assert row["flex_timing"] == {"wp": slf.TIMING_PROFILE}
    assert row["flex_retimed_kwh"] == {"wp": 2.0} == row["flex_delivered_kwh"]
    assert row["flex_logged_reasons"] == {}
    assert row["savings_v"] == 2
    # no battery: no SoC correction
    assert row["p_ref_basis"] == sl.P_REF_NO_BATTERY
    assert row["soc_correction_eur"] == 0.0 and row["soc_correction_prev_eur"] == 0.0
    assert row["soc_shadow_end_pct"] is None and row["p_ref_cent"] is None
    assert state.shadow_soc is None and state.shadow_soc_day_start is None
    sl.check_day_slots(row, sl.day_slots_record(closed.closing))


def test_replayed_slots_add_up_to_the_row_with_battery():
    pv = lambda i: 3.0 if 16 <= i < 40 else 0.0  # noqa: E731 — midday PV
    inputs = _shifted_day(DAY1, pv=pv) + _shifted_day(DAY1 + timedelta(days=1), pv=pv)
    inputs.append(_closing_slot(DAY1 + timedelta(days=2)))
    state, closes = _run(inputs, BATTERY, _evening_flex, savings_v=2)

    assert len(closes) == 2
    for closed in closes:
        record = sl.day_slots_record(closed.closing)
        sl.check_day_slots(closed.row, record)
        assert closed.row["soc_shadow_end_pct"] == round(closed.chain_soc, 2)
    # the chain continues from the replay's end SoC, causal and day-start SoC alike
    assert closes[1].closing.shadow_soc_day_start == closes[0].chain_soc
    assert state.shadow_soc_day_start == closes[1].chain_soc
    # moving the heat pump out of the cheap PV hour into the evening costs the shadow plant more
    assert closes[0].row["saving_eur"] > closes[0].row["saving_logged_timing_eur"]


def test_logged_timing_saving_equals_the_causal_day():
    """D4: the replay on the logged timing from the day's start SoC is the causal day, to the bit."""
    pv = lambda i: 3.0 if 16 <= i < 40 else 0.0  # noqa: E731
    inputs = _shifted_day(DAY1, pv=pv) + [_closing_slot(DAY1 + timedelta(days=1))]
    _, v1_rows = _run_v1(inputs)
    _, closes = _run(inputs, BATTERY, _evening_flex, savings_v=2)
    assert closes[0].row["saving_logged_timing_eur"] == v1_rows[0]["saving_eur"]


def _run_v1(inputs):
    state = sl.start_chain(inputs[0], day_bounds, reason=sl.CHAIN_FIRST_RUN, savings_v=1)
    rows = []
    for inp in inputs:
        state, row = sl.advance(state, inp, BATTERY, day_bounds, app_version="test")
        if row is not None:
            rows.append(row)
    return state, rows


# --- no flex: v2 equals v1 to the cent --------------------------------------------

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


@pytest.mark.parametrize("day_flex", [_no_flex, lambda s: replace(_evening_flex(s), profiles_kw={})])
def test_day_without_retimed_flex_equals_the_v1_row(day_flex):
    """No consumer, or a consumer without shape and window (logged timing): the v1 row, two days."""
    pv = lambda i: 3.0 if 16 <= i < 40 else 0.0  # noqa: E731
    inputs = _shifted_day(DAY1, pv=pv) + _shifted_day(DAY1 + timedelta(days=1), pv=pv)
    inputs.append(_closing_slot(DAY1 + timedelta(days=2)))
    v1_state, v1_closes = _run(inputs, BATTERY, None, savings_v=1)
    v2_state, closes = _run(inputs, BATTERY, day_flex, savings_v=2)

    assert len(v1_closes) == len(closes) == 2
    for v1_closed, closed in zip(v1_closes, closes):
        v1_row = v1_closed.row
        v2_row = {k: v for k, v in closed.row.items() if k not in _V2_ONLY}
        assert v2_row == {k: v for k, v in v1_row.items() if k != "savings_v"}
        assert closed.row["saving_logged_timing_eur"] == v1_row["saving_eur"]
        assert closed.row["fuel_saved_kwh"] == closed.row["fuel_saved_eur"] == 0.0
        v1_slots = sl.day_slots_record(v1_closed.closing)["slots"]
        assert sl.day_slots_record(closed.closing)["slots"] == v1_slots
    assert v2_state.shadow_soc == v1_state.shadow_soc


@pytest.mark.parametrize(
    "house_consumers",
    [
        None,  # no active house profile
        [{"id": "wp", "type": "generic", "nominal_power_kw": 1.0, "schedule": {"start_hour": "x", "duration_h": 1}}],
    ],
)
def test_missing_house_profile_or_broken_model_keeps_the_logged_timing(house_consumers):
    def day_flex(state):
        return store.flex_day_inputs(state, [HP], house_consumers, "Europe/Vienna")

    inputs = _shifted_day(DAY1) + [_closing_slot(DAY1 + timedelta(days=1))]
    _, closes = _run(inputs, None, day_flex, savings_v=2, with_battery=False)
    row = closes[0].row
    assert row["flex_timing"] == {"wp": slf.TIMING_LOGGED}
    assert row["flex_logged_reasons"] == {"wp": slf.REASON_PROFILE_ERROR}
    assert row["saving_eur"] == 0.0


# --- inputs and state --------------------------------------------------------------


def _house_generic(cid: str, start_hour: int, nominal_kw: float) -> dict:
    """A house-profile consumer whose model runs once a week at ``start_hour`` (1 h)."""
    return {
        "id": cid,
        "type": "generic",
        "nominal_power_kw": nominal_kw,
        "schedule": {"start_hour": start_hour, "duration_h": 1.0, "runs_per_week": 1},
    }


def test_flex_day_inputs_take_the_house_model_in_local_time():
    """D8: the shape is the house profile's model, at the configured start on every day.

    2026-11-01 is a Sunday; with one run a week the model has no run that day, but the
    reference only needs the timing. 18:00 Vienna = 17:00 UTC.
    """
    utc = timezone.utc
    slots = (
        {"slot_start": datetime(2026, 11, 1, 16, 45, tzinfo=utc).isoformat(), "counted": True},
        {"slot_start": datetime(2026, 11, 1, 17, 0, tzinfo=utc).isoformat(), "counted": True},
    )
    state = sl.LedgerState(
        savings_v=2,
        chain_start=DAY1,
        chain_start_reason=sl.CHAIN_FIRST_RUN,
        shadow_soc=None,
        day_start=DAY1,
        day_end=DAY1 + timedelta(days=1),
        last_slot_start=None,
        soc_actual_end=None,
        prev_correction_eur=None,
        slots=slots,
    )
    hp = HP | {"thermal_flex_window": {"start_hour": 18, "duration_h": 2}}
    inputs = store.flex_day_inputs(state, [hp], [_house_generic("wp", 18, 1.5)], "Europe/Vienna")
    assert inputs.profiles_kw == {"wp": [0.0, 1.5]}
    assert inputs.windows["wp"].enable_slots == frozenset({1})


def test_flex_day_inputs_skip_evs_and_consumers_without_a_model():
    ev = {"id": "auto", "type": "ev", "nominal_power_kw": 11.0}
    slots = ({"slot_start": DAY1.isoformat(), "counted": True},)
    state = sl.LedgerState(
        savings_v=2,
        chain_start=DAY1,
        chain_start_reason=sl.CHAIN_FIRST_RUN,
        shadow_soc=None,
        day_start=DAY1,
        day_end=DAY1 + timedelta(days=1),
        last_slot_start=None,
        soc_actual_end=None,
        prev_correction_eur=None,
        slots=slots,
    )
    house = [_house_generic("auto", 7, 11.0)]
    inputs = store.flex_day_inputs(state, [HP, ev], house, "Europe/Vienna")
    assert inputs.profiles_kw == {}


def test_v2_day_close_needs_the_flex_inputs():
    inputs = _shifted_day(DAY1) + [_closing_slot(DAY1 + timedelta(days=1))]
    with pytest.raises(ValueError, match="day_flex"):
        _run(inputs, BATTERY, None, savings_v=2)


def test_chain_without_battery_needs_v2():
    with pytest.raises(ValueError, match="savings_v"):
        sl.start_chain(
            _closing_slot(DAY1), day_bounds, reason=sl.CHAIN_FIRST_RUN, savings_v=1, with_battery=False
        )


def test_state_round_trip_keeps_the_day_start_soc():
    inputs = _shifted_day(DAY1)[:3]
    v2, _ = _run(inputs, BATTERY, _evening_flex, savings_v=2)
    raw = v2.to_dict()
    assert raw["shadow_soc_day_start"] == 50.0
    assert sl.LedgerState.from_dict(raw) == v2
    no_battery, _ = _run(inputs, None, _evening_flex, savings_v=2, with_battery=False)
    assert sl.LedgerState.from_dict(no_battery.to_dict()) == no_battery
    raw.pop("shadow_soc_day_start")
    with pytest.raises(KeyError):
        sl.LedgerState.from_dict(raw)
    v1, _ = _run_v1(inputs)
    assert "shadow_soc_day_start" not in v1.to_dict()


def test_open_day_figures_stay_causal_in_v2():
    """D2: ``close_day`` on the open day uses the causal slots, not the replay."""
    inputs = _shifted_day(DAY1)[:40]
    v2, _ = _run(inputs, BATTERY, _evening_flex, savings_v=2)
    v1, _ = _run_v1(inputs)
    v2_row = sl.close_day(v2, BATTERY, app_version="test")
    v1_row = sl.close_day(v1, BATTERY, app_version="test")
    assert v2_row["saving_eur"] == v1_row["saving_eur"]


@pytest.mark.parametrize(
    ("utc_day", "start_hour", "expected"),
    [
        # 2026-10-25, end of summer time: 00:00–01:45 UTC are 02:00 CEST and 02:00 CET again
        (datetime(2026, 10, 25, tzinfo=timezone.utc), 2, [2.0] * 8),
        # 2027-03-28, start of summer time: 00:00–00:45 UTC = 01:00 CET, 01:00–01:45 UTC = 03:00 CEST
        (datetime(2027, 3, 28, tzinfo=timezone.utc), 3, [0.0] * 4 + [2.0] * 4),
    ],
)
def test_flex_day_inputs_follow_the_wall_clock_across_dst(utc_day, start_hour, expected):
    slots = tuple(
        {"slot_start": (utc_day + i * STEP).isoformat(), "counted": True} for i in range(8)
    )
    state = sl.LedgerState(
        savings_v=2,
        chain_start=utc_day,
        chain_start_reason=sl.CHAIN_FIRST_RUN,
        shadow_soc=None,
        day_start=utc_day,
        day_end=utc_day + timedelta(days=1),
        last_slot_start=None,
        soc_actual_end=None,
        prev_correction_eur=None,
        slots=slots,
    )
    inputs = store.flex_day_inputs(state, [HP], [_house_generic("wp", start_hour, 2.0)], "Europe/Vienna")
    assert inputs.profiles_kw == {"wp": expected}


# --- native filter window from the log -------------------------------------------

POOL = {
    "id": "pool",
    "nominal_power_kw": 0.2,
    "filter_schedule": {"enabled": True, "config_fallback": {"native_start_hour": 10, "native_duration_hours": 2}},
}


def test_logged_filter_window_flows_from_the_entry_into_the_row(tmp_path):
    entry = {
        "k_push_act": 8.0,
        "market_price_cent": 30.0,
        "filter_contexts": {
            "pool": {"native_start_hour": 14, "native_duration_hours": 1, "source_label": "loxone"},
            "half": {"native_start_hour": None, "native_duration_hours": 2, "source_label": "unbekannt"},
        },
    }
    pending = store.pending_slot_from_entry(DAY1, entry)
    assert pending["filter_native"] == {"pool": {"native_start_hour": 14.0, "native_duration_hours": 1.0}}

    # pool ran 10:00–11:00 (Earnie); the logged native window is 14:00–15:00 = slots 28–31
    inputs = []
    for i in range(96):
        closed = _closed(flex={"pool": 0.2 if 12 <= i < 16 else 0.0})
        inp = store.ledger_input_from_pending(DAY1 + i * STEP, closed, {**pending, "slot_start": (DAY1 + i * STEP).isoformat()})
        inputs.append(inp)
    inputs.append(_closing_slot(DAY1 + timedelta(days=1)))

    def from_config(state):
        return store.flex_day_inputs(state, [POOL], [], "Europe/Vienna")

    state, closes = _run(inputs, None, from_config, savings_v=2, with_battery=False)
    closed = closes[0]
    assert closed.closing.slots[0]["filter_native"] == {"pool": {"native_start_hour": 14.0, "native_duration_hours": 1.0}}
    assert closed.row["flex_timing"] == {"pool": slf.TIMING_NATIVE_WINDOW}
    assert closed.row["flex_native_window_source"] == {"pool": slf.NATIVE_SOURCE_LOG}
    replayed = closed.closing.slots
    base_cost = 0.5 * 0.25 * 0.30
    assert [round(replayed[i]["cost_without_eur"] - base_cost, 9) > 0 for i in range(96)] == [
        28 <= i < 32 for i in range(96)
    ]


def test_day_without_logged_filter_window_uses_the_configured_one(tmp_path):
    inputs = [
        sl.LedgerInput(DAY1 + i * STEP, _closed(flex={"pool": 0.2 if 12 <= i < 16 else 0.0}), 30.0, 8.0)
        for i in range(96)
    ] + [_closing_slot(DAY1 + timedelta(days=1))]

    def from_config(state):
        return store.flex_day_inputs(state, [POOL], [], "Europe/Vienna")

    _, closes = _run(inputs, None, from_config, savings_v=2, with_battery=False)
    assert closes[0].row["flex_native_window_source"] == {"pool": slf.NATIVE_SOURCE_CONFIG}
    assert "filter_native" not in closes[0].closing.slots[0]


def test_backfill_keeps_the_logged_filter_window():
    from scripts import build_savings_ledger as cli

    entry = {"completed_at": "2026-11-01T07:00:00", "filter_contexts": {"pool": {"native_start_hour": 14}}, "noise": 1}
    assert cli._slim(entry)["filter_contexts"] == {"pool": {"native_start_hour": 14}}
    assert "noise" not in cli._slim(entry)

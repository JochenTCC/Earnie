"""Chart 2's slots left of Jetzt come from the savings ledger (Ledger P7, Account view P2)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from ui import chart_ledger_savings as cls
from ui.chart_account_view import (
    SLOT_COUNTED,
    SLOT_NO_DATA,
    SLOT_PENDING,
    SLOT_PLAN,
    SLOT_SKIPPED,
)

_TZ = ZoneInfo("Europe/Vienna")
_QUARTER = timedelta(minutes=15)
_DAY_START = datetime(2026, 11, 4, 7, 9, 9, tzinfo=_TZ)
_DAY_END = datetime(2026, 11, 5, 7, 10, 39, tzinfo=_TZ)
_BATTERY = {"battery_capacity_kwh": 15.0, "efficiency": 0.94}


def _slot(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 4, hour, minute, tzinfo=_TZ)


def _booked(start: datetime, *, with_eur: float, without_eur: float, counted: bool = True) -> dict:
    return {
        "slot_start": start.isoformat(),
        "counted": counted,
        "skip_reason": None if counted else sl.SKIP_NO_PRICE,
        "cost_with_eur": with_eur,
        "cost_without_eur": without_eur,
        "import_kwh_with": with_eur * 2.0,
        "import_kwh_without": without_eur * 2.0,
        "export_kwh_with": 0.0,
        "export_kwh_without": 0.0,
        "k_act_cent": 40.0,
        "shadow_soc_end": 20.0,
    }


def _state(*slots: dict, soc_actual_end: float | None = 30.0, prev: float | None = 0.25):
    return sl.LedgerState(
        savings_v=sl.SAVINGS_V,
        chain_start=_DAY_START,
        chain_start_reason=sl.CHAIN_FIRST_RUN,
        shadow_soc=20.0,
        day_start=_DAY_START,
        day_end=_DAY_END,
        last_slot_start=datetime.fromisoformat(slots[-1]["slot_start"]) if slots else None,
        soc_actual_end=soc_actual_end,
        prev_correction_eur=prev,
        slots=tuple(slots),
    )


def _build(state, slots, history, rows=()):
    return cls.build_ledger_chart_savings(
        slots,
        history,
        state,
        _BATTERY,
        rows,
        window_start=_DAY_START,
        window_end=_DAY_END,
    )


def test_slots_carry_with_and_without_and_the_open_day_waits_after_the_last_booked_slot():
    slots = [_slot(8) + _QUARTER * index for index in range(6)]
    state = _state(
        _booked(slots[0], with_eur=0.10, without_eur=0.30),
        _booked(slots[1], with_eur=0.20, without_eur=0.10),
        _booked(slots[2], with_eur=0.05, without_eur=0.05, counted=False),
    )

    ledger = _build(state, slots, history=5)

    assert ledger["slot_with_eur"][:2] == pytest.approx([0.10, 0.20])
    assert ledger["slot_without_eur"][:2] == pytest.approx([0.30, 0.10])
    assert ledger["slot_states"] == [
        SLOT_COUNTED, SLOT_COUNTED, SLOT_SKIPPED, SLOT_PENDING, SLOT_PENDING, SLOT_PLAN
    ]
    # A skipped slot counts as zero on both sides.
    assert ledger["slot_with_eur"][2] == 0.0 and ledger["slot_without_eur"][2] == 0.0


def test_a_gap_before_the_last_booked_slot_has_no_data():
    slots = [_slot(8) + _QUARTER * index for index in range(3)]
    state = _state(
        _booked(slots[0], with_eur=0.0, without_eur=0.2),
        _booked(slots[2], with_eur=0.0, without_eur=0.1),
    )

    states = _build(state, slots, history=3)["slot_states"]

    assert states == [SLOT_COUNTED, SLOT_NO_DATA, SLOT_COUNTED]


def test_closed_day_slots_come_from_the_slot_file_records():
    earlier = _DAY_START - timedelta(hours=1)
    booked = _slot(8)
    state = _state(_booked(booked, with_eur=0.0, without_eur=0.2))
    closed = {"yesterday": [_booked(earlier, with_eur=0.3, without_eur=0.5)]}

    ledger = cls.build_ledger_chart_savings(
        [earlier - _QUARTER, earlier, booked], 3, state, _BATTERY, [],
        window_start=_DAY_START - timedelta(days=1), window_end=_DAY_END, closed_slots=closed,
    )

    assert ledger["slot_states"] == [SLOT_NO_DATA, SLOT_COUNTED, SLOT_COUNTED]
    assert ledger["slot_without_eur"] == pytest.approx([0.0, 0.5, 0.2])


def test_soc_correction_is_the_day_rows_change_against_the_previous_day():
    slots = [_slot(8)]
    state = _state(_booked(slots[0], with_eur=0.5, without_eur=0.7), soc_actual_end=30.0, prev=0.25)
    # (30 − 20) % · 15 kWh · 0.94 at 40 ct = 0,564 €; minus the 0,25 € carried in.
    ledger = _build(state, slots, history=1)

    assert ledger["saving_euro"] == pytest.approx(0.2)
    assert ledger["soc_correction_euro"] == pytest.approx(0.564 - 0.25)
    assert ledger["hint"] is None


def test_result_is_json_safe_for_debug_dumps():
    slots = [_slot(8)]
    state = _state(_booked(slots[0], with_eur=0.1, without_eur=0.2))

    json.dumps(_build(state, slots, history=1))


def test_window_without_any_data_gives_the_hint():
    state = _state(_booked(_slot(8), with_eur=0.1, without_eur=0.2))
    other_day = [_DAY_START - timedelta(days=2)]

    ledger = _build(state, other_day, history=1)

    assert ledger["hint"] == cls.HINT_NO_DATA


def test_closed_days_in_the_window_keep_their_result_and_incomplete_flag():
    yesterday = _DAY_START - timedelta(days=1)
    row = {
        "day_start": yesterday.isoformat(),
        "day_end": _DAY_START.isoformat(),
        "saving_adjusted_eur": -0.4,
        "incomplete": True,
    }
    state = _state(_booked(_slot(8), with_eur=0.5, without_eur=0.7), prev=0.25)
    outside = {
        **row,
        "day_start": "2026-10-31T07:00:00+01:00",
        "day_end": "2026-11-01T07:00:00+01:00",
    }
    ledger = cls.build_ledger_chart_savings(
        [_slot(8)],
        1,
        state,
        _BATTERY,
        [outside, row],
        window_start=yesterday,
        window_end=_DAY_END,
    )

    assert ledger["closed_days"] == [{
        "day_start": yesterday.isoformat(),
        "day_end": _DAY_START.isoformat(),
        "saving_adjusted_eur": -0.4,
        "incomplete": True,
    }]
    assert ledger["saving_euro"] == pytest.approx(0.2)


def test_peek_state_leaves_an_unreadable_file_in_place(tmp_path):
    path = tmp_path / "savings_ledger_state.json"
    path.write_text("{broken", encoding="utf-8")

    loaded = store.peek_state(str(path))

    assert loaded.state is None
    assert loaded.restart_reason == sl.CHAIN_STATE_UNREADABLE
    assert path.read_text(encoding="utf-8") == "{broken"
    assert list(tmp_path.iterdir()) == [path]


def test_peek_state_reads_what_the_daemon_wrote(tmp_path):
    path = tmp_path / "savings_ledger_state.json"
    state = _state(_booked(_slot(8), with_eur=0.1, without_eur=0.2))
    store.save_state(state, str(path))

    assert store.peek_state(str(path)).state == state


@pytest.mark.parametrize(
    ("restart_state", "hint"),
    [(None, cls.HINT_NOT_RUNNING), ("{broken", cls.HINT_UNREADABLE)],
)
def test_load_without_a_usable_state_gives_a_hint_and_no_values(
    tmp_path, monkeypatch, restart_state, hint
):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    if restart_state is not None:
        (tmp_path / "savings_ledger_state.json").write_text(restart_state, encoding="utf-8")

    ledger = cls.load_ledger_chart_savings(
        [_slot(8)], 1, window_start=_DAY_START, window_end=_DAY_END
    )

    assert ledger["hint"] == hint
    assert ledger["saving_euro"] is None
    assert ledger["slot_states"] == [SLOT_NO_DATA]


def test_a_broken_slot_file_is_a_hint_and_keeps_the_open_day(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    state = _state(_booked(_slot(8), with_eur=0.1, without_eur=0.3))
    store.save_state(state)
    yesterday = _DAY_START - timedelta(days=1)
    store.append_row({
        "day_start": yesterday.isoformat(), "day_end": _DAY_START.isoformat(),
        "saving_eur": 0.2, "saving_adjusted_eur": 0.2, "incomplete": False,
    })
    monkeypatch.setattr(cls.config, "get_battery_params_list", lambda: [_BATTERY])
    monkeypatch.setattr(cls.sl, "shadow_battery_params", lambda batteries: batteries[0])

    ledger = cls.load_ledger_chart_savings(
        [_slot(8)], 1, window_start=yesterday, window_end=_DAY_END
    )

    assert ledger["hint"] == cls.HINT_SLOTS_UNREADABLE
    assert ledger["slot_states"] == [SLOT_COUNTED]
    assert [day["day_start"] for day in ledger["closed_days"]] == [yesterday.isoformat()]

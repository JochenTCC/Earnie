"""Ledger P7: Chart 2 "Ersparnis bisher" comes from the savings ledger."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from ui import chart_ledger_savings as cls
from ui.chart_cumulative_render import render_cumulative_cost_chart

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


def test_series_cumulates_without_minus_with_and_stops_at_the_last_booked_slot():
    slots = [_slot(8) + _QUARTER * index for index in range(6)]
    state = _state(
        _booked(slots[0], with_eur=0.10, without_eur=0.30),
        _booked(slots[1], with_eur=0.20, without_eur=0.10),
        _booked(slots[2], with_eur=0.05, without_eur=0.05),
    )

    series = _build(state, slots, history=5)["cumulative_euro"]

    assert series[:3] == pytest.approx([0.20, 0.10, 0.10])
    assert math.isnan(series[3]) and math.isnan(series[4]) and math.isnan(series[5])


def test_series_holds_over_a_slot_the_daemon_did_not_book():
    slots = [_slot(8) + _QUARTER * index for index in range(3)]
    state = _state(
        _booked(slots[0], with_eur=0.0, without_eur=0.2),
        _booked(slots[2], with_eur=0.0, without_eur=0.1),
    )

    series = _build(state, slots, history=3)["cumulative_euro"]

    assert series == pytest.approx([0.2, 0.2, 0.3])


def test_series_leaves_slots_of_other_days_empty():
    earlier = _DAY_START - timedelta(hours=1)
    booked = _slot(8)
    state = _state(_booked(booked, with_eur=0.0, without_eur=0.2))

    series = _build(state, [earlier, booked], history=2)["cumulative_euro"]

    assert math.isnan(series[0])
    assert series[1] == pytest.approx(0.2)


def test_soc_correction_is_the_day_rows_change_against_the_previous_day():
    slots = [_slot(8)]
    state = _state(_booked(slots[0], with_eur=0.5, without_eur=0.7), soc_actual_end=30.0, prev=0.25)
    # (30 − 20) % · 15 kWh · 0.94 at 40 ct = 0.564 €; minus the 0.25 € carried in.
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


def test_figures_for_day_tell_open_closed_and_unknown_days_apart():
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

    assert [day["day_start"] for day in ledger["closed_days"]] == [yesterday.isoformat()]
    # Chart anchors are not the ledger's stamps to the second.
    open_day = cls.ledger_figures_for_day(ledger, _DAY_START + timedelta(seconds=40))
    assert open_day["saving_euro"] == pytest.approx(0.2)
    closed = cls.ledger_figures_for_day(ledger, yesterday - timedelta(seconds=40))
    assert closed["closed_saving_euro"] == pytest.approx(-0.4)
    assert closed["incomplete"] is True
    unknown = cls.ledger_figures_for_day(ledger, _DAY_START + timedelta(days=1))
    assert unknown["saving_euro"] is None and unknown["closed_saving_euro"] is None


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
    assert math.isnan(ledger["cumulative_euro"][0])


def _render(monkeypatch, ledger):
    captured: dict = {}
    captions: list[str] = []
    monkeypatch.setattr(
        "ui.chart_cumulative_render.st.plotly_chart",
        lambda fig, **_k: captured.update(fig=fig),
    )
    monkeypatch.setattr("ui.chart_cumulative_render.st.caption", captions.append)
    monkeypatch.setattr(
        "ui.chart_cumulative_render.render_title_with_help", lambda *_a, **_k: None
    )
    slots = [_slot(8) + _QUARTER * index for index in range(4)]
    df = pd.DataFrame(
        {
            "slot_datetime": slots,
            "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
            "Preis extrapoliert": [False] * 4,
        }
    )
    render_cumulative_cost_chart(
        df,
        hourly_matched_baseline_cost_euro=[0.1] * 4,
        hourly_optimized_cost_euro=[0.08] * 4,
        hourly_matched_baseline_consumption_kwh=[0.5] * 4,
        hourly_optimized_consumption_kwh=[0.45] * 4,
        history_slot_count=2,
        slot_actual_cost_euro=[0.05] * 2,
        slot_actual_consumption_kwh=[0.2] * 2,
        ledger_savings=ledger,
    )
    return [trace.name for trace in captured["fig"].data], captions


def test_chart_draws_the_savings_line_from_the_ledger(monkeypatch):
    slots = [_slot(8), _slot(8, 15)]
    state = _state(
        _booked(slots[0], with_eur=0.0, without_eur=0.2),
        _booked(slots[1], with_eur=0.0, without_eur=0.1),
    )

    names, captions = _render(monkeypatch, _build(state, slots + [_slot(8, 30), _slot(8, 45)], 2))

    assert "Ersparnis bisher" in names
    assert not any("Ersparnis-Buch" in text for text in captions)


def test_chart_without_ledger_has_no_zero_line_and_shows_the_hint(monkeypatch):
    names, captions = _render(monkeypatch, cls._no_ledger(4, cls.HINT_NOT_RUNNING))

    assert "Ist bisher" in " ".join(str(name) for name in names)
    assert "Ersparnis bisher" not in names
    assert cls.HINT_NOT_RUNNING in captions

"""SE sunrise-booked steps: ready_by → SA₂ (book [SA₁, SA₂))."""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data.feed_in_prices import feed_in_settings_from_dict
from optimizer.simulation import _flex_indices_for_book_hours
from simulation.backtesting_horizon import (
    hourly_slots_half_open,
    resolve_ready_by_sunrise_step,
)
from simulation.engine import (
    _simulate_anchor_step,
    build_sunrise_window_matrix,
    window_anchor_for_date,
)
from simulation.horizon_mode import SUNRISE_WINDOW
from tests.fixtures.backtesting_fixtures import (
    SOC_CHAIN_END_DAY,
    SOC_CHAIN_START_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)

os.environ.setdefault("EARNIE_OFFLINE", "1")

_LAT = 47.41
_LON = 9.74
_TZ = "Europe/Vienna"

_BATTERY = {
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
}


@pytest.fixture(autouse=True)
def _fixtures(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch):
        yield


def test_flex_indices_with_book_start():
    assert _flex_indices_for_book_hours(48, 0, 24, flex_book_start=24) == list(
        range(24, 48)
    )
    # remaining starts at absolute hour 20; book [24, 48) → relative 4..27
    assert _flex_indices_for_book_hours(30, 20, 24, flex_book_start=24) == list(
        range(4, 28)
    )
    assert _flex_indices_for_book_hours(20, 0, 24, flex_book_start=0) == list(range(20))


def test_sa2_is_sunrise_on_ready_by_date():
    """Summer: ready_by 07:00 lies after SA₂; the book ends at that morning's sunrise."""
    ready = datetime(2026, 6, 19, 7, tzinfo=ZoneInfo(_TZ))
    step = resolve_ready_by_sunrise_step(ready, _LAT, _LON, _TZ)
    assert step.sa2.date() == ready.date()
    assert step.sa1.date() == date(2026, 6, 18)
    assert step.sa0.date() == date(2026, 6, 17)
    assert step.sa2 < ready
    assert step.sa1_index > 0
    assert len(step.book_slots) >= 23
    assert len(step.milp_slots) > len(step.book_slots)


def test_book_period_cuts_chain_edges_to_the_period():
    """First / last book of the chain keep only the in-period slots; the MILP stays whole."""
    tz = ZoneInfo(_TZ)
    full = resolve_ready_by_sunrise_step(
        datetime(2025, 10, 1, 7, tzinfo=tz), _LAT, _LON, _TZ
    )
    period = (datetime(2025, 10, 1), datetime(2026, 10, 1))
    first = resolve_ready_by_sunrise_step(
        datetime(2025, 10, 1, 7, tzinfo=tz), _LAT, _LON, _TZ, book_period=period
    )
    book = [slot.replace(tzinfo=None) for slot in first.book_slots]
    assert book[0] == datetime(2025, 10, 1, 0, 0)
    assert book[-1] == full.book_slots[-1].replace(tzinfo=None)
    assert first.milp_slots == full.milp_slots
    assert first.milp_slots[first.sa1_index].replace(tzinfo=None) == book[0]
    last = resolve_ready_by_sunrise_step(
        datetime(2026, 10, 1, 7, tzinfo=tz), _LAT, _LON, _TZ, book_period=period
    )
    assert last.book_slots[-1].replace(tzinfo=None) == datetime(2026, 9, 30, 23, 45)
    inner = resolve_ready_by_sunrise_step(
        datetime(2026, 3, 3, 7, tzinfo=tz), _LAT, _LON, _TZ, book_period=period
    )
    assert inner.book_slots == resolve_ready_by_sunrise_step(
        datetime(2026, 3, 3, 7, tzinfo=tz), _LAT, _LON, _TZ
    ).book_slots


def test_book_period_rejects_step_outside_period():
    tz = ZoneInfo(_TZ)
    with pytest.raises(ValueError, match="außerhalb der Buchungsperiode"):
        resolve_ready_by_sunrise_step(
            datetime(2025, 6, 1, 7, tzinfo=tz),
            _LAT,
            _LON,
            _TZ,
            book_period=(datetime(2025, 10, 1), datetime(2026, 10, 1)),
        )


def test_book_contains_charging_night_before_ready_by():
    """Winter weekday: ready_by 07:00 before sunrise — the night 20:00→07:00 is booked."""
    ready = datetime(2025, 12, 9, 7, tzinfo=ZoneInfo(_TZ))
    step = resolve_ready_by_sunrise_step(ready, _LAT, _LON, _TZ)
    assert step.sa1 < ready < step.sa2
    book = {slot.replace(tzinfo=None) for slot in step.book_slots}
    assert datetime(2025, 12, 8, 20, 0) in book
    assert datetime(2025, 12, 9, 6, 45) in book


def _winter_week_steps():
    """Thu 07:00 … Tue 07:00 with weekend ready_by 12:00; sunrise ≈ 07:45 (> 07:00)."""
    tz = ZoneInfo(_TZ)
    ready_hours = {
        date(2025, 12, 4): 7,
        date(2025, 12, 5): 7,
        date(2025, 12, 6): 12,
        date(2025, 12, 7): 12,
        date(2025, 12, 8): 7,
        date(2025, 12, 9): 7,
    }
    return [
        resolve_ready_by_sunrise_step(
            datetime.combine(day, time(hour), tzinfo=tz), _LAT, _LON, _TZ
        )
        for day, hour in ready_hours.items()
    ]


def test_winter_weekend_books_form_contiguous_sunrise_chain():
    """Regression: Fri→Sat used to be missing and Sun→Mon booked twice."""
    steps = _winter_week_steps()
    for prev, nxt in zip(steps, steps[1:]):
        assert prev.sa2 == nxt.sa1
        assert prev.book_slots[-1] + timedelta(minutes=15) == nxt.book_slots[0]
    all_slots = [slot for step in steps for slot in step.book_slots]
    assert len(all_slots) == len(set(all_slots))
    span = hourly_slots_half_open(steps[0].sa1, steps[-1].sa2)
    assert tuple(all_slots) == span


def test_ready_by_07_vs_10_same_departure_day_same_book_when_both_after_sunrise():
    """On a summer Saturday, 07:00 and 10:00 share the same SA₁→SA₂ book."""
    d07 = resolve_ready_by_sunrise_step(
        datetime(2026, 6, 20, 7, tzinfo=ZoneInfo(_TZ)), _LAT, _LON, _TZ
    )
    d10 = resolve_ready_by_sunrise_step(
        datetime(2026, 6, 20, 10, tzinfo=ZoneInfo(_TZ)), _LAT, _LON, _TZ
    )
    assert d07.sa1 == d10.sa1
    assert d07.sa2 == d10.sa2
    assert d07.book_slots == d10.book_slots


def test_fri07_sat10_books_abut_without_gap_or_overlap():
    fri = resolve_ready_by_sunrise_step(
        datetime(2026, 6, 19, 7, tzinfo=ZoneInfo(_TZ)), _LAT, _LON, _TZ
    )
    sat = resolve_ready_by_sunrise_step(
        datetime(2026, 6, 20, 10, tzinfo=ZoneInfo(_TZ)), _LAT, _LON, _TZ
    )
    assert fri.sa2 == sat.sa1
    fri_book = {slot.replace(tzinfo=None) for slot in fri.book_slots}
    sat_book = {slot.replace(tzinfo=None) for slot in sat.book_slots}
    assert fri_book.isdisjoint(sat_book)


def test_build_sunrise_matrix_uses_ready_by_charging_anchor():
    scenario = fixture_scenario_params()
    cache = load_fixture_cache()
    prices = build_synthetic_prices_df(
        pd.Timestamp(SOC_CHAIN_START_DAY),
        pd.Timestamp(SOC_CHAIN_END_DAY),
    )
    anchor = window_anchor_for_date(SOC_CHAIN_START_DAY)
    book_matrix, meta, sa1_index, matrix_full = build_sunrise_window_matrix(
        anchor, cache, prices, scenario
    )
    assert len(matrix_full) > len(book_matrix)
    assert meta["book_hours"] == len(book_matrix)
    assert meta["sa1_index"] == sa1_index
    assert all(row.get("charging_anchor") == anchor for row in book_matrix)
    assert all(row.get("charging_anchor") == anchor for row in matrix_full)


def test_simulate_anchor_step_books_sa1_sa2_and_holds_soc(monkeypatch):
    scenario = fixture_scenario_params()
    cache = load_fixture_cache()
    prices = build_synthetic_prices_df(
        pd.Timestamp(SOC_CHAIN_START_DAY),
        pd.Timestamp(SOC_CHAIN_END_DAY),
    )
    anchor = window_anchor_for_date(SOC_CHAIN_START_DAY)
    _book, meta, sa1_index, matrix_full = build_sunrise_window_matrix(
        anchor, cache, prices, scenario
    )

    captured: dict = {}

    def _fake_simulate(matrix, sim_soc, **kwargs):
        captured["matrix_len"] = len(matrix)
        captured["flex_book_hours"] = kwargs.get("flex_book_hours")
        captured["flex_book_start"] = kwargs.get("flex_book_start")
        captured["disable"] = kwargs.get("disable_horizon_soc_anchor")
        captured["soc_hold_index"] = kwargs.get("soc_hold_index")
        captured["soc_hold_percent"] = kwargs.get("soc_hold_percent")
        captured["commit_hours"] = kwargs.get("commit_hours")
        rows = []
        for i, row in enumerate(matrix):
            rows.append(
                {
                    "slot_datetime": row["slot_datetime"],
                    "Simulierter SoC (%)": 55.0 if i >= sa1_index else 50.0,
                    "Geplante Batterie-Aktion (kW)": 0.0,
                    "PV-Prognose (kW)": float(row.get("expected_p_pv", 0.0) or 0.0),
                    "Verbrauch-Prognose (kW)": float(
                        row.get("expected_p_act", 0.0) or 0.0
                    ),
                    "Netzbezug (kW)": 0.0,
                    "Steuerbefehl": "Automatikbetrieb",
                    "_horizon_end_soc": 55.0 if i == len(matrix) - 1 else None,
                }
            )
        return rows

    feed_in = feed_in_settings_from_dict(scenario)
    with patch("simulation.engine.simulate_horizon", side_effect=_fake_simulate):
        chart_rows, matrix_out, meta2, new_soc, *_rest = _simulate_anchor_step(
            anchor,
            50.0,
            horizon_mode=SUNRISE_WINDOW,
            cache=cache,
            prices_df=prices,
            scenario_params=scenario,
            battery_params=_BATTERY,
            feed_in_settings=feed_in,
            hours_done=0,
            collect_cbc=False,
        )

    assert captured["matrix_len"] == len(matrix_full)
    assert captured["flex_book_start"] == sa1_index
    assert captured["flex_book_hours"] == meta["book_hours"]
    assert captured["disable"] is True
    assert captured["soc_hold_index"] == sa1_index - 1
    assert captured["soc_hold_percent"] == pytest.approx(50.0)
    assert captured["commit_hours"] == len(matrix_full)
    assert len(chart_rows) == meta["book_hours"]
    assert len(matrix_out) == meta["book_hours"]
    assert new_soc == pytest.approx(55.0)
    assert meta2["ready_by"] == anchor


def _stash_meta(book_start: datetime, book_end: datetime) -> dict:
    slots = []
    slot = book_start
    while slot < book_end:
        slots.append(slot)
        slot += timedelta(minutes=15)
    return {
        "ready_by": book_end,
        "sa1": book_start,
        "sa2": book_end,
        "step_slot_datetimes": slots,
    }


def test_stash_rejects_flex_outside_book():
    """Bug B guard: flex in SA₀→SA₁ would never reach the booked series."""
    from simulation.anchor_step import _stash_sunrise_full_horizon_flex

    consumer = {"id": "ev", "name": "EV"}
    book_start = datetime(2026, 6, 24, 5, 15)
    meta = _stash_meta(book_start, book_start + timedelta(hours=1))
    rows = [
        {"slot_datetime": book_start - timedelta(minutes=15), "EV (kW)": 3.5},
        {"slot_datetime": book_start, "EV (kW)": 3.5},
    ]
    with pytest.raises(ValueError, match="außerhalb des Buchungsfensters"):
        _stash_sunrise_full_horizon_flex(meta, rows, [consumer])


def test_stash_accepts_flex_inside_book_only():
    from simulation.anchor_step import _stash_sunrise_full_horizon_flex

    consumer = {"id": "ev", "name": "EV"}
    book_start = datetime(2026, 6, 24, 5, 15)
    meta = _stash_meta(book_start, book_start + timedelta(hours=1))
    rows = [
        {"slot_datetime": book_start - timedelta(minutes=15), "EV (kW)": 0.0},
        {"slot_datetime": book_start, "EV (kW)": 4.0},
    ]
    _stash_sunrise_full_horizon_flex(meta, rows, [consumer])
    assert meta["plausibility_optimized_flex_kwh"] == pytest.approx(1.0)
    assert "foresight_flex_rows" not in meta


def test_sunrise_step_anchors_chain_over_whole_period():
    """Books run from SA(start−1) to SA(end+1): every QH of the period booked once."""
    from simulation.engine import list_sunrise_step_anchors
    from simulation.backtesting_horizon import (
        naive_backtesting_slot,
        resolve_sunrise_book_step_for_scenario,
    )

    scenario = fixture_scenario_params()
    cache = load_fixture_cache()
    start = pd.Timestamp(SOC_CHAIN_START_DAY)
    end = pd.Timestamp(SOC_CHAIN_END_DAY)
    anchors = list_sunrise_step_anchors(start, end, cache, scenario)
    steps = [resolve_sunrise_book_step_for_scenario(a, scenario) for a in anchors]
    assert [a.date() for a in anchors] == [
        SOC_CHAIN_START_DAY,
        SOC_CHAIN_END_DAY,
        SOC_CHAIN_END_DAY + timedelta(days=1),
    ]
    for prev, nxt in zip(steps, steps[1:]):
        assert prev.sa2 == nxt.sa1
    booked = [naive_backtesting_slot(s) for step in steps for s in step.book_slots]
    assert len(booked) == len(set(booked))
    period = pd.date_range(start, end + pd.Timedelta(days=1), freq="15min", inclusive="left")
    assert set(period.to_pydatetime()) <= set(booked)


def test_assert_unique_book_slots_rejects_double_booking():
    from simulation.engine import _assert_unique_book_slots

    slot = datetime(2025, 12, 8, 7, 45)
    _assert_unique_book_slots([slot, slot + timedelta(minutes=15)])
    with pytest.raises(ValueError, match="doppelt gebucht"):
        _assert_unique_book_slots([slot, slot + timedelta(minutes=15), slot])


def test_book_end_soc_includes_last_book_slot():
    """SoC chain: carry the SoC after the last book slot, not its start SoC."""
    from simulation.anchor_step import _sunrise_book_end_soc

    book_start = datetime(2026, 6, 24, 5, 15)
    meta = _stash_meta(book_start, book_start + timedelta(minutes=30))
    rows = [
        {"slot_datetime": book_start, "Simulierter SoC (%)": 60.0},
        {"slot_datetime": book_start + timedelta(minutes=15), "Simulierter SoC (%)": 55.0},
        {"slot_datetime": book_start + timedelta(minutes=30), "Simulierter SoC (%)": 50.0},
    ]
    assert _sunrise_book_end_soc(rows, meta) == pytest.approx(50.0)
    with pytest.raises(ValueError, match="End-SoC an SA₂"):
        _sunrise_book_end_soc(rows[:2], meta)


def test_soc_hold_slot_anchors_book_start_soc():
    """The book starts at SA₁ with the carried-in SoC even if SA₀→SA₁ drifted."""
    from optimizer.sim_horizon_types import _HorizonOptions
    from optimizer.simulation import _soc_after_hold_slot

    options = _HorizonOptions(
        k_push=None,
        verbose=False,
        commit_hours=10,
        flex_book_hours=4,
        flex_book_start=5,
        sunrise_soc_min_index=None,
        soc_hold_index=4,
        soc_hold_percent=40.0,
    )
    assert _soc_after_hold_slot(options, 3, 70.2) == pytest.approx(70.2)
    assert _soc_after_hold_slot(options, 4, 70.2) == pytest.approx(40.0)
    assert _soc_after_hold_slot(options, 5, 70.2) == pytest.approx(70.2)
    no_hold = _HorizonOptions(
        k_push=None,
        verbose=False,
        commit_hours=1,
        flex_book_hours=None,
        flex_book_start=0,
        sunrise_soc_min_index=None,
        soc_hold_index=None,
        soc_hold_percent=None,
    )
    assert _soc_after_hold_slot(no_hold, 4, 70.2) == pytest.approx(70.2)


def test_reference_books_same_sunrise_slots_as_optimized_run():
    """Historisch / ref:* follow the optimized run's sunrise chain (start … end+1)."""
    import config
    from simulation.engine import compute_historical_reference_costs, run_simulation

    scenario = fixture_scenario_params()
    cache = load_fixture_cache()
    start = pd.Timestamp(SOC_CHAIN_START_DAY)
    end = pd.Timestamp(SOC_CHAIN_END_DAY)
    prices = build_synthetic_prices_df(start, end)
    reference = compute_historical_reference_costs(
        start,
        end,
        prices,
        config.get_backtesting_feed_in_settings(runtime_override=scenario),
        cache=cache,
        scenario_params=scenario,
        horizon_mode=SUNRISE_WINDOW,
    )
    optimized, _plausibility, _cbc = run_simulation(
        start, end, scenario, prices, cache=cache, horizon_mode=SUNRISE_WINDOW
    )
    assert list(reference.index) == list(optimized.index)

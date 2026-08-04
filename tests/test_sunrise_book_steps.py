"""SE sunrise-booked steps: ready_by → SA₂ (book [SA₁, SA₂))."""
from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data.feed_in_prices import FEED_IN_MODE_FIXED, FeedInSettings
from optimizer.simulation import _flex_indices_for_book_hours
from simulation.backtesting_horizon import resolve_ready_by_sunrise_step
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


def test_sa2_is_first_sunrise_after_ready_by():
    ready = datetime(2026, 6, 19, 7, tzinfo=ZoneInfo(_TZ))
    step = resolve_ready_by_sunrise_step(ready, _LAT, _LON, _TZ)
    assert step.sa1 < ready < step.sa2
    assert step.sa0 < step.sa1 < step.sa2
    assert step.sa1_index > 0
    assert len(step.book_slots) >= 23
    assert len(step.milp_slots) > len(step.book_slots)


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

    feed_in = FeedInSettings(
        mode=FEED_IN_MODE_FIXED,
        k_push_cent=5.0,
        fee_factor=0.0,
        fix_cent=5.0,
    )
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

"""Sunrise book windows must keep the energy of schedule-driven generic consumers.

Regression: the book window [SA1, SA2) lies *after* the ready-by anchor, but the generic
target rule accepts a run only when it ends before ``window_end`` (= anchor). Every
appliance / pool-filter / dev-pc target silently became ~0 (-14 % load in March).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from house_config.generic_schedule import generic_daily_target_kwh_for_day
from house_config.planning_flex_bridge import (
    collect_planning_flex_consumers,
    resolve_profile_spec_flex_targets,
)
from house_config.profiles_store import normalize_house_profiles_document
from simulation.engine import window_anchor_for_date
from simulation.matrix_builder import build_sunrise_window_matrix
from tests.fixtures.backtesting_fixtures import (
    SOC_CHAIN_START_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)

_N_WINDOWS = 5


def _manual(cid: str, nominal: float, runs: int, duration_h: float, start_hour: int, shift_h: float) -> dict:
    return {
        "id": cid,
        "label": cid,
        "type": "generic",
        "nominal_power_kw": nominal,
        "earnie_role": "manual",
        "schedule": {
            "runs_per_week": runs,
            "duration_h": duration_h,
            "start_hour": start_hour,
            "start_shift_h": shift_h,
        },
    }


def _profile() -> dict:
    raw = {
        "id": "home",
        "label": "Home",
        "annual_kwh": 20000.0,
        "latitude": 47.4,
        "longitude": 9.7,
        "netznutzung": {"area_id": "user_no_grid_fee"},
        "consumers": [
            _manual("filter", 0.18, 7, 4.0, 12, 0.0),
            _manual("trockner", 1.0, 3, 2.0, 16, 4.0),
            _manual("spueler", 0.35, 5, 3.0, 12, 8.0),
        ],
    }
    return normalize_house_profiles_document({"profiles": [raw]})["profiles"]["home"]


def _scenario(profile: dict) -> dict:
    return {
        **fixture_scenario_params(),
        "_house_profile": profile,
        "_planning_flex_consumers": collect_planning_flex_consumers(profile),
        "consumption_source": "profile_spec",
    }


def _daily_energy(profile: dict, cid: str, first: datetime, last: datetime) -> float:
    consumer = next(c for c in profile["consumers"] if c["id"] == cid)
    total, day = 0.0, first.date()
    while day <= last.date():
        total += generic_daily_target_kwh_for_day(consumer, day)
        day += timedelta(days=1)
    return total


def test_book_window_targets_conserve_scheduled_energy(monkeypatch):
    profile = _profile()
    with activate_backtesting_fixtures(monkeypatch):
        scenario = _scenario(profile)
        cache = load_fixture_cache()
        first_anchor = window_anchor_for_date(SOC_CHAIN_START_DAY)
        prices = build_synthetic_prices_df(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_START_DAY) + pd.Timedelta(days=_N_WINDOWS + 2),
        )
        totals: dict[str, float] = {}
        first_slot = last_slot = None
        for i in range(_N_WINDOWS):
            _book, meta, _sa1, _full = build_sunrise_window_matrix(
                first_anchor + timedelta(days=i), cache, prices, scenario
            )
            slots = meta["step_slot_datetimes"]
            first_slot = first_slot or slots[0]
            last_slot = slots[-1]
            for cid, kwh in meta["spec_flex_targets_kwh"].items():
                totals[cid] = totals.get(cid, 0.0) + kwh
    first = first_slot.replace(tzinfo=None)
    last = last_slot.replace(tzinfo=None)
    for cid in ("filter", "trockner", "spueler"):
        expected = _daily_energy(profile, cid, first, last)
        assert expected > 0.0
        # Runs on the first/last (partial) day may fall to a neighbouring window: allow
        # one run of slack, but never the ~100 % loss of the old window_end=anchor rule.
        one_run = _daily_energy(profile, cid, first, first) or expected / _N_WINDOWS
        assert totals[cid] >= expected - 2 * max(one_run, 1.0), (cid, totals[cid], expected)
        assert totals[cid] <= expected + 1e-6


def test_anchor_as_window_end_loses_book_window_energy():
    """Negative control: documents the old behaviour for slots *after* the anchor."""
    profile = _profile()
    flex = collect_planning_flex_consumers(profile)
    anchor = datetime(2026, 3, 3, 7, 0)
    book_slots = [anchor - timedelta(minutes=15) + timedelta(minutes=15 * i) for i in range(96)]
    wrong = resolve_profile_spec_flex_targets(flex, profile, book_slots, window_end=anchor)
    right = resolve_profile_spec_flex_targets(
        flex, profile, book_slots, window_end=book_slots[-1] + timedelta(minutes=15)
    )
    assert sum(wrong.values()) < 0.2 * sum(right.values())
    assert right["filter"] == pytest.approx(0.18 * 4.0)

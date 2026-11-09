"""The two SE prototypes behind the study's figures: look-ahead past SA₂ and the SoC base level.

The fixture has flat PV and a flat price, where neither prototype has anything to do, so the
runs here replace both with a daily curve. Everything else is the real sunrise pipeline.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import pytest

import simulation.matrix_builder as matrix_builder
from optimizer.milp import _solve_milp_to_model
from optimizer.milp_horizon_extras import (
    BASE_LEVEL_ENV,
    LOOKAHEAD_ENV,
    _base_level_credit,
    _base_level_target_kwh,
)
from optimizer.slot_duration import DEFAULT_DT_H
from simulation.backtesting_horizon import (
    lookahead_hours,
    resolve_ready_by_sunrise_step,
    resolve_sunrise_book_step_for_scenario,
)
from simulation.engine import (
    build_sunrise_window_matrix,
    list_sunrise_step_anchors,
    run_simulation,
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

_START = pd.Timestamp(SOC_CHAIN_START_DAY)
_END = pd.Timestamp(SOC_CHAIN_END_DAY)
_ENERGY_COLUMNS = ["consumption_kw", "baseload_kw", "swimspa_kw", "eauto_kw", "pv_kw"]
_OFF = ("0", None)
_LOOKAHEAD = ("8", None)
_BOTH = ("8", "1")


def _set_switches(monkeypatch, lookahead: str | None, base_level: str | None) -> None:
    for name, value in ((LOOKAHEAD_ENV, lookahead), (BASE_LEVEL_ENV, base_level)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


# --- Plan level: what the base level asks of the MILP

_SLOTS = 24
_LOOKAHEAD_SLOTS = 8
_SUNRISE = _SLOTS - 1 - _LOOKAHEAD_SLOTS
_KWH_PER_KW = float(DEFAULT_DT_H) * _LOOKAHEAD_SLOTS


def _battery(efficiency: float = 0.95) -> dict:
    return {
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "efficiency": efficiency,
        "control": "full",
    }


def _matrix(*, surplus_kw: float = 0.0, k_act: float = 20.0) -> list[dict]:
    """No load before SA₂, so only the sale competes with the level; it pays better before SA₂."""
    rows = []
    for slot in range(_SLOTS):
        past_book = slot > _SUNRISE
        rows.append(
            {
                "hour": slot % 24,
                "expected_p_pv": 0.5 + surplus_kw if past_book else 0.0,
                "expected_p_act": 0.5 if past_book else 0.0,
                "k_act": k_act,
                "k_push_act": 1.0 if past_book else 10.0,
                "expected_flex_kw": {},
            }
        )
    return rows


def _solve(monkeypatch, matrix: list[dict], soc: float, *, level: bool, battery: dict | None = None):
    _set_switches(monkeypatch, "2", "1" if level else None)
    solved = _solve_milp_to_model(
        matrix, soc, battery or _battery(), 10.0, False, [], {}, None, None, None, None, None, None,
        None, None, inverter_params=[], pv_systems=[],
    )
    assert solved is not None
    return solved[0]


def _kwh(variable) -> float:
    return float(variable.varValue or 0.0)


def _plan(model) -> list[list[float]]:
    return [
        [_kwh(series[t]) for t in range(_SLOTS)]
        for series in (model.e_batt, model.p_charge, model.p_discharge, model.p_grid_buy, model.p_grid_sell)
    ]


@pytest.mark.parametrize(
    "surplus_kwh,e_min,expected",
    [
        pytest.param(0.0, 1.0, 5.0, id="no-surplus-stops-at-half-the-battery"),
        pytest.param(4.0, 1.0, 3.0, id="room-for-the-surplus-and-the-reserve"),
        pytest.param(20.0, 1.0, 1.0, id="a-day-that-fills-stays-at-the-minimum"),
        pytest.param(0.0, 6.0, 6.0, id="a-minimum-above-half-wins"),
    ],
)
def test_level_target(surplus_kwh, e_min, expected) -> None:
    assert _base_level_target_kwh(surplus_kwh, e_min, 10.0) == pytest.approx(expected)


def test_plan_holds_half_the_battery_at_sa2_and_no_more(monkeypatch) -> None:
    held = _solve(monkeypatch, _matrix(), 100.0, level=True)
    sold = _solve(monkeypatch, _matrix(), 100.0, level=False)

    assert _kwh(held.e_batt[_SUNRISE]) == pytest.approx(5.0, abs=1e-6)
    assert _kwh(sold.e_batt[_SUNRISE]) == pytest.approx(1.0, abs=1e-6)


def test_plan_leaves_room_for_the_surplus_and_the_reserve(monkeypatch) -> None:
    surplus_kw = 4.0 / _KWH_PER_KW

    model = _solve(monkeypatch, _matrix(surplus_kw=surplus_kw), 100.0, level=True)

    assert _kwh(model.e_batt[_SUNRISE]) == pytest.approx(3.0, abs=1e-6)


def test_plan_is_unchanged_on_a_day_that_fills_the_battery(monkeypatch) -> None:
    matrix = _matrix(surplus_kw=20.0 / _KWH_PER_KW)

    assert _plan(_solve(monkeypatch, matrix, 100.0, level=True)) == _plan(
        _solve(monkeypatch, matrix, 100.0, level=False)
    )


@pytest.mark.parametrize("efficiency", [0.95, 1.0])
def test_level_alone_does_not_pay_for_grid_charging(monkeypatch, efficiency) -> None:
    """Nothing uses the energy past SA₂ here, so the value alone stays below the buy price."""
    model = _solve(monkeypatch, _matrix(), 10.0, level=True, battery=_battery(efficiency))

    assert sum(_kwh(model.p_charge[t]) for t in range(_SUNRISE + 1)) == pytest.approx(0.0, abs=1e-6)
    assert _kwh(model.e_batt[_SUNRISE]) == pytest.approx(1.0, abs=1e-6)


def _dark_morning() -> list[dict]:
    """A load past SA₂ without PV, at the same flat price as the night."""
    matrix = _matrix()
    for row in matrix[_SUNRISE + 1 :]:
        row["expected_p_pv"] = 0.0
        row["expected_p_act"] = 3.0
    return matrix


def test_without_the_level_a_flat_price_gives_no_reason_to_charge(monkeypatch) -> None:
    model = _solve(monkeypatch, _dark_morning(), 10.0, level=False)

    assert sum(_kwh(model.p_charge[t]) for t in range(_SUNRISE + 1)) == pytest.approx(0.0, abs=1e-6)


def _charged_before_sa2(model) -> float:
    return sum(_kwh(model.p_charge[t]) for t in range(_SUNRISE + 1))


def test_level_is_not_reached_from_the_grid_when_the_morning_uses_the_energy(monkeypatch) -> None:
    """The value adds to the later use of the same energy, which alone would make charging pay."""
    model = _solve(monkeypatch, _dark_morning(), 10.0, level=True)

    assert _charged_before_sa2(model) == pytest.approx(0.0, abs=1e-6)
    assert _kwh(model.e_batt[_SUNRISE]) == pytest.approx(1.0, abs=1e-6)


def test_level_is_reached_from_pv(monkeypatch) -> None:
    matrix = _matrix()
    for row in matrix[:8]:
        row["expected_p_pv"] = 5.0

    assert _kwh(_solve(monkeypatch, matrix, 10.0, level=True).e_batt[_SUNRISE]) == pytest.approx(5.0, abs=1e-6)
    assert _kwh(_solve(monkeypatch, matrix, 10.0, level=False).e_batt[_SUNRISE]) == pytest.approx(1.0, abs=1e-6)


def test_pv_that_only_covers_the_load_earns_no_level(monkeypatch) -> None:
    matrix = _dark_morning()
    for row in matrix[:8]:
        row["expected_p_pv"] = 2.0
        row["expected_p_act"] = 2.0

    model = _solve(monkeypatch, matrix, 10.0, level=True)

    assert _charged_before_sa2(model) == pytest.approx(0.0, abs=1e-6)


def test_pv_that_was_sold_does_not_earn_the_level(monkeypatch) -> None:
    """PV in the plan counts only if it went into the battery, not if the grid fills in later."""
    matrix = _dark_morning()
    for row in matrix[:8]:
        row["expected_p_pv"] = 5.0
        row["k_act"] = 100.0
        row["k_push_act"] = 40.0
    for row in matrix[8 : _SUNRISE + 1]:
        row["k_push_act"] = 1.0

    model = _solve(monkeypatch, matrix, 10.0, level=True)

    assert _charged_before_sa2(model) == pytest.approx(0.0, abs=1e-6)
    assert _kwh(model.e_batt[_SUNRISE]) == pytest.approx(1.0, abs=1e-6)


def test_sold_pv_does_not_turn_earlier_grid_energy_into_pv(monkeypatch) -> None:
    """Prices where charging for the morning pays only with the value, and PV is worth selling."""
    matrix = _dark_morning()
    for row in matrix[_SUNRISE + 1 :]:
        row["k_act"] = 200.0
    for row in matrix[: _SUNRISE + 1]:
        row["k_act"] = 330.0
        row["k_push_act"] = 1.0
    for row in matrix[4:8]:
        row["expected_p_pv"] = 5.0
        row["k_act"] = 1000.0
        row["k_push_act"] = 360.0

    model = _solve(monkeypatch, matrix, 10.0, level=True)

    assert _charged_before_sa2(model) == pytest.approx(0.0, abs=1e-6)


def test_energy_used_before_sa2_cannot_be_refilled_from_the_grid(monkeypatch) -> None:
    """The start energy counts, but once a dear evening used it the grid does not replace it."""
    matrix = _dark_morning()
    for row in matrix[:8]:
        row["expected_p_act"] = 3.0
        row["k_act"] = 100.0

    model = _solve(monkeypatch, matrix, 50.0, level=True)

    assert _kwh(model.e_batt[7]) == pytest.approx(1.0, abs=1e-6)
    assert _charged_before_sa2(model) == pytest.approx(0.0, abs=1e-6)


def test_level_does_not_block_grid_charging_that_pays_by_itself(monkeypatch) -> None:
    matrix = _dark_morning()
    for row in matrix[: _SUNRISE + 1]:
        row["k_act"] = 10.0
    for row in matrix[_SUNRISE + 1 :]:
        row["k_act"] = 30.0

    with_level = _charged_before_sa2(_solve(monkeypatch, matrix, 10.0, level=True))
    without = _charged_before_sa2(_solve(monkeypatch, matrix, 10.0, level=False))

    assert without > 1.0
    assert with_level == pytest.approx(without, abs=1e-6)


def test_tracking_starts_at_the_soc_hold(monkeypatch) -> None:
    """The slots before the hold are not replayed, so the real SoC there counts in full."""
    _set_switches(monkeypatch, "2", "1")

    solved = _solve_milp_to_model(
        _matrix(), 10.0, _battery(), 10.0, False, [], {}, None, None, None, None, None, None, None, None,
        soc_hold_index=5, soc_hold_percent=60.0, inverter_params=[], pv_systems=[],
    )

    assert solved is not None
    assert _kwh(solved[0].e_batt[5]) == pytest.approx(6.0, abs=1e-6)
    assert _kwh(solved[0].e_batt[_SUNRISE]) == pytest.approx(5.0, abs=1e-6)


def test_level_stops_with_several_batteries(monkeypatch) -> None:
    _set_switches(monkeypatch, "2", "1")
    batteries = [{**_battery(), "id": "one"}, {**_battery(), "id": "two"}]

    with pytest.raises(ValueError, match="nur einen Speicher"):
        _solve_milp_to_model(
            _matrix(), 50.0, batteries, 10.0, False, [], {}, None, None, None, None, None, None, None, None,
            current_soc_by_id={"one": 50.0, "two": 50.0}, inverter_params=[], pv_systems=[],
        )


def test_level_without_a_start_soc_stops(monkeypatch) -> None:
    model = _solve(monkeypatch, _matrix(), 50.0, level=False)
    monkeypatch.setenv(BASE_LEVEL_ENV, "1")

    with pytest.raises(ValueError, match="base_level_start"):
        _base_level_credit(model, _matrix(), None)


def test_cheapest_slot_past_sa2_sets_the_value(monkeypatch) -> None:
    """The value follows the plan's cheapest price, so a low price past SA₂ lowers it below the sale."""
    matrix = _matrix()
    for row in matrix[_SUNRISE + 1 :]:
        row["k_act"] = 5.0

    model = _solve(monkeypatch, matrix, 100.0, level=True)

    assert _kwh(model.e_batt[_SUNRISE]) == pytest.approx(1.0, abs=1e-6)


def test_level_without_a_look_ahead_stops(monkeypatch) -> None:
    _set_switches(monkeypatch, "0", "1")
    with pytest.raises(ValueError, match=LOOKAHEAD_ENV):
        _solve_milp_to_model(
            _matrix(), 50.0, _battery(), 10.0, False, [], {}, None, None, None, None, None, None,
            None, None, inverter_params=[], pv_systems=[],
        )


def test_level_with_a_look_ahead_past_the_horizon_stops(monkeypatch) -> None:
    _set_switches(monkeypatch, "100", "1")
    with pytest.raises(ValueError, match=BASE_LEVEL_ENV):
        _solve_milp_to_model(
            _matrix(), 50.0, _battery(), 10.0, False, [], {}, None, None, None, None, None, None,
            None, None, inverter_params=[], pv_systems=[],
        )


# --- Window: the look-ahead only adds slots past the book


@pytest.mark.parametrize("raw,expected", [("", 8.0), ("0", 0.0), ("8", 8.0), ("2.5", 2.5)])
def test_lookahead_hours(monkeypatch, raw, expected) -> None:
    monkeypatch.setenv(LOOKAHEAD_ENV, raw)
    assert lookahead_hours() == expected


def test_lookahead_is_on_by_default(monkeypatch) -> None:
    monkeypatch.delenv(LOOKAHEAD_ENV, raising=False)
    assert lookahead_hours() == 8.0


def test_negative_lookahead_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv(LOOKAHEAD_ENV, "-1")
    with pytest.raises(ValueError, match=LOOKAHEAD_ENV):
        lookahead_hours()


def test_lookahead_changes_the_plan_window_and_nothing_of_the_book(monkeypatch) -> None:
    ready_by = datetime(2026, 1, 15, 7, 0)
    resolve = lambda: resolve_ready_by_sunrise_step(ready_by, 47.2, 9.6, "Europe/Vienna")  # noqa: E731
    monkeypatch.setenv(LOOKAHEAD_ENV, "0")
    off = resolve()

    monkeypatch.setenv(LOOKAHEAD_ENV, "8")
    on = resolve()

    assert on.book_slots == off.book_slots
    assert on.sa1_index == off.sa1_index
    assert (on.sa0, on.sa1, on.sa2) == (off.sa0, off.sa1, off.sa2)
    assert on.milp_slots[: off.milp_hours] == off.milp_slots
    assert on.milp_hours == off.milp_hours + 32
    assert on.milp_slots[-1] == off.milp_slots[-1] + timedelta(hours=8)


# --- The real pipeline with a daily curve


def _bell_kw(slot, peak_kw: float) -> float:
    hour = slot.hour + slot.minute / 60.0
    return max(0.0, peak_kw * (1.0 - ((hour - 14.0) / 5.0) ** 2))


def _spread_cent(slot) -> float:
    """Dear morning right after SA₂, which a plan ending at SA₂ cannot see."""
    if 5 <= slot.hour < 10:
        return 32.0
    return 18.0 if slot.hour < 5 else 22.0


@pytest.fixture
def curves(monkeypatch):
    """Replace the fixture's flat PV and price by a daily curve; yields the setter."""
    real = matrix_builder._matrix_rows_from_slots

    def install(peak_kw: float, *, spread: bool) -> None:
        def rows(slots, consumption, prices, *, pv_profile, **kwargs):
            epex, brutto, sources = prices
            if spread:
                brutto = [_spread_cent(slot) for slot in slots]
            return real(
                slots,
                consumption,
                (epex, brutto, sources),
                pv_profile=[_bell_kw(slot, peak_kw) for slot in slots],
                **kwargs,
            )

        monkeypatch.setattr(matrix_builder, "_matrix_rows_from_slots", rows)

    return install


@pytest.fixture
def sim(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch):

        def run(switches: tuple[str | None, str | None]) -> pd.DataFrame:
            _set_switches(monkeypatch, *switches)
            df, plausibility, _ = run_simulation(
                _START,
                _END,
                fixture_scenario_params(),
                build_synthetic_prices_df(_START, _END),
                cache=load_fixture_cache(),
                initial_soc=50.0,
                horizon_mode=SUNRISE_WINDOW,
            )
            assert plausibility.failed == []
            return df

        yield run


def _books() -> list[list[datetime]]:
    scenario = fixture_scenario_params()
    anchors = list_sunrise_step_anchors(_START, _END, load_fixture_cache(), scenario)
    return [
        [slot.replace(tzinfo=None) for slot in resolve_sunrise_book_step_for_scenario(anchor, scenario).book_slots]
        for anchor in anchors
    ]


def _soc_at_sunrise(df: pd.DataFrame, book: list[datetime]) -> float:
    return float(df.loc[pd.Timestamp(book[0]), "sim_soc"])


def _grid_charged_kwh(df: pd.DataFrame) -> float:
    charged = df["batt_action_kw"].clip(lower=0.0) * float(DEFAULT_DT_H)
    return float(pd.concat([charged, df["import_kwh"]], axis=1).min(axis=1).sum())


@pytest.mark.parametrize("peak_kw", [1.0, 6.0])
@pytest.mark.parametrize(
    "switches",
    [pytest.param(("4", None), id="lookahead-4"), pytest.param(_LOOKAHEAD, id="lookahead-8"), pytest.param(_BOTH, id="with-level")],
)
def test_each_window_keeps_its_energy_and_slots(sim, curves, monkeypatch, peak_kw, switches) -> None:
    curves(peak_kw, spread=True)
    off = sim(_OFF)
    assert off["swimspa_kw"].sum() > 0.0 and off["eauto_kw"].sum() > 0.0, "the fixture must run flex"

    on = sim(switches)

    assert on.index.equals(off.index)
    books = _books()
    assert len(books) == 3
    assert sum(len(book) for book in books) == len(off)
    for book in books:
        index = pd.DatetimeIndex(book)
        for column in _ENERGY_COLUMNS:
            assert on.loc[index, column].sum() == pytest.approx(off.loc[index, column].sum(), abs=1e-6), column


def test_book_matrix_and_its_targets_do_not_see_the_look_ahead(sim, monkeypatch) -> None:
    scenario = fixture_scenario_params()
    cache = load_fixture_cache()
    prices = build_synthetic_prices_df(_START, _END)
    anchor = list_sunrise_step_anchors(_START, _END, cache, scenario)[0]
    _set_switches(monkeypatch, "0", None)
    book_off, meta_off, sa1_off, full_off = build_sunrise_window_matrix(anchor, cache, prices, scenario)

    _set_switches(monkeypatch, "8", None)
    book_on, meta_on, sa1_on, full_on = build_sunrise_window_matrix(anchor, cache, prices, scenario)

    assert book_on == book_off
    assert sa1_on == sa1_off
    assert meta_on.pop("planning_horizon_hours") == meta_off.pop("planning_horizon_hours") + 32
    assert meta_on == meta_off
    assert len(full_on) == len(full_off) + 32


def test_schedule_runs_are_assigned_up_to_the_book_end_with_a_look_ahead(sim, monkeypatch) -> None:
    """A reference run counts for the window it ends in; the fixture has no such consumer."""
    scenario = fixture_scenario_params()
    cache = load_fixture_cache()
    prices = build_synthetic_prices_df(_START, _END)
    anchor = list_sunrise_step_anchors(_START, _END, cache, scenario)[0]
    ends: list[datetime] = []
    real = matrix_builder._resolve_matrix_consumption

    def spy(source, slots, cache_arg, window_end, **kwargs):
        ends.append(window_end)
        return real(source, slots, cache_arg, window_end, **kwargs)

    monkeypatch.setattr(matrix_builder, "_resolve_matrix_consumption", spy)
    _set_switches(monkeypatch, "8", None)

    book, _, _, _ = build_sunrise_window_matrix(anchor, cache, prices, scenario)

    assert ends[0] == book[-1]["slot_datetime"] + timedelta(hours=float(DEFAULT_DT_H))


def test_past_the_book_the_plan_sees_the_flex_as_plain_load(sim, monkeypatch) -> None:
    """Only those rows carry it, and the book's own rows stay as they are."""
    _set_switches(monkeypatch, "8", None)
    scenario = fixture_scenario_params()
    cache = load_fixture_cache()
    prices = build_synthetic_prices_df(_START, _END)
    anchor = list_sunrise_step_anchors(_START, _END, cache, scenario)[0]

    def full_matrix(kw: float):
        monkeypatch.setattr(
            "simulation.reference_ladder.reference_flex_shapes_kw",
            lambda slots, _consumers, _source: {"flex": [kw] * len(slots)},
        )
        return build_sunrise_window_matrix(anchor, cache, prices, scenario)

    book, meta, _, without = full_matrix(0.0)
    _, _, _, shaped = full_matrix(1.5)

    book_end = max(row["slot_datetime"] for row in book)
    past = [i for i, row in enumerate(without) if row["slot_datetime"] > book_end]
    assert len(past) == 33, "the SA₂ slot, which the book excludes, and 8 h of look-ahead"
    for index, (plain, with_flex) in enumerate(zip(without, shaped)):
        added = 1.5 if index in past else 0.0
        assert with_flex["expected_p_act"] == pytest.approx(plain["expected_p_act"] + added, abs=1e-3)
    assert meta["book_hours"] == len(book)


@pytest.mark.parametrize("peak_kw", [1.0, 6.0])
def test_lookahead_lowers_the_cost_of_a_dear_morning(sim, curves, peak_kw) -> None:
    """The reason for the prototype: the battery no longer runs empty right before the dear hours."""
    curves(peak_kw, spread=True)

    off = sim(_OFF)
    on = sim(_LOOKAHEAD)

    assert on["sim_cost"].sum() < off["sim_cost"].sum() - 0.1
    assert _soc_at_sunrise(on, _books()[1]) > _soc_at_sunrise(off, _books()[1]) + 20.0


def test_level_raises_the_night_level_up_to_half_the_battery(sim, curves) -> None:
    curves(1.0, spread=False)

    without = sim(_LOOKAHEAD)
    held = sim(_BOTH)

    second_book = _books()[1]
    assert _soc_at_sunrise(without, second_book) == pytest.approx(10.0, abs=0.5)
    assert 30.0 < _soc_at_sunrise(held, second_book) <= 50.0


@pytest.mark.parametrize("spread", [False, True], ids=["flat", "dear-morning"])
def test_level_adds_no_grid_charging_in_a_run(sim, curves, spread) -> None:
    curves(1.0, spread=spread)

    assert _grid_charged_kwh(sim(_BOTH)) <= _grid_charged_kwh(sim(_LOOKAHEAD)) + 0.01


def test_level_changes_nothing_on_days_that_fill_the_battery(sim, curves) -> None:
    curves(12.0, spread=False)

    pd.testing.assert_frame_equal(sim(_BOTH), sim(_LOOKAHEAD))

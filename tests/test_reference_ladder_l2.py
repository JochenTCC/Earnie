"""RuleRef P2: L2 rules on top of the L1 profile (spec § 4)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import pytest

from optimizer.sim_baseline import (
    DEFAULT_RULE_PARAMS,
    SURPLUS_BATTERY_FIRST,
    available_slot_prices,
    build_rule_based_flex_kw_per_hour,
    build_shaped_flex_kw_per_slot,
)
from optimizer.slot_duration import energy_kwh_from_kw
from simulation.horizon_mode import SUNRISE_WINDOW
from tests.fixtures.backtesting_fixtures import (
    LOW_EAUTO_DAY,
    SOC_CHAIN_END_DAY,
    SOC_CHAIN_START_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    fixture_tariff_params,
    load_fixture_cache,
)

os.environ.setdefault("EARNIE_OFFLINE", "1")

DAY = datetime(2026, 6, 1)
SLOTS_PER_DAY = 96
EV = {"id": "ev", "type": "ev", "nominal_power_kw": 11.0, "min_power_kw": 1.4}
HEAT_PUMP = {
    "id": "wp",
    "type": "thermal_annual",
    "nominal_power_kw": 2.0,
    "min_power_kw": 2.0,
    "min_on_quarterhours": 1,
}
FLEX_GENERIC = {"id": "pumpe", "type": "generic", "nominal_power_kw": 2.0}
WINDOW_GENERIC = {
    "id": "spueler",
    "type": "generic",
    "nominal_power_kw": 2.0,
    "generic_flex_window": {"start_hour": 5, "start_shift_h": 4.0, "duration_h": 1.0},
}
NO_BATTERY = {
    "battery_capacity_kwh": 0.0,
    "efficiency": 1.0,
    "min_soc": 0.0,
    "max_soc": 100.0,
    "max_power_kw": 0.0,
}
BATTERY = {
    "battery_capacity_kwh": 10.0,
    "efficiency": 1.0,
    "min_soc": 0.0,
    "max_soc": 100.0,
    "max_power_kw": 5.0,
}


def _slot(index: int) -> datetime:
    return DAY + timedelta(minutes=15 * index)


def _matrix(slots: int = 2 * SLOTS_PER_DAY, *, pv: dict[int, float] | None = None) -> list[dict]:
    return [
        {
            "slot_datetime": _slot(t),
            "expected_p_pv": (pv or {}).get(t, 0.0),
            "expected_p_act": 1.0,
        }
        for t in range(slots)
    ]


def _prices(special: dict[int, float] | None = None, base: float = 20.0) -> dict[datetime, float]:
    return {_slot(t): (special or {}).get(t, base) for t in range(3 * SLOTS_PER_DAY)}


def _shape(values: dict[int, float], slots: int = 2 * SLOTS_PER_DAY) -> list[float]:
    return [values.get(t, 0.0) for t in range(slots)]


def _build(
    consumer: dict,
    target: float,
    shape: dict[int, float],
    eligible: list[int] | None = None,
    *,
    matrix: list[dict] | None = None,
    prices: dict[datetime, float] | None = None,
    params: dict = DEFAULT_RULE_PARAMS,
    battery: dict = NO_BATTERY,
    soc: float = 50.0,
):
    matrix = matrix if matrix is not None else _matrix()
    cid = consumer["id"]
    eligible = eligible if eligible is not None else list(range(SLOTS_PER_DAY))
    return build_rule_based_flex_kw_per_hour(
        matrix,
        {cid: target},
        {cid: eligible},
        [consumer],
        {cid: _shape(shape, len(matrix))},
        prices if prices is not None else _prices(),
        params,
        book_indices=list(range(len(matrix))),
        battery_params=battery,
        initial_soc=soc,
    )


def _kw(result, cid: str) -> list[float]:
    return [slot[cid] for slot in result.per_slot]


def _running(result, cid: str) -> dict[int, float]:
    return {t: round(kw, 6) for t, kw in enumerate(_kw(result, cid)) if kw > 1e-6}


@pytest.mark.parametrize("consumer", [EV, HEAT_PUMP, FLEX_GENERIC, WINDOW_GENERIC])
def test_no_rule_firing_equals_the_l1_profile(consumer):
    """Flat prices, no PV: every consumer type keeps its L1 slots."""
    shape = {20: 1.0, 21: 2.0, 60: 1.0}
    eligible = list(range(SLOTS_PER_DAY))
    cid = consumer["id"]
    l1 = build_shaped_flex_kw_per_slot(
        2 * SLOTS_PER_DAY, [consumer], {cid: 1.0}, {cid: _shape(shape)}, {cid: eligible}
    )
    result = _build(consumer, 1.0, shape, eligible)
    assert _kw(result, cid) == pytest.approx(_kw(l1, cid))


def test_energy_is_exact_when_several_rules_fire_per_consumer():
    matrix = _matrix(pv={30: 8.0, 31: 8.0, 32: 3.0})
    prices = _prices({40: 50.0, 41: 50.0, 70: 60.0, 71: 60.0})
    consumers = [EV, HEAT_PUMP, FLEX_GENERIC]
    targets = {"ev": 6.0, "wp": 2.0, "pumpe": 1.0}
    shapes = {
        "ev": _shape({40: 2.0, 41: 2.0, 80: 4.0}),
        "wp": _shape({40: 2.0, 41: 2.0, 70: 2.0}),
        "pumpe": _shape({70: 1.0, 71: 1.0}),
    }
    eligible = list(range(SLOTS_PER_DAY))
    result = build_rule_based_flex_kw_per_hour(
        matrix,
        targets,
        {cid: eligible for cid in targets},
        consumers,
        shapes,
        prices,
        DEFAULT_RULE_PARAMS,
        book_indices=list(range(len(matrix))),
        battery_params=BATTERY,
        initial_soc=30.0,
    )
    for cid, target in targets.items():
        assert energy_kwh_from_kw(_kw(result, cid)) == pytest.approx(target)
        assert max(_kw(result, cid)) <= next(
            c["nominal_power_kw"] for c in consumers if c["id"] == cid
        )


def test_lock_defers_and_catches_up_in_the_next_allowed_slots():
    expensive = {40: 50.0, 41: 50.0, 42: 50.0, 43: 50.0}
    result = _build(
        HEAT_PUMP,
        1.0,
        {40: 1.0, 41: 1.0, 42: 1.0, 43: 1.0},
        prices=_prices(expensive),
    )
    assert _running(result, "wp") == {44: 2.0, 45: 2.0}
    assert energy_kwh_from_kw(_kw(result, "wp")) == pytest.approx(1.0)


def test_flat_tariff_never_locks():
    shape = {t: 1.0 for t in range(40, 44)}
    result = _build(HEAT_PUMP, 1.0, shape, prices=_prices(base=33.3))
    assert _running(result, "wp") == {t: 1.0 for t in range(40, 44)}


def test_lock_quantile_comes_from_the_params():
    expensive = _prices({40: 50.0})
    shape = {40: 1.0}
    assert _running(_build(HEAT_PUMP, 0.25, shape, prices=expensive), "wp") == {41: 1.0}
    never = {**DEFAULT_RULE_PARAMS, "lock_quantile": 1.0}
    assert _running(_build(HEAT_PUMP, 0.25, shape, prices=expensive, params=never), "wp") == {
        40: 1.0
    }


def test_available_prices_stop_at_the_last_published_day():
    prices = _prices()
    before = available_slot_prices(DAY.replace(hour=11, minute=45), prices)
    after = available_slot_prices(DAY.replace(hour=12), prices)
    assert len(before) == SLOTS_PER_DAY - 47
    assert len(after) == SLOTS_PER_DAY - 48 + SLOTS_PER_DAY


def test_unpublished_price_does_not_change_the_lock_before_the_publication_hour():
    """10:00 is ranked against today only; a very expensive tomorrow would unlock it."""
    today = {40: 30.0}
    tomorrow = {t: 90.0 for t in range(SLOTS_PER_DAY, 2 * SLOTS_PER_DAY)}
    shape = {40: 1.0}
    alone = _build(HEAT_PUMP, 0.25, shape, prices=_prices(today))
    with_tomorrow = _build(HEAT_PUMP, 0.25, shape, prices=_prices({**today, **tomorrow}))
    assert _running(alone, "wp") == _running(with_tomorrow, "wp") == {41: 1.0}


def test_published_price_changes_the_lock_after_the_publication_hour():
    """The same 13:00 price: locked on today's prices, free once a dear tomorrow is known."""
    slot = 52
    tomorrow = {t: 90.0 for t in range(SLOTS_PER_DAY, 2 * SLOTS_PER_DAY)}
    result = _build(HEAT_PUMP, 0.25, {slot: 1.0}, prices=_prices({slot: 30.0, **tomorrow}))
    assert _running(result, "wp") == {slot: 1.0}


def test_missing_price_inside_the_available_range_fails_loud():
    prices = _prices()
    del prices[_slot(70)]
    with pytest.raises(ValueError, match="Kein Endkundenpreis für 2026-06-01 17:30"):
        _build(HEAT_PUMP, 0.25, {40: 1.0}, prices=prices)


def test_spring_dst_gap_is_not_a_missing_price():
    gap_day = datetime(2026, 3, 29)
    prices = {
        gap_day + timedelta(minutes=15 * t): 20.0
        for t in range(SLOTS_PER_DAY)
        if not 8 <= t < 12
    }
    assert len(available_slot_prices(gap_day, prices)) == SLOTS_PER_DAY - 4


def test_surplus_pull_reduces_later_slots_from_the_back():
    matrix = _matrix(pv={40: 3.0})
    shape = {t: 1.0 for t in range(80, 88)}
    result = _build(EV, 2.0, shape, matrix=matrix)
    assert _running(result, "ev") == {40: 2.0, **{t: 1.0 for t in range(80, 86)}}
    assert energy_kwh_from_kw(_kw(result, "ev")) == pytest.approx(2.0)


def test_surplus_below_the_minimum_power_does_not_start():
    matrix = _matrix(pv={40: 2.0})
    result = _build(EV, 1.0, {80: 4.0}, matrix=matrix)
    assert _running(result, "ev") == {80: 4.0}


def test_thermal_boost_needs_its_on_off_power_and_overrides_the_lock():
    prices = _prices({40: 50.0, 41: 50.0})
    too_little = _build(HEAT_PUMP, 0.5, {60: 2.0}, matrix=_matrix(pv={40: 2.0}), prices=prices)
    assert _running(too_little, "wp") == {60: 2.0}
    boosted = _build(HEAT_PUMP, 0.5, {60: 2.0}, matrix=_matrix(pv={40: 3.0}), prices=prices)
    assert _running(boosted, "wp") == {40: 2.0}


def test_min_on_holds_a_started_run_after_the_surplus_ends():
    consumer = {**EV, "min_on_quarterhours": 3}
    result = _build(consumer, 2.0, {80: 8.0}, matrix=_matrix(pv={40: 3.0}))
    powers = _running(result, "ev")
    assert powers[40] == pytest.approx(2.0)
    assert powers[41] == pytest.approx(1.4)
    assert powers[42] == pytest.approx(1.4)
    assert 43 not in powers
    assert energy_kwh_from_kw(_kw(result, "ev")) == pytest.approx(2.0)


def test_two_consumers_do_not_claim_the_same_surplus():
    matrix = _matrix(pv={40: 4.0})
    second = {**EV, "id": "ev2"}
    result = build_rule_based_flex_kw_per_hour(
        matrix,
        {"ev": 1.0, "ev2": 1.0},
        {"ev": list(range(96)), "ev2": list(range(96))},
        [EV, second],
        {"ev": _shape({80: 4.0}), "ev2": _shape({81: 4.0})},
        _prices(),
        DEFAULT_RULE_PARAMS,
        book_indices=list(range(len(matrix))),
        battery_params=NO_BATTERY,
        initial_soc=50.0,
    )
    assert result.per_slot[40]["ev"] == pytest.approx(3.0)
    assert result.per_slot[40]["ev2"] == 0.0


def test_consumer_first_takes_the_surplus_before_the_battery():
    result = _build(EV, 1.0, {80: 4.0}, matrix=_matrix(pv={40: 3.0}), battery=BATTERY, soc=20.0)
    assert _running(result, "ev")[40] == pytest.approx(2.0)


def test_battery_first_leaves_the_surplus_to_a_battery_with_room():
    params = {**DEFAULT_RULE_PARAMS, "surplus_priority": SURPLUS_BATTERY_FIRST}
    result = _build(
        EV, 1.0, {80: 4.0}, matrix=_matrix(pv={40: 3.0}), battery=BATTERY, soc=20.0, params=params
    )
    assert _running(result, "ev") == {80: 4.0}


def test_battery_first_takes_what_a_full_battery_would_export():
    """PV covers the load up to slot 40, so the battery is still full there."""
    params = {**DEFAULT_RULE_PARAMS, "surplus_priority": SURPLUS_BATTERY_FIRST}
    pv = {**{t: 1.0 for t in range(40)}, 40: 3.0}
    result = _build(
        EV, 1.0, {80: 4.0}, matrix=_matrix(pv=pv), battery=BATTERY, soc=100.0, params=params
    )
    assert _running(result, "ev")[40] == pytest.approx(2.0)


def test_unknown_surplus_priority_fails_loud():
    with pytest.raises(ValueError, match="surplus_priority"):
        _build(EV, 1.0, {80: 4.0}, params={"lock_quantile": 0.75, "surplus_priority": "x"})


def test_deadline_forcing_overrides_the_lock():
    prices = _prices({40: 50.0, 41: 50.0})
    result = _build(HEAT_PUMP, 1.0, {40: 2.0, 41: 2.0}, [40, 41], prices=prices)
    assert _running(result, "wp") == {40: 2.0, 41: 2.0}


def test_deadline_runs_only_what_the_later_slots_cannot_deliver():
    prices = _prices({t: 50.0 for t in range(40, 44)})
    result = _build(HEAT_PUMP, 1.25, {t: 2.0 for t in range(40, 43)}, [40, 41, 42, 43], prices=prices)
    assert _running(result, "wp") == {41: 1.0, 42: 2.0, 43: 2.0}


def test_infeasible_window_fails_loud_with_the_missing_kwh():
    with pytest.raises(ValueError, match=r"'wp'.*fehlen 1\.000 kWh"):
        _build(HEAT_PUMP, 2.0, {40: 2.0}, [40, 41])


def test_cheapest_block_moves_the_cycle_with_its_shape():
    prices = _prices({t: 5.0 for t in range(30, 34)})
    shape = {20: 1.0, 21: 2.0, 22: 2.0, 23: 1.0}
    result = _build(WINDOW_GENERIC, 1.5, shape, list(range(20, 40)), prices=prices)
    assert _running(result, "spueler") == {30: 1.0, 31: 2.0, 32: 2.0, 33: 1.0}
    assert result.no_published_block_ids == []


def test_cheapest_block_does_not_use_tomorrow_when_the_window_opens_before_publication():
    tomorrow_cheap = {t: 1.0 for t in range(SLOTS_PER_DAY + 8, SLOTS_PER_DAY + 12)}
    prices = _prices({**tomorrow_cheap, **{t: 10.0 for t in range(60, 64)}})
    result = _build(WINDOW_GENERIC, 1.0, {40: 1.0, 41: 1.0, 42: 1.0, 43: 1.0}, list(range(40, 130)), prices=prices)
    assert _running(result, "spueler") == {t: 1.0 for t in range(60, 64)}


def test_cheapest_block_uses_tomorrow_when_the_window_opens_after_publication():
    tomorrow_cheap = {t: 1.0 for t in range(SLOTS_PER_DAY + 8, SLOTS_PER_DAY + 12)}
    result = _build(
        WINDOW_GENERIC,
        1.0,
        {60: 1.0, 61: 1.0, 62: 1.0, 63: 1.0},
        list(range(60, 130)),
        prices=_prices(tomorrow_cheap),
    )
    assert _running(result, "spueler") == {
        t: 1.0 for t in range(SLOTS_PER_DAY + 8, SLOTS_PER_DAY + 12)
    }


def test_cheapest_block_without_a_published_start_keeps_the_timing_and_reports_it():
    shape = {t: 1.0 for t in range(40, 100)}
    result = _build(WINDOW_GENERIC, 15.0, shape, list(range(40, 130)))
    assert _running(result, "spueler") == {t: 1.0 for t in range(40, 100)}
    assert result.no_published_block_ids == ["spueler"]


def test_cycle_longer_than_the_window_has_no_start():
    shape = {t: 1.0 for t in [40, 41, 60]}
    result = _build(WINDOW_GENERIC, 0.75, shape, [40, 41, 60])
    assert _running(result, "spueler") == {40: 1.0, 41: 1.0, 60: 1.0}
    assert result.no_published_block_ids == ["spueler"]


def test_ev_has_no_price_lock():
    prices = _prices({40: 90.0})
    result = _build(EV, 1.0, {40: 4.0}, prices=prices)
    assert _running(result, "ev") == {40: 4.0}


def test_generic_without_window_locks_but_has_no_surplus_rule():
    prices = _prices({40: 50.0})
    matrix = _matrix(pv={20: 9.0})
    result = _build(FLEX_GENERIC, 0.25, {40: 1.0}, matrix=matrix, prices=prices)
    assert _running(result, "pumpe") == {41: 1.0}


def test_continuous_load_has_no_rule():
    consumer = {**FLEX_GENERIC, "continuous_load": True}
    prices = _prices({40: 50.0})
    result = _build(consumer, 0.25, {40: 1.0}, matrix=_matrix(pv={20: 9.0}), prices=prices)
    assert _running(result, "pumpe") == {40: 1.0}


def test_slots_outside_the_book_stay_empty():
    matrix = _matrix()
    result = build_rule_based_flex_kw_per_hour(
        matrix,
        {"wp": 0.5},
        {"wp": list(range(40, 96))},
        [HEAT_PUMP],
        {"wp": _shape({40: 2.0})},
        _prices(),
        DEFAULT_RULE_PARAMS,
        book_indices=list(range(40, 96)),
        battery_params=NO_BATTERY,
        initial_soc=50.0,
    )
    assert all(slot["wp"] == 0.0 for slot in result.per_slot[:40])
    assert result.per_slot[40]["wp"] == pytest.approx(2.0)


@pytest.fixture
def ladder_env(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch):
        yield {
            "cache": load_fixture_cache(),
            "scenario": fixture_scenario_params(),
            "prices": build_synthetic_prices_df(
                pd.Timestamp("2024-07-01"), pd.Timestamp("2026-06-26")
            ),
        }


def _run_step(env, step: str, start: str, end: str, **kwargs):
    from simulation import reference_ladder

    prices = kwargs.pop("prices", env["prices"])
    return getattr(reference_ladder, f"compute_{step}_reference_costs")(
        pd.Timestamp(start),
        pd.Timestamp(end),
        env["scenario"],
        prices,
        env["cache"],
        initial_soc=50.0,
        horizon_mode=SUNRISE_WINDOW,
        **kwargs,
    )


def test_l2_passes_the_plausibility_check_and_books_the_same_slots_as_l1(ladder_env):
    l1 = _run_step(ladder_env, "l1", SOC_CHAIN_START_DAY, SOC_CHAIN_END_DAY)
    l2 = _run_step(ladder_env, "l2", SOC_CHAIN_START_DAY, SOC_CHAIN_END_DAY)
    assert l2.plausibility.results
    assert l2.plausibility.failed == []
    assert list(l2.frame.index) == list(l1.frame.index)
    assert l2.frame["k_act"].tolist() == pytest.approx(l1.frame["k_act"].tolist())


def _spot_tariff_env(env: dict) -> dict:
    """The fixture scenario has a fixed tariff, on which the lock never fires."""
    tariffs = fixture_tariff_params("de_spot_test", "fixed_37ct", timezone_name="Europe/Berlin")
    return {**env, "scenario": {**env["scenario"], **tariffs}}


def test_rules_move_energy_on_a_spot_tariff_and_keep_it_per_window(ladder_env):
    env = _spot_tariff_env(ladder_env)
    # The fixture's flex runs in the morning; a morning peak is what the lock must avoid.
    env["prices"] = build_synthetic_prices_df(
        pd.Timestamp("2024-07-01"), pd.Timestamp("2026-06-26"), peak_hour=10, peak_cent=80.0
    )
    l1 = _run_step(env, "l1", SOC_CHAIN_START_DAY, SOC_CHAIN_END_DAY)
    l2 = _run_step(env, "l2", SOC_CHAIN_START_DAY, SOC_CHAIN_END_DAY)
    assert l2.frame["k_act"].nunique() > 1
    assert l2.plausibility.failed == []
    assert l2.frame["consumption_kw"].to_numpy() != pytest.approx(l1.frame["consumption_kw"].to_numpy())
    # Chart rows round flex to 0.01 kW per slot; the builder tests check the exact energy.
    assert l2.frame["consumption_kw"].sum() == pytest.approx(l1.frame["consumption_kw"].sum(), abs=0.1)


def test_fixed_tariff_never_locks_on_the_fixture(ladder_env):
    """Only the SwimSpa has a target that day and only the lock applies to it."""
    l1 = _run_step(ladder_env, "l1", LOW_EAUTO_DAY, LOW_EAUTO_DAY)
    l2 = _run_step(ladder_env, "l2", LOW_EAUTO_DAY, LOW_EAUTO_DAY)
    for column in ("consumption_kw", "import_kwh", "export_kwh", "sim_cost", "sim_soc"):
        assert l2.frame[column].to_numpy() == pytest.approx(l1.frame[column].to_numpy()), column


def test_config_ev_without_a_type_has_no_lock_but_the_surplus_rule():
    consumer = {
        "id": "eauto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "charging_schedule": {"enabled": True},
    }
    expensive = _build(consumer, 1.0, {40: 3.5, 41: 0.5}, prices=_prices({40: 90.0, 41: 90.0}))
    assert _running(expensive, "eauto") == {40: 3.5, 41: 0.5}
    pulled = _build(consumer, 1.0, {80: 4.0}, matrix=_matrix(pv={40: 3.0}))
    assert _running(pulled, "eauto")[40] == pytest.approx(2.0)


def test_price_series_matches_the_booked_price(ladder_env):
    from simulation.reference_ladder import _end_customer_price_series

    result = _run_step(ladder_env, "l2", LOW_EAUTO_DAY, LOW_EAUTO_DAY)
    index = result.frame.index
    series = _end_customer_price_series(
        index[0].to_pydatetime(),
        index[-1].to_pydatetime(),
        ladder_env["prices"],
        ladder_env["scenario"],
    )
    for ts, booked in result.frame["k_act"].items():
        assert series[ts.to_pydatetime()] == pytest.approx(booked)


def test_market_data_ending_inside_the_available_range_fails_loud(ladder_env):
    day = pd.Timestamp(LOW_EAUTO_DAY)
    prices = ladder_env["prices"]
    index = prices.index.tz_localize(None) if prices.index.tz is not None else prices.index
    truncated = prices[index < day + pd.Timedelta(days=1)]
    with pytest.raises(ValueError, match="Kein Börsenpreis"):
        _run_step(ladder_env, "l2", LOW_EAUTO_DAY, LOW_EAUTO_DAY, prices=truncated)


def test_l1_does_not_need_prices_past_the_window(ladder_env):
    """The lock's range is an L2 requirement; L1 keeps running on what the matrix needs."""
    assert _run_step(ladder_env, "l1", LOW_EAUTO_DAY, LOW_EAUTO_DAY).frame["sim_cost"].notna().all()

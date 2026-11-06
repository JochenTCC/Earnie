"""SE forecast mode: plan on forecasts, book on actuals (``docs/dev/se-forecast-mode.md``)."""
from __future__ import annotations

import copy
import os
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from data.backtesting_prices import BacktestingPriceResources
from optimizer.sim_horizon_types import _HorizonOptions
from optimizer.simulation import _booking_rows, simulate_horizon
from scripts.run_backtesting import _build_arg_parser
from scripts.run_reference_ladder import (
    _build_arg_parser as _ladder_parser,
    _forecast_argv,
    _validate_forecast_args,
)
from simulation.anchor_step import _simulate_plan_horizon
from simulation.engine import run_simulation
from simulation.forecast_mode import (
    ForecastPlanner,
    PvForecastSource,
    load_deviation_kw,
    parse_plan_forecast,
)
from simulation.historical_cache import HistoricalDataCache
from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW
from simulation.reference_ladder_export import (
    ForecastRun,
    assert_references_match,
    daily_ladder_frame,
    summary_frame,
)
from tests.fixtures.backtesting_fixtures import (
    HIGH_EAUTO_DAY,
    SOC_CHAIN_END_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    fixture_tariff_params,
    load_fixture_cache,
)
from tests.test_reference_ladder_export import _BATTERY, _all_hourly, _block, _hourly, _meta

os.environ.setdefault("EARNIE_OFFLINE", "1")


@pytest.fixture
def forecast_env(monkeypatch):
    import config

    with activate_backtesting_fixtures(monkeypatch):
        scenario = {
            **fixture_scenario_params(),
            **fixture_tariff_params("de_spot_test", "fixed_37ct", timezone_name="Europe/Berlin"),
        }
        yield {
            "cache": load_fixture_cache(),
            "scenario": scenario,
            "prices": build_synthetic_prices_df(
                pd.Timestamp("2024-07-01"), pd.Timestamp("2026-06-26")
            ),
            "start": pd.Timestamp(HIGH_EAUTO_DAY),
            "end": pd.Timestamp(SOC_CHAIN_END_DAY),
            "feed_in": config.get_backtesting_feed_in_settings(runtime_override=scenario),
        }


def _run(env, **kwargs):
    return run_simulation(
        env["start"],
        env["end"],
        env["scenario"],
        env["prices"],
        cache=env["cache"],
        horizon_mode=SUNRISE_WINDOW,
        **kwargs,
    )


def _half_pv(self, slots):
    return [round(0.5 * kw, 3) for kw in self._cache.get_pv_for_slots(slots, scenario_params=self._params)]


# --- plan on actuals reproduces the plain run


def _replay_schedules(monkeypatch):
    """The second run gets the first run's schedules, if the MILP sees the same matrix.

    CBC can pick another of several equal optima under load, which is not what this compares.
    """
    import optimizer.simulation as simulation

    solve = simulation.milp_horizon_schedule
    stored: dict = {}

    def _memo(matrix, soc, **kwargs):
        key = (matrix[0]["slot_datetime"], round(float(soc), 6))
        if key in stored:
            assert stored[key][0] == matrix
            return copy.deepcopy(stored[key][1])
        schedule = solve(matrix, soc, **kwargs)
        stored[key] = (copy.deepcopy(matrix), copy.deepcopy(schedule))
        return schedule

    monkeypatch.setattr(simulation, "milp_horizon_schedule", _memo)
    return stored


def test_empty_forecast_set_reproduces_the_perfect_foresight_run(forecast_env, monkeypatch):
    stored = _replay_schedules(monkeypatch)
    perfect, plaus_perfect, _ = _run(forecast_env)
    solved = len(stored)
    replay, plaus_replay, _ = _run(forecast_env, plan_forecast=())
    assert solved and len(stored) == solved
    pd.testing.assert_frame_equal(perfect, replay)
    assert perfect.attrs == replay.attrs
    assert len(plaus_replay.failed) == len(plaus_perfect.failed)


# --- deviating plan, actual booking


def test_deviating_pv_changes_the_result_but_not_what_is_booked_as_pv(forecast_env, monkeypatch):
    perfect, _, _ = _run(forecast_env)
    monkeypatch.setattr(PvForecastSource, "__init__", _plain_init)
    monkeypatch.setattr(PvForecastSource, "kw_for_slots", lambda _self, slots: [0.0] * len(slots))
    booked, plausibility, _ = _run(forecast_env, plan_forecast=("pv",))
    assert list(booked.index) == list(perfect.index)
    assert booked["pv_kw"].tolist() == perfect["pv_kw"].tolist()
    assert booked["k_act"].tolist() == perfect["k_act"].tolist()
    # A plan that expects no PV costs more once the real PV is booked.
    assert booked["sim_cost"].sum() > perfect["sim_cost"].sum() + 0.5
    assert not plausibility.failed


def _plain_init(self, scenario_params, cache):
    self._params = scenario_params
    self._cache = cache


def test_energy_parity_per_window_with_deviating_inputs(forecast_env, monkeypatch):
    monkeypatch.setattr(PvForecastSource, "__init__", _plain_init)
    monkeypatch.setattr(PvForecastSource, "kw_for_slots", _half_pv)
    perfect, _, _ = _run(forecast_env)
    booked, plausibility, _ = _run(forecast_env, plan_forecast=("pv",))
    assert plausibility.results and not plausibility.failed
    assert booked["consumption_kw"].sum() == pytest.approx(perfect["consumption_kw"].sum(), rel=1e-3)


def test_booked_price_is_the_actual_price_while_the_plan_sees_another(forecast_env, monkeypatch):
    # Days differ, or the mirror would hit the actual price exactly.
    prices = forecast_env["prices"]
    forecast_env["prices"] = prices * (1.0 + 0.1 * (prices.index.dayofyear % 5).to_numpy()[:, None])
    perfect, _, _ = _run(forecast_env)
    plans: list[tuple[list[dict], list[dict]]] = []
    original = ForecastPlanner.plan_matrix

    def _spy(self, booking_matrix, planning_moment):
        plan = original(self, booking_matrix, planning_moment)
        plans.append((plan, booking_matrix, planning_moment))
        return plan

    monkeypatch.setattr(ForecastPlanner, "plan_matrix", _spy)
    booked, _, _ = _run(
        forecast_env,
        plan_forecast=("price",),
        price_resources=BacktestingPriceResources(strategy="mirror"),
    )
    assert booked["k_act"].tolist() == perfect["k_act"].tolist()
    assert booked["k_push_act"].tolist() == perfect["k_push_act"].tolist()
    assert plans
    differs = False
    for plan, actual, moment in plans:
        for plan_row, actual_row in zip(plan, actual):
            published = plan_row["slot_datetime"].date() <= moment.date()
            if published:
                assert plan_row["price_buy"] == pytest.approx(actual_row["price_buy"])
            else:
                assert plan_row["price_source"] != "day_ahead"
            differs = differs or plan_row["k_act"] != actual_row["k_act"]
    assert differs


def test_soc_chain_of_the_replay_follows_the_booked_battery_power(forecast_env, monkeypatch):
    """Also across the window edge: the next window starts from the replayed SoC."""
    from simulation.engine_scenario import _scenario_to_battery_params

    monkeypatch.setattr(PvForecastSource, "__init__", _plain_init)
    monkeypatch.setattr(PvForecastSource, "kw_for_slots", _half_pv)
    booked, _, _ = _run(forecast_env, plan_forecast=("pv",))
    battery = _scenario_to_battery_params(forecast_env["scenario"])
    capacity, efficiency = battery["battery_capacity_kwh"], battery["efficiency"]
    soc = booked["sim_soc"].to_numpy()
    power = booked["batt_action_kw"].to_numpy()
    assert np.abs(power).max() > 0.0
    energy = np.where(power >= 0, power * efficiency, power / efficiency) * 0.25
    # Column rounding: SoC to 0.1 %, power to 0.01 kW.
    assert np.abs(soc[1:] - (soc[:-1] + energy[:-1] / capacity * 100.0)).max() < 0.2


def test_forecast_mode_needs_the_sunrise_window(forecast_env):
    with pytest.raises(ValueError, match="sunrise_window"):
        run_simulation(
            forecast_env["start"],
            forecast_env["end"],
            forecast_env["scenario"],
            forecast_env["prices"],
            cache=forecast_env["cache"],
            horizon_mode=FIXED_24H,
            plan_forecast=(),
        )


def test_price_forecast_and_strategy_belong_together(forecast_env):
    kwargs = dict(
        scenario_params=forecast_env["scenario"],
        cache=forecast_env["cache"],
        prices_df=forecast_env["prices"],
        feed_in_settings=forecast_env["feed_in"],
    )
    with pytest.raises(ValueError, match="Preisstrategie"):
        ForecastPlanner(("price",), price_resources=None, **kwargs)
    with pytest.raises(ValueError, match="Preisstrategie"):
        ForecastPlanner((), price_resources=BacktestingPriceResources(strategy="mirror"), **kwargs)


# --- booking rows


def _row(slot_hour: int, act: float, pv: float, price: float) -> dict:
    return {
        "slot_datetime": datetime(2026, 6, 10, slot_hour),
        "expected_p_act": act,
        "expected_p_total": act,
        "expected_p_pv": pv,
        "k_act": price,
        "price_buy": price,
        "price_source": "x",
        "k_push_act": 1.0,
    }


def _options(start: int, hours: int) -> _HorizonOptions:
    return _HorizonOptions(None, False, 3, hours, start, None, None, None)


def test_booking_rows_take_actuals_inside_the_book_only():
    plan = [_row(h, 1.0, 2.0, 10.0) for h in range(3)]
    actual = [_row(h, 3.0, 4.0, 20.0) for h in range(3)]
    rows = _booking_rows(plan, plan, actual, _options(1, 1))
    assert rows[0]["expected_p_pv"] == 2.0 and rows[0]["k_act"] == 10.0
    assert rows[1]["expected_p_pv"] == 4.0 and rows[1]["k_act"] == 20.0
    assert rows[2]["expected_p_act"] == 1.0


def test_booking_rows_carry_what_the_preparation_added():
    raw = [_row(0, 1.0, 2.0, 10.0)]
    prepared = [{**raw[0], "expected_p_act": 1.5}]
    rows = _booking_rows(raw, prepared, [_row(0, 3.0, 4.0, 20.0)], _options(0, 1))
    assert rows[0]["expected_p_act"] == pytest.approx(3.5)


def test_booking_rows_fail_loud_on_another_slot():
    with pytest.raises(ValueError, match="Slot"):
        _booking_rows(
            [_row(0, 1.0, 2.0, 10.0)],
            [_row(0, 1.0, 2.0, 10.0)],
            [_row(1, 1.0, 2.0, 10.0)],
            _options(0, 1),
        )


def test_booking_matrix_needs_the_open_loop_path():
    with pytest.raises(ValueError, match="commit_hours"):
        simulate_horizon([_row(0, 1.0, 2.0, 10.0)], 50.0, commit_hours=1, booking_matrix=[])


def test_plain_run_does_not_pass_a_booking_matrix(monkeypatch):
    """Without forecast mode the horizon call stays as it was."""
    seen = {}

    def _fake(matrix, soc, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr("simulation.anchor_step._simulate_horizon", _fake)
    plan = type(
        "Plan",
        (),
        dict(
            matrix=[],
            meta={"consumer_daily_targets_kwh": {}},
            sunrise_soc_min_index=None,
            commit_hours=1,
            disable_soc_anchor=True,
            flex_book_hours=None,
            flex_book_start=0,
            soc_hold_index=None,
            soc_hold_percent=None,
        ),
    )()
    monkeypatch.setattr("simulation.anchor_step._flexible_consumers_from_scenario", lambda _p: [])
    _simulate_plan_horizon(
        plan, 50.0, battery_params={}, hours_done=0, collect_cbc=False, scenario_params={}
    )
    assert "booking_matrix" not in seen


# --- PV forecast source


class _FakePv:
    def __init__(self, actual_kw: float) -> None:
        self.actual_kw = actual_kw

    def get_pv_for_slots(self, slots, *, scenario_params):
        return [self.actual_kw] * len(slots)


def _pv_source(monkeypatch, wm2: pd.Series, *, actual_kw: float = 2.0, kwp: float = 10.0):
    from data.modeled_climate import ModeledClimateContext, ModeledPvSystem
    from data.open_meteo_solar_archive import TiltedSurface

    systems = [ModeledPvSystem("a", "A", TiltedSurface(30.0, 0.0), kwp)] if kwp else []
    climate = ModeledClimateContext(lat=47.0, lon=9.0, timezone="Europe/Vienna", pv_systems=systems)
    monkeypatch.setattr(ModeledClimateContext, "from_scenario", classmethod(lambda cls, _p: climate))
    monkeypatch.setattr(
        "data.open_meteo_solar_archive.fetch_hourly_tilted_irradiance_day1_forecast_wm2_series",
        lambda *_a, **_k: wm2,
    )
    return PvForecastSource({}, _FakePv(actual_kw))


def _june_hours() -> pd.DatetimeIndex:
    return pd.date_range("2026-06-01", "2026-07-01", freq="h", inclusive="left")


def test_pv_forecast_is_scaled_to_the_months_booked_total(monkeypatch):
    hours = _june_hours()
    values = np.where(hours.hour == 12, 500.0, 0.0)
    source = _pv_source(monkeypatch, pd.Series(values, index=hours))
    planned = source.kw_for_slots([ts.to_pydatetime() for ts in hours])
    assert sum(planned) == pytest.approx(2.0 * len(hours), rel=1e-3)
    assert planned[12] > 0.0 and planned[11] == 0.0


def test_pv_forecast_holds_the_hour_on_quarter_hour_slots(monkeypatch):
    hours = _june_hours()
    source = _pv_source(monkeypatch, pd.Series(np.arange(len(hours), dtype=float) + 1.0, index=hours))
    a, b = source.kw_for_slots([datetime(2026, 6, 2, 5, 0), datetime(2026, 6, 2, 5, 45)])
    assert a == b


def test_pv_forecast_fails_loud_on_a_missing_run(monkeypatch):
    hours = _june_hours()
    wm2 = pd.Series(100.0, index=hours)
    wm2.iloc[:48] = np.nan
    source = _pv_source(monkeypatch, wm2)
    with pytest.raises(ValueError, match="2026-06-01 10:00"):
        source.kw_for_slots([datetime(2026, 6, 1, 10, 0)])
    assert source.kw_for_slots([datetime(2026, 6, 3, 10, 0)])[0] > 0.0


def test_pv_forecast_without_a_forecast_for_booked_pv_fails_loud(monkeypatch):
    hours = _june_hours()
    source = _pv_source(monkeypatch, pd.Series(0.0, index=hours))
    with pytest.raises(ValueError, match="nicht skalierbar"):
        source.kw_for_slots([datetime(2026, 6, 3, 10, 0)])


def test_pv_forecast_without_a_plant_is_zero(monkeypatch):
    source = _pv_source(monkeypatch, pd.Series(dtype=float), actual_kw=0.0, kwp=0.0)
    assert source.kw_for_slots([datetime(2026, 6, 3, 10, 0)]) == [0.0]


# --- load forecast


def _baseload_cache(values: dict[str, float]) -> HistoricalDataCache:
    frame = pd.DataFrame({"BaseLoad": list(values.values())}, index=pd.to_datetime(list(values)))
    cache = HistoricalDataCache()
    cache._consumption_df = frame
    cache._consumption_df_hourly = frame
    cache._pv_series = pd.Series(dtype=float)
    return cache


def test_load_profile_leaves_the_target_day_out_of_its_mean():
    cache = _baseload_cache(
        {"2026-06-01 10:00": 1.0, "2026-06-08 10:00": 2.0, "2026-06-15 10:00": 6.0}
    )
    deviation = cache.get_baseload_profile_deviation_kw([datetime(2026, 6, 15, 10, 45)])
    assert deviation == pytest.approx([1.5 - 6.0])


def test_load_profile_without_another_day_fails_loud():
    cache = _baseload_cache({"2026-06-01 10:00": 1.0})
    with pytest.raises(ValueError, match="keinen anderen Tag"):
        cache.get_baseload_profile_deviation_kw([datetime(2026, 6, 1, 10, 0)])


def test_flat_profile_house_has_no_load_deviation():
    profile = {"consumers": [], "baseload_kwh": 3000.0}
    slots = [datetime(2026, 6, 15, 10, 0)]
    assert load_deviation_kw(
        slots, {"consumption_source": "profile_spec", "_house_profile": profile}, None
    ) == [0.0]


def test_logged_day_house_plans_on_the_profile():
    cache = _baseload_cache(
        {"2026-06-01 10:00": 1.0, "2026-06-08 10:00": 2.0, "2026-06-15 10:00": 6.0}
    )
    deviation = load_deviation_kw(
        [datetime(2026, 6, 15, 10, 0)], {"consumption_source": "logged_day"}, cache
    )
    assert deviation == pytest.approx([-4.5])


def test_load_plan_shifts_the_row_and_keeps_it_non_negative(forecast_env, monkeypatch):
    monkeypatch.setattr(
        "simulation.forecast_mode.load_deviation_kw", lambda slots, _p, _c: [-5.0, 1.0][: len(slots)]
    )
    planner = ForecastPlanner(
        ("load",),
        scenario_params=forecast_env["scenario"],
        cache=forecast_env["cache"],
        prices_df=forecast_env["prices"],
        feed_in_settings=forecast_env["feed_in"],
        price_resources=None,
    )
    actual = [_row(0, 1.0, 2.0, 10.0), _row(1, 1.0, 2.0, 10.0)]
    plan = planner.plan_matrix(actual, datetime(2026, 6, 10, 0))
    assert [row["expected_p_act"] for row in plan] == [0.0, 2.0]
    assert [row["expected_p_act"] for row in actual] == [1.0, 1.0]


# --- parsing and CLI


def test_parse_plan_forecast():
    assert parse_plan_forecast(None) is None
    assert parse_plan_forecast("") == ()
    assert parse_plan_forecast("load, price") == ("price", "load")
    with pytest.raises(ValueError, match="wetter"):
        parse_plan_forecast("wetter")


def test_backtesting_cli_takes_an_empty_forecast_set():
    args = _build_arg_parser().parse_args(["--plan-forecast="])
    assert parse_plan_forecast(args.plan_forecast) == ()


def test_ladder_cli_needs_a_price_strategy_for_price_forecasts():
    parser = _ladder_parser()
    base = ["--workers", "1", "--output-dir", "x"]
    with pytest.raises(SystemExit):
        _validate_forecast_args(parser.parse_args(base))
    _validate_forecast_args(parser.parse_args([*base, "--skip-forecast"]))
    _validate_forecast_args(parser.parse_args([*base, "--forecast-price-strategy", "mirror"]))
    _validate_forecast_args(parser.parse_args([*base, "--plan-forecast", "pv,load"]))
    with pytest.raises(SystemExit):
        _validate_forecast_args(
            parser.parse_args([*base, "--plan-forecast", "pv", "--forecast-price-strategy", "mirror"])
        )


def test_ladder_cli_forwards_the_forecast_run():
    args = _ladder_parser().parse_args(
        ["--workers", "3", "--output-dir", "x", "--forecast-price-strategy", "mirror", "--scenario", "a"]
    )
    argv = _forecast_argv(args, "x/forecast_mode")
    assert argv[:4] == ["--workers", "3", "--output-dir", "x/forecast_mode"]
    assert "--plan-forecast=price,pv,load" in argv
    assert argv[argv.index("--price-strategy") + 1] == "mirror"
    assert argv[argv.index("--scenario") + 1] == "a"


# --- export


@pytest.fixture
def plain_setup(monkeypatch):
    monkeypatch.setattr(
        "simulation.engine_scenario._scenario_to_battery_params", lambda _params: dict(_BATTERY)
    )
    monkeypatch.setattr(
        "simulation.engine_scenario._flexible_consumers_from_scenario", lambda _params: []
    )


def _forecast_run(*, l3_per_slot: float = 0.015, l2_per_slot: float = 0.02) -> ForecastRun:
    meta = _meta()
    meta["period"] = {**meta["period"], "plan_forecast": ["price", "pv"], "price_strategy": "mirror"}
    meta["plausibility"] = {"a": {"failed_count": 2}}
    meta["ladder_soc_correction"]["a"]["soc_end_percent"] = 40.0
    hourly = pd.concat(
        [
            _hourly("ref:a", 0.04),
            _hourly("l1:a", 0.03),
            _hourly("l2:a", l2_per_slot),
            _hourly("a", l3_per_slot),
        ]
    )
    return ForecastRun(meta, hourly)


def test_summary_carries_the_range(plain_setup):
    summary = summary_frame(_meta(), _all_hourly(), {"a": {}}, _forecast_run())
    row = summary.iloc[0]
    slots = 2 * 96
    assert row["l3_eur"] == pytest.approx(slots * 0.01)
    assert row["l3_forecast_eur"] == pytest.approx(slots * 0.015)
    assert row["saving_l2_l3_forecast_eur"] == pytest.approx(slots * 0.02 + 0.27 - slots * 0.015)
    assert row["saving_l2_l3_eur"] > row["saving_l2_l3_forecast_eur"]
    assert row["plausibility_failed_windows_l3_forecast"] == 2
    assert row["soc_end_percent_l3_forecast"] == 40.0
    assert row["plan_forecast"] == "price,pv"
    assert row["price_strategy"] == "mirror"
    assert row["l3_foresight"] == "perfect"


def test_summary_range_carries_the_forecast_runs_own_fuel(plain_setup):
    meta = _meta()
    meta["heat_fuel"] = {rid: _block(30.0) for rid in ("ref:a", "l1:a", "l2:a")} | {"a": _block(20.0)}
    forecast = _forecast_run()
    forecast.meta["heat_fuel"] = {rid: _block(30.0) for rid in ("ref:a", "l1:a", "l2:a")} | {"a": _block(25.0)}
    row = summary_frame(meta, _all_hourly(), {"a": {}}, forecast).iloc[0]
    slots = 2 * 96
    assert row["l3_fuel_eur"] == pytest.approx(4.0)
    assert row["l3_fuel_forecast_eur"] == pytest.approx(5.0)
    assert row["l3_total_forecast_eur"] == pytest.approx(slots * 0.015 + 5.0)
    assert row["saving_l2_l3_with_fuel_forecast_eur"] == pytest.approx(
        slots * 0.02 + 6.0 + 0.27 - (slots * 0.015 + 5.0)
    )
    daily = daily_ladder_frame(meta, _all_hourly(), {"a": {}}, forecast)
    assert daily["l3_fuel_forecast_eur"].sum() == pytest.approx(5.0)
    assert daily["l3_total_forecast_eur"].sum() == pytest.approx(slots * 0.015 + 5.0)


def test_references_must_match_in_fuel_between_the_runs():
    forecast = _forecast_run()
    forecast.meta["heat_fuel"]["l2:a"] = _block(30.0)
    with pytest.raises(ValueError, match="L2.*Brennstoff"):
        assert_references_match(_meta(), _all_hourly(), forecast)


def test_summary_without_a_forecast_run_stays_as_it_was(plain_setup):
    summary = summary_frame(_meta(), _all_hourly(), {"a": {}})
    assert "l3_forecast_eur" not in summary.columns


def test_daily_carries_the_forecast_l3(plain_setup):
    daily = daily_ladder_frame(_meta(), _all_hourly(), {"a": {}}, _forecast_run())
    assert daily.iloc[0]["l3_forecast_eur"] == pytest.approx(96 * 0.015)


def test_daily_fails_loud_on_a_day_the_forecast_run_did_not_book(plain_setup):
    forecast = _forecast_run()
    hourly = forecast.hourly
    forecast = ForecastRun(
        forecast.meta,
        pd.concat([hourly[hourly["scenario_id"] != "a"], _hourly("a", 0.015, days=1)]),
    )
    with pytest.raises(ValueError, match="l3_forecast_eur"):
        daily_ladder_frame(_meta(), _all_hourly(), {"a": {}}, forecast)


def test_references_must_match_between_the_runs():
    assert_references_match(_meta(), _all_hourly(), _forecast_run())
    with pytest.raises(ValueError, match="L2"):
        assert_references_match(_meta(), _all_hourly(), _forecast_run(l2_per_slot=0.03))


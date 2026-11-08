"""RuleRef P5: study export and rule sensitivity (spec §§ 4.7, 5)."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from optimizer.sim_baseline import (
    DEFAULT_RULE_PARAMS,
    SURPLUS_BATTERY_FIRST,
    SURPLUS_CONSUMER_FIRST,
)
from simulation.heat_fuel import heat_fuel_for_result
from simulation.horizon_mode import SUNRISE_WINDOW
from simulation.reference_ladder import SE_START_SOC_PERCENT, compute_l2_reference_costs
from simulation.reference_ladder_export import (
    DAILY_CSV,
    SUMMARY_CSV,
    SensitivityRun,
    daily_ladder_frame,
    has_heating_rod,
    rule_key,
    sensitivity_frame,
    sensitivity_grid,
    summary_frame,
    write_csv,
)
from tests.fixtures.backtesting_fixtures import (
    HIGH_EAUTO_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    fixture_tariff_params,
    load_fixture_cache,
)

os.environ.setdefault("EARNIE_OFFLINE", "1")

_BATTERY = {"battery_capacity_kwh": 10.0, "efficiency": 0.9}


def _hourly(result_id: str, cost_per_slot: float, *, days: int = 2) -> pd.DataFrame:
    slots = 96 * days
    return pd.DataFrame(
        {
            "ts": pd.date_range("2026-06-10", periods=slots, freq="15min"),
            "scenario_id": result_id,
            "sim_cost": cost_per_slot,
            "import_kwh": 0.1,
            "export_kwh": 0.05,
            # L0 has no battery: the series file leaves its column empty.
            "batt_action_kw": float("nan") if result_id.startswith("ref:") else [2.0, -2.0] * (slots // 2),
        }
    )


def _block(fuel_kwh_per_day: float = 0.0, rod_kwh_per_day: float = 0.0, *, price: float = 0.1) -> dict:
    """A log block over the two days of ``_hourly``."""
    return {
        "fuel_kwh": 2 * fuel_kwh_per_day,
        "fuel_eur": 2 * fuel_kwh_per_day * price,
        "rod_kwh": 2 * rod_kwh_per_day,
        "carriers": ["gas"] if fuel_kwh_per_day else [],
        "daily": {
            day: {
                "fuel_kwh": fuel_kwh_per_day,
                "fuel_eur": fuel_kwh_per_day * price,
                "rod_kwh": rod_kwh_per_day,
            }
            for day in ("2026-06-10", "2026-06-11")
        },
    }


def _meta() -> dict:
    return {
        "labels": {"a": "Haus A"},
        "period": {"start": "2026-06-10", "end": "2026-06-11", "horizon_mode": SUNRISE_WINDOW},
        "reference_by_scenario": {"a": "ref:a"},
        "ladder_by_scenario": {"a": {"l1": "l1:a", "l2": "l2:a"}},
        "ladder_report": {
            "l1:a": {"plausibility_failed_windows": 0},
            "l2:a": {"plausibility_failed_windows": 1},
        },
        "ladder_soc_correction": {
            "a": {
                "soc_end_percent": 60.0,
                "p_ref_cent": 30.0,
                "p_ref_basis": "import_weighted",
                "steps": {
                    "l1": {"soc_end_percent": 60.0, "correction_eur": 0.0},
                    "l2": {"soc_end_percent": 50.0, "correction_eur": 0.27},
                },
            }
        },
        "heat_fuel": {result_id: _block() for result_id in ("ref:a", "l1:a", "l2:a", "a")},
    }


def _all_hourly() -> pd.DataFrame:
    return pd.concat(
        [_hourly("ref:a", 0.04), _hourly("l1:a", 0.03), _hourly("l2:a", 0.02), _hourly("a", 0.01)]
    )


@pytest.fixture
def plain_setup(monkeypatch):
    monkeypatch.setattr(
        "simulation.engine_scenario._scenario_to_battery_params", lambda _params: dict(_BATTERY)
    )
    monkeypatch.setattr(
        "simulation.engine_scenario._flexible_consumers_from_scenario", lambda _params: []
    )


def test_grid_has_eight_sets_with_the_default_first():
    grid = sensitivity_grid()
    assert len(grid) == 8
    assert grid[0] == DEFAULT_RULE_PARAMS
    assert {rule_key(params) for params in grid} == {
        (quantile, priority)
        for quantile in (0.50, 0.66, 0.75, 0.90)
        for priority in (SURPLUS_CONSUMER_FIRST, SURPLUS_BATTERY_FIRST)
    }


def test_daily_has_one_row_per_day_and_the_four_steps(plain_setup):
    daily = daily_ladder_frame(_meta(), _all_hourly(), {"a": {}})
    assert list(daily["date"]) == ["2026-06-10", "2026-06-11"]
    row = daily.iloc[0]
    assert row["scenario_id"] == "a"
    assert row["scenario_label"] == "Haus A"
    assert (row["l0_eur"], row["l1_eur"], row["l2_eur"], row["l3_eur"]) == pytest.approx(
        (96 * 0.04, 96 * 0.03, 96 * 0.02, 96 * 0.01)
    )
    assert row["l3_foresight"] == "perfect"
    assert not row["heating_rod"]
    assert row["l2_import_kwh"] == pytest.approx(96 * 0.1)
    assert row["l2_export_kwh"] == pytest.approx(96 * 0.05)
    assert row["l2_battery_throughput_kwh"] == pytest.approx(96 * 2.0 * 0.25)
    assert row["l0_battery_throughput_kwh"] == 0.0


def test_daily_fails_loud_on_a_day_a_step_did_not_book(plain_setup):
    hourly = pd.concat(
        [_hourly("ref:a", 0.04), _hourly("l1:a", 0.03), _hourly("l2:a", 0.02, days=1), _hourly("a", 0.01)]
    )
    with pytest.raises(ValueError, match="2026-06-11.*l2_eur"):
        daily_ladder_frame(_meta(), hourly, {"a": {}})


def test_missing_series_fails_loud(plain_setup):
    with pytest.raises(ValueError, match="ref:a"):
        daily_ladder_frame(_meta(), _hourly("a", 0.01), {"a": {}})


def test_summary_sums_the_days_and_values_the_end_soc(plain_setup):
    row = summary_frame(_meta(), _all_hourly(), {"a": {}}).iloc[0]
    l0, l2, l3 = 192 * 0.04, 192 * 0.02, 192 * 0.01
    assert row["l2_eur"] == pytest.approx(l2)
    assert row["saving_l2_l3_eur"] == pytest.approx(l2 + 0.27 - l3)
    assert row["rule_share"] == pytest.approx((l0 - l2 - 0.27) / (l0 - l3))
    assert row["plausibility_failed_windows_l2"] == 1
    assert row["l3_foresight"] == "perfect"


def _with_fuel(meta: dict, fuel: dict[str, float], rod: dict[str, float] | None = None) -> dict:
    rod = rod or {}
    meta["heat_fuel"] = {rid: _block(kwh, rod.get(rid, 0.0)) for rid, kwh in fuel.items()}
    return meta


def test_fuel_house_without_a_rod_saves_what_it_saves_on_electricity(plain_setup):
    meta = _with_fuel(_meta(), {rid: 30.0 for rid in ("ref:a", "l1:a", "l2:a", "a")})
    row = summary_frame(meta, _all_hourly(), {"a": {}}).iloc[0]
    assert [row[f"l{n}_fuel_eur"] for n in range(4)] == [pytest.approx(6.0)] * 4
    assert row["saving_l2_l3_with_fuel_eur"] == pytest.approx(row["saving_l2_l3_eur"])
    assert row["l2_total_eur"] == pytest.approx(row["l2_eur"] + 6.0)
    assert row["fuel_carriers"] == "gas"


def test_rod_in_a_fuel_house_shows_in_the_saving_and_in_the_rule_share(plain_setup):
    meta = _with_fuel(
        _meta(),
        {"ref:a": 30.0, "l1:a": 30.0, "l2:a": 25.0, "a": 20.0},
        {"l2:a": 4.0, "a": 8.0},
    )
    row = summary_frame(meta, _all_hourly(), {"a": {}}).iloc[0]
    l0, l2, l3 = 192 * 0.04 + 6.0, 192 * 0.02 + 5.0, 192 * 0.01 + 4.0
    assert row["l3_total_eur"] == pytest.approx(l3)
    assert row["saving_l2_l3_with_fuel_eur"] == pytest.approx(l2 + 0.27 - l3)
    assert row["saving_l2_l3_eur"] == pytest.approx(192 * 0.01 + 0.27)  # electricity stays as it was
    assert row["rule_share_with_fuel"] == pytest.approx((l0 - l2 - 0.27) / (l0 - l3))
    assert (row["l2_rod_kwh"], row["l3_rod_kwh"]) == (8.0, 16.0)
    assert (row["l2_fuel_kwh"], row["l3_fuel_kwh"]) == (50.0, 40.0)


def test_daily_sums_to_the_summary_and_compares_with_fuel(plain_setup):
    meta = _with_fuel(
        _meta(),
        {"ref:a": 30.0, "l1:a": 30.0, "l2:a": 25.0, "a": 20.0},
        {"l2:a": 4.0, "a": 8.0},
    )
    daily = daily_ladder_frame(meta, _all_hourly(), {"a": {}})
    summary = summary_frame(meta, _all_hourly(), {"a": {}}).iloc[0]
    for column in ("l2_fuel_eur", "l3_total_eur", "l3_rod_kwh", "l3_fuel_kwh", "l2_import_kwh", "l1_battery_throughput_kwh"):
        assert daily[column].sum() == pytest.approx(summary[column]), column
    assert daily["l2_l3_with_fuel_eur"].sum() == pytest.approx(
        summary["saving_l2_l3_with_fuel_eur"] - summary["l2_soc_correction_eur"]
    )


def test_electric_heat_source_has_no_fuel_term(plain_setup):
    row = summary_frame(_meta(), _all_hourly(), {"a": {}}).iloc[0]
    assert row["l2_fuel_eur"] == 0.0
    assert row["fuel_carriers"] == ""
    assert row["saving_l2_l3_with_fuel_eur"] == pytest.approx(row["saving_l2_l3_eur"])
    assert row["rule_share_with_fuel"] == pytest.approx(row["rule_share"])


def test_log_without_the_fuel_block_fails_loud(plain_setup):
    meta = _meta()
    del meta["heat_fuel"]["l2:a"]
    with pytest.raises(ValueError, match="Brennstoff-Block.*l2:a"):
        summary_frame(meta, _all_hourly(), {"a": {}})
    with pytest.raises(ValueError, match="Brennstoff-Block.*l2:a"):
        daily_ladder_frame(meta, _all_hourly(), {"a": {}})


def test_log_without_daily_fuel_needs_a_new_run(plain_setup):
    meta = _meta()
    del meta["heat_fuel"]["a"]["daily"]
    with pytest.raises(ValueError, match="je Tag.*neu rechnen"):
        daily_ladder_frame(meta, _all_hourly(), {"a": {}})


def test_daily_fails_loud_on_a_booked_day_without_fuel(plain_setup):
    meta = _meta()
    del meta["heat_fuel"]["l2:a"]["daily"]["2026-06-11"]
    with pytest.raises(ValueError, match="2026-06-11.*l2_fuel_eur"):
        daily_ladder_frame(meta, _all_hourly(), {"a": {}})


@pytest.fixture
def gas_consumer(monkeypatch):
    """Real ``heat_fuel`` block: 30 kWh fuel a day, efficiency 0.8, 0.1 €/kWh."""
    from data import modeled_climate
    from house_config import heat_source
    from optimizer import thermal_flex_context

    monkeypatch.setattr(heat_source, "heating_rod_part", lambda consumer: {"id": "rod"})
    monkeypatch.setattr(heat_source, "part_kennung", lambda parent, part: f"{parent}_{part}")
    monkeypatch.setattr(heat_source, "consumer_heat_source", lambda consumer: {"type": "gas"})
    monkeypatch.setattr(heat_source, "heat_source_is_electric", lambda source: False)
    monkeypatch.setattr(heat_source, "heat_source_efficiency", lambda source: 0.8)
    monkeypatch.setattr(heat_source, "fuel_price_eur_per_kwh", lambda source: 0.1)
    monkeypatch.setattr(heat_source, "fuel_co2_g_per_kwh", lambda source: 200.0)
    monkeypatch.setattr(thermal_flex_context, "thermal_daily_fuel_kwh_for_date", lambda *a, **k: 30.0)
    monkeypatch.setattr(modeled_climate.ModeledClimateContext, "from_scenario", staticmethod(lambda params: None))
    return {"_house_profile": {"consumers": [{"id": "heat", "type": "thermal_annual", "heating_system_id": "x"}]}}


def _series_with_rod(rod_kw_per_slot: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-06-10", periods=len(rod_kw_per_slot), freq="15min")
    return pd.DataFrame({"import_kwh": 0.0, "heat_rod_kw": rod_kw_per_slot}, index=index)


def test_fuel_difference_on_the_ladder_is_the_rod_heat_over_the_efficiency(plain_setup, gas_consumer):
    rod_kw = [2.0] * 8 + [0.0] * (2 * 96 - 8)  # 4 kWh of rod heat on the first day
    blocks = {
        "ref:a": heat_fuel_for_result(_series_with_rod([0.0] * 192), gas_consumer),
        "l1:a": heat_fuel_for_result(_series_with_rod([0.0] * 192), gas_consumer),
        "l2:a": heat_fuel_for_result(_series_with_rod(rod_kw), gas_consumer),
        "a": heat_fuel_for_result(_series_with_rod(rod_kw), gas_consumer),
    }
    meta = {**_meta(), "heat_fuel": blocks}
    row = summary_frame(meta, _all_hourly(), {"a": {}}).iloc[0]
    assert row["l0_fuel_kwh"] - row["l2_fuel_kwh"] == pytest.approx(4.0 / 0.8, abs=0.1)
    assert row["l0_fuel_eur"] - row["l2_fuel_eur"] == pytest.approx(4.0 / 0.8 * 0.1, abs=0.01)
    assert row["l2_rod_kwh"] == pytest.approx(4.0)
    daily = daily_ladder_frame(meta, _all_hourly(), {"a": {}})
    assert list(daily["l2_rod_kwh"]) == pytest.approx([4.0, 0.0])
    assert list(daily["l2_fuel_kwh"]) == pytest.approx([30.0 - 4.0 / 0.8, 30.0])


def test_rod_above_the_days_heat_nets_over_the_period(gas_consumer):
    """The heat stays in the store: the total keeps the rod's heat, so the day goes negative."""
    rod_kw = [10.0] * 16 + [0.0] * (2 * 96 - 16)  # 40 kWh on the first day, 50 kWh of fuel
    block = heat_fuel_for_result(_series_with_rod(rod_kw), gas_consumer)
    assert block["fuel_kwh"] == pytest.approx(2 * 30.0 - 40.0 / 0.8)
    assert block["daily"]["2026-06-10"]["fuel_kwh"] == pytest.approx(30.0 - 40.0 / 0.8)
    assert sum(day["fuel_eur"] for day in block["daily"].values()) == pytest.approx(block["fuel_eur"], abs=0.01)


def test_run_reference_ladder_writes_the_fuel_columns(plain_setup, monkeypatch, tmp_path, capsys):
    import scripts.run_reference_ladder as cli

    meta = _with_fuel(_meta(), {"ref:a": 30.0, "l1:a": 30.0, "l2:a": 25.0, "a": 20.0}, {"l2:a": 4.0, "a": 8.0})
    monkeypatch.setattr(cli, "run_backtesting_main", lambda argv: None)
    monkeypatch.setattr(cli, "load_backtesting_log", lambda path: (meta, _all_hourly()))
    monkeypatch.setattr(cli, "scenarios_for_period", lambda *args: {"a": {}})
    monkeypatch.setattr(cli.config, "get_backtesting_scenarios", lambda: {})
    cli.main(["--workers", "1", "--output-dir", str(tmp_path), "--skip-sensitivity", "--skip-forecast"])
    summary = pd.read_csv(tmp_path / SUMMARY_CSV, sep=";", decimal=",").iloc[0]
    assert summary["l3_total_eur"] == pytest.approx(192 * 0.01 + 4.0)
    assert summary["l2_rod_kwh"] == 8.0
    assert summary["l3_fuel_kwh"] == 40.0
    assert summary["fuel_carriers"] == "gas"
    assert summary["saving_l2_l3_with_fuel_eur"] == pytest.approx(192 * 0.02 + 5.0 + 0.27 - (192 * 0.01 + 4.0))
    daily = pd.read_csv(tmp_path / DAILY_CSV, sep=";", decimal=",")
    assert daily["l2_fuel_eur"].sum() == pytest.approx(5.0)
    assert daily["l1_battery_throughput_kwh"].iloc[0] == pytest.approx(48.0)
    assert "Mit Brennstoff (gas)" in capsys.readouterr().out


def test_heating_rod_is_flagged(monkeypatch):
    rod = {"id": "rod", "daily_target_source": "heating_rod"}
    monkeypatch.setattr(
        "simulation.engine_scenario._flexible_consumers_from_scenario", lambda _params: [rod]
    )
    assert has_heating_rod({})


def _runs(**costs: float) -> dict:
    return {
        ("l2:a", rule_key(params)): SensitivityRun(costs.get(f"q{params['lock_quantile']}", 5.0), 50.0, 0, 0.0)
        for params in sensitivity_grid()[1:]
    }


def test_sensitivity_reports_default_and_best_in_hindsight(plain_setup):
    best_key = (0.5, SURPLUS_BATTERY_FIRST)
    runs = {key: SensitivityRun(9.0, 50.0, 0, 0.0) for key in _runs()}
    runs[("l2:a", best_key)] = SensitivityRun(1.0, 50.0, 0, 0.0)
    frame = sensitivity_frame(_meta(), _all_hourly(), {"a": {}}, runs, sensitivity_grid())
    assert len(frame) == 8
    default = frame.loc[frame["is_default"]].iloc[0]
    assert (default["lock_quantile"], default["surplus_priority"]) == rule_key(DEFAULT_RULE_PARAMS)
    # The SE run's own L2, not an eighth run.
    assert default["l2_eur"] == pytest.approx(192 * 0.02)
    assert default["l2_soc_correction_eur"] == pytest.approx(0.27)
    best = frame.loc[frame["is_best_in_hindsight"]]
    assert len(best) == 1
    assert (best.iloc[0]["lock_quantile"], best.iloc[0]["surplus_priority"]) == best_key
    assert best.iloc[0]["saving_l2_l3_eur"] == pytest.approx(1.0 + 0.27 - 192 * 0.01)


def test_best_counts_the_end_soc_term(plain_setup):
    """A cheaper run that ends emptier is not better."""
    cheap_empty, dearer_full = (0.5, SURPLUS_CONSUMER_FIRST), (0.9, SURPLUS_CONSUMER_FIRST)
    runs = {key: SensitivityRun(9.0, 50.0, 0, 0.0) for key in _runs()}
    runs[("l2:a", cheap_empty)] = SensitivityRun(1.0, 0.0, 0, 0.0)
    runs[("l2:a", dearer_full)] = SensitivityRun(1.5, 60.0, 0, 0.0)
    frame = sensitivity_frame(_meta(), _all_hourly(), {"a": {}}, runs, sensitivity_grid())
    best = frame.loc[frame["is_best_in_hindsight"]].iloc[0]
    assert (best["lock_quantile"], best["surplus_priority"]) == dearer_full


def test_best_counts_the_fuel(plain_setup):
    """A rod run that books more electricity and saves more fuel wins, and it shows in the saving."""
    no_rod, with_rod = (0.5, SURPLUS_CONSUMER_FIRST), (0.9, SURPLUS_CONSUMER_FIRST)
    runs = {key: SensitivityRun(9.0, 50.0, 0, 9.0) for key in _runs()}
    runs[("l2:a", no_rod)] = SensitivityRun(1.0, 50.0, 0, 6.0)
    runs[("l2:a", with_rod)] = SensitivityRun(2.0, 50.0, 0, 3.0)
    meta = _with_fuel(_meta(), {"ref:a": 30.0, "l1:a": 30.0, "l2:a": 30.0, "a": 10.0})
    frame = sensitivity_frame(meta, _all_hourly(), {"a": {}}, runs, sensitivity_grid())
    best = frame.loc[frame["is_best_in_hindsight"]].iloc[0]
    assert (best["lock_quantile"], best["surplus_priority"]) == with_rod
    assert best["l2_fuel_eur"] == 3.0
    assert best["saving_l2_l3_with_fuel_eur"] == pytest.approx(2.0 + 0.27 + 3.0 - (192 * 0.01 + 2.0))
    default = frame.loc[frame["is_default"]].iloc[0]
    assert default["l2_fuel_eur"] == pytest.approx(6.0)  # from the log, not an eighth run


def test_tie_keeps_the_default(plain_setup):
    runs = {key: SensitivityRun(192 * 0.02, 50.0, 0, 0.0) for key in _runs()}
    frame = sensitivity_frame(_meta(), _all_hourly(), {"a": {}}, runs, sensitivity_grid())
    assert frame.loc[frame["is_best_in_hindsight"]].iloc[0]["is_default"]


def test_csv_uses_the_format_of_the_series_file(plain_setup, tmp_path):
    path = tmp_path / "daily.csv"
    write_csv(daily_ladder_frame(_meta(), _all_hourly(), {"a": {}}), str(path))
    back = pd.read_csv(path, sep=";", decimal=",")
    assert back["l3_eur"].iloc[0] == pytest.approx(96 * 0.01)


def test_shared_setup_needs_one_sensitivity_run_per_set(plain_setup):
    meta = _meta()
    meta["ladder_by_scenario"]["b"] = {"l1": "l1:a", "l2": "l2:a"}
    meta["reference_by_scenario"]["b"] = "ref:a"
    meta["ladder_soc_correction"]["b"] = meta["ladder_soc_correction"]["a"]
    meta["heat_fuel"]["b"] = _block()
    hourly = pd.concat([_all_hourly(), _hourly("b", 0.015)])
    runs = {key: SensitivityRun(5.0, 50.0, 0, 0.0) for key in _runs()}
    frame = sensitivity_frame(meta, hourly, {"a": {}, "b": {}}, runs, sensitivity_grid())
    assert len(frame) == 16
    assert len(runs) == 7


def test_real_l2_variants_differ_only_by_their_rule_params(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch):
        scenario = {
            **fixture_scenario_params(),
            **fixture_tariff_params("de_spot_test", "fixed_37ct", timezone_name="Europe/Berlin"),
        }
        prices = build_synthetic_prices_df(pd.Timestamp("2024-07-01"), pd.Timestamp("2026-06-26"))
        cache = load_fixture_cache()
        day = pd.Timestamp(HIGH_EAUTO_DAY)

        def run(rule_params: dict):
            return compute_l2_reference_costs(
                day, day, scenario, prices, cache,
                initial_soc=SE_START_SOC_PERCENT,
                horizon_mode=SUNRISE_WINDOW,
                rule_params=rule_params,
            )

        default = run(DEFAULT_RULE_PARAMS)
        tighter = run({**DEFAULT_RULE_PARAMS, "lock_quantile": 0.50})
        assert list(default.frame.index) == list(tighter.frame.index)
        assert not tighter.plausibility.failed
        # Same energy on every parameter set (spec § 3.1), up to the rows' rounded kW.
        assert tighter.frame["consumption_kw"].sum() == pytest.approx(
            default.frame["consumption_kw"].sum(), rel=1e-3
        )


def test_argv_reaches_the_se_run():
    from scripts.run_reference_ladder import _backtesting_argv, _build_arg_parser

    args = _build_arg_parser().parse_args(
        ["--workers", "4", "--output-dir", "x", "--scenario", "a", "--scenario", "b", "--start-month", "10", "--end-month", "10"]
    )
    assert _backtesting_argv(args, args.output_dir) == [
        "--workers", "4", "--output-dir", "x",
        "--scenario", "a", "--scenario", "b",
        "--start-month", "10", "--end-month", "10",
    ]


def test_scenario_filter_rejects_an_unknown_id():
    from scripts.run_backtesting import _selected_scenarios

    assert _selected_scenarios({"a": {}, "b": {}}, None) == {"a": {}, "b": {}}
    assert _selected_scenarios({"a": {}, "b": {}}, ["b", "b"]) == {"b": {}}
    with pytest.raises(SystemExit, match="Unbekanntes Szenario: c"):
        _selected_scenarios({"a": {}}, ["c"])

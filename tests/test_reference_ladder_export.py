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
from simulation.horizon_mode import SUNRISE_WINDOW
from simulation.reference_ladder import SE_START_SOC_PERCENT, compute_l2_reference_costs
from simulation.reference_ladder_export import (
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
    return pd.DataFrame(
        {
            "ts": pd.date_range("2026-06-10", periods=96 * days, freq="15min"),
            "scenario_id": result_id,
            "sim_cost": cost_per_slot,
        }
    )


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


def test_heating_rod_is_flagged(monkeypatch):
    rod = {"id": "rod", "daily_target_source": "heating_rod"}
    monkeypatch.setattr(
        "simulation.engine_scenario._flexible_consumers_from_scenario", lambda _params: [rod]
    )
    assert has_heating_rod({})


def _runs(**costs: float) -> dict:
    return {
        ("l2:a", rule_key(params)): SensitivityRun(costs.get(f"q{params['lock_quantile']}", 5.0), 50.0, 0)
        for params in sensitivity_grid()[1:]
    }


def test_sensitivity_reports_default_and_best_in_hindsight(plain_setup):
    best_key = (0.5, SURPLUS_BATTERY_FIRST)
    runs = {key: SensitivityRun(9.0, 50.0, 0) for key in _runs()}
    runs[("l2:a", best_key)] = SensitivityRun(1.0, 50.0, 0)
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
    runs = {key: SensitivityRun(9.0, 50.0, 0) for key in _runs()}
    runs[("l2:a", cheap_empty)] = SensitivityRun(1.0, 0.0, 0)
    runs[("l2:a", dearer_full)] = SensitivityRun(1.5, 60.0, 0)
    frame = sensitivity_frame(_meta(), _all_hourly(), {"a": {}}, runs, sensitivity_grid())
    best = frame.loc[frame["is_best_in_hindsight"]].iloc[0]
    assert (best["lock_quantile"], best["surplus_priority"]) == dearer_full


def test_tie_keeps_the_default(plain_setup):
    runs = {key: SensitivityRun(192 * 0.02, 50.0, 0) for key in _runs()}
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
    hourly = pd.concat([_all_hourly(), _hourly("b", 0.015)])
    runs = {key: SensitivityRun(5.0, 50.0, 0) for key in _runs()}
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

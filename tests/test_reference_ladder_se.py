"""RuleRef P3: ladder runs in the SE, L2 as the reference of the saving (spec §§ 2, 5)."""
from __future__ import annotations

import inspect
import os

import pandas as pd
import pytest

from simulation.horizon_mode import SUNRISE_WINDOW
from simulation.reference_costs import (
    is_scenario_reference_id,
    ladder_reference_id,
    scenario_reference_id,
)
from simulation.reference_ladder import (
    SE_START_SOC_PERCENT,
    compute_ladder_reference,
    plan_ladder_reference_tasks,
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

os.environ.setdefault("EARNIE_OFFLINE", "1")


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


def test_identical_setups_share_their_ladder_runs(ladder_env):
    scenario = ladder_env["scenario"]
    ladder, specs = plan_ladder_reference_tasks({"a": scenario, "b": dict(scenario)})
    assert [spec.ref_id for spec in specs] == ["l1:a", "l2:a"]
    assert ladder["b"] == ladder["a"] == {"l1": "l1:a", "l2": "l2:a"}


def test_other_storage_gets_its_own_runs(ladder_env):
    scenario = ladder_env["scenario"]
    ladder, specs = plan_ladder_reference_tasks(
        {"a": scenario, "b": {**scenario, "battery_capacity_kwh": 25.0}}
    )
    assert len(specs) == 4
    assert ladder["b"] == {"l1": "l1:b", "l2": "l2:b"}


def test_other_flex_set_gets_its_own_runs(ladder_env):
    scenario = ladder_env["scenario"]
    extra = {"id": "extra", "name": "Extra", "nominal_power_kw": 1.0, "optimizer_enabled": True}
    ladder, specs = plan_ladder_reference_tasks(
        {"a": scenario, "b": {**scenario, "_planning_flex_consumers": [extra]}}
    )
    assert len(specs) == 4
    assert ladder["a"]["l2"] != ladder["b"]["l2"]


def test_labels_name_the_scenario_and_the_step(ladder_env):
    _, specs = plan_ladder_reference_tasks(
        {"a": ladder_env["scenario"]}, scenario_labels={"a": "Haus A"}
    )
    assert [spec.label for spec in specs] == [
        "Wechselrichter-Eigenverbrauch (Haus A)",
        "Standard-Regeln (Haus A)",
    ]


def test_every_ladder_id_counts_as_a_reference():
    assert is_scenario_reference_id(scenario_reference_id("a"))
    assert is_scenario_reference_id(ladder_reference_id("l1", "a"))
    assert is_scenario_reference_id(ladder_reference_id("l2", "a"))
    assert not is_scenario_reference_id("a")
    assert not is_scenario_reference_id("l1a")
    with pytest.raises(ValueError, match="Referenz-Stufe"):
        ladder_reference_id("l3", "a")


def test_ladder_runs_start_with_the_soc_of_the_optimized_run():
    from simulation.engine import run_simulation

    default = inspect.signature(run_simulation).parameters["initial_soc"].default
    assert SE_START_SOC_PERCENT == default


def test_ladder_gets_cheaper_step_by_step_with_pv_battery_and_ev(ladder_env):
    """Spot tariff, PV, battery, EV; a chain of days on which L1 and L2 end on the same SoC.

    One day alone can end the other way round: L2 then ends with a fuller battery, which
    the cost sum does not value; ``test_reference_ladder_p3b`` covers that with the SoC term.
    """
    import config
    from simulation.engine import compute_historical_reference_costs

    scenario = {
        **ladder_env["scenario"],
        **fixture_tariff_params("de_spot_test", "fixed_37ct", timezone_name="Europe/Berlin"),
    }
    start, end = pd.Timestamp(HIGH_EAUTO_DAY), pd.Timestamp(SOC_CHAIN_END_DAY)
    prices = ladder_env["prices"]
    cache = ladder_env["cache"]
    l0 = compute_historical_reference_costs(
        start,
        end,
        prices,
        config.get_backtesting_feed_in_settings(runtime_override=scenario),
        cache=cache,
        scenario_params=scenario,
        horizon_mode=SUNRISE_WINDOW,
    )
    l1 = compute_ladder_reference("l1", start, end, scenario, prices, cache, horizon_mode=SUNRISE_WINDOW)
    l2 = compute_ladder_reference("l2", start, end, scenario, prices, cache, horizon_mode=SUNRISE_WINDOW)
    assert list(l1.frame.index) == list(l0.index) == list(l2.frame.index)
    assert l1.end_soc == pytest.approx(l2.end_soc)
    assert l0["sim_cost"].sum() > l1.frame["sim_cost"].sum() > l2.frame["sim_cost"].sum()


def test_unknown_step_fails_loud(ladder_env):
    day = pd.Timestamp(HIGH_EAUTO_DAY)
    with pytest.raises(ValueError, match="Referenz-Stufe"):
        compute_ladder_reference(
            "l3",
            day,
            day,
            ladder_env["scenario"],
            ladder_env["prices"],
            ladder_env["cache"],
            horizon_mode=SUNRISE_WINDOW,
        )


def test_ladder_worker_reports_progress_and_quality(ladder_env, tmp_path):
    from scripts.run_backtesting import _run_ladder_worker

    day = pd.Timestamp(HIGH_EAUTO_DAY)
    ref_id, frame, report = _run_ladder_worker(
        "l2:a",
        "l2",
        day.isoformat(),
        day.isoformat(),
        ladder_env["prices"],
        ladder_env["scenario"],
        str(tmp_path / "progress.json"),
        "Standard-Regeln (a)",
        SUNRISE_WINDOW,
    )
    assert ref_id == "l2:a"
    assert not frame.empty
    assert report["plausibility_failed_windows"] == 0
    assert set(report) == {
        "plausibility_failed_windows",
        "no_shape_windows",
        "no_published_block_windows",
        "truncated_lock_slots",
    }


def test_price_load_reaches_the_day_after_the_end():
    from scripts.run_backtesting import _price_load_window

    start, end = pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-30")
    assert _price_load_window(start, end, "perfect") == (start, pd.Timestamp("2026-07-01"))
    load_start, load_end = _price_load_window(start, end, "mirror")
    assert load_start < start
    assert load_end == pd.Timestamp("2026-07-01")


def _meta(ladder: bool = True) -> dict:
    meta = {
        "reference_id": "historical_reference",
        "live_scenario_id": "live",
        "scenario_ids": ["historical_reference", "ref:live", "l1:live", "l2:live", "live"],
        "labels": {},
        "summary": {
            "total_eur": {
                "historical_reference": 2000.0,
                "ref:live": 1500.0,
                "l1:live": 1200.0,
                "l2:live": 1000.0,
                "live": 900.0,
            }
        },
    }
    if ladder:
        meta["ladder_by_scenario"] = {"live": {"l1": "l1:live", "l2": "l2:live"}}
    return meta


def _rows(meta: dict) -> dict[str, dict]:
    from ui.backtesting_results_helpers import build_annual_cost_rows

    return {row["Szenario"]: row for row in build_annual_cost_rows(meta)}


def test_saving_column_is_l2_minus_l3_and_the_old_delta_stays():
    row = _rows(_meta())["live"]
    assert row["Ersparnis vs. Standard-Regeln [€]"] == "+100.00 €"
    assert row["Δ vs Referenz [€]"] == "-600.00 €"


def test_reference_rows_have_no_saving_and_come_before_the_optimized_row():
    meta = _meta()
    rows = _rows(meta)
    assert all(
        rows[rid]["Ersparnis vs. Standard-Regeln [€]"] == "—"
        for rid in ("historical_reference", "ref:live", "l1:live", "l2:live")
    )
    assert list(rows)[-1] == "live"


def test_saving_counts_fuel_on_both_sides():
    meta = _meta()
    meta["heat_fuel"] = {
        "l2:live": {"fuel_eur": 50.0, "co2_kg": 1.0},
        "live": {"fuel_eur": 20.0, "co2_kg": 1.0},
    }
    assert _rows(meta)["live"]["Ersparnis vs. Standard-Regeln [€]"] == "+130.00 €"


def test_log_without_a_ladder_shows_no_saving():
    assert _rows(_meta(ladder=False))["live"]["Ersparnis vs. Standard-Regeln [€]"] == "—"


def test_ladder_report_appears_as_a_hint():
    meta = _meta()
    meta["ladder_report"] = {
        "l2:live": {
            "plausibility_failed_windows": 2,
            "no_shape_windows": {"ev": 3},
            "no_published_block_windows": {},
            "truncated_lock_slots": 8,
        }
    }
    hint = _rows(meta)["l2:live"]["Hinweis"]
    assert "2 Fenster mit abweichender Energie" in hint
    assert "ev: 3 Fenster ohne Lastprofil" in hint
    assert "2 h Preissperre mit kürzerem Horizont" in hint


def test_log_payload_keeps_the_ladder():
    from simulation.backtesting_log import _attach_period_bounds

    payload: dict = {"period": {}}
    period = {
        "ladder_by_scenario": {"live": {"l1": "l1:live", "l2": "l2:live"}},
        "ladder_report": {"l1:live": {}},
        "ladder_soc_correction": {"live": {}},
    }
    _attach_period_bounds(payload, period, [], 1)
    assert payload["ladder_by_scenario"] == period["ladder_by_scenario"]
    assert payload["ladder_report"] == period["ladder_report"]
    assert payload["ladder_soc_correction"] == period["ladder_soc_correction"]

"""RuleRef P1: L1 reference on the windows of the optimized run (spec §§ 3, 4.1)."""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import pytest

from optimizer.sim_baseline import build_shaped_flex_kw_per_slot
from optimizer.slot_duration import DEFAULT_DT_H, energy_kwh_from_kw
from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW
from tests.fixtures.backtesting_fixtures import (
    LOW_EAUTO_DAY,
    SOC_CHAIN_END_DAY,
    SOC_CHAIN_START_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)

os.environ.setdefault("EARNIE_OFFLINE", "1")

EV = {"id": "ev", "name": "EV", "nominal_power_kw": 11.0}


def _kw(result, cid: str) -> list[float]:
    return [slot[cid] for slot in result.per_slot]


def test_shape_is_scaled_to_the_target_and_stays_out_of_ineligible_slots():
    shape = [0.0, 2.0, 4.0, 2.0, 9.0, 0.0]
    result = build_shaped_flex_kw_per_slot(
        6, [EV], {"ev": 4.0}, {"ev": shape}, {"ev": [0, 1, 2, 3]}
    )
    assert _kw(result, "ev") == pytest.approx([0.0, 4.0, 8.0, 4.0, 0.0, 0.0])
    assert energy_kwh_from_kw(_kw(result, "ev")) == pytest.approx(4.0)
    assert result.no_shape_ids == []


def test_no_flat_spreading_without_shape_runs_at_nominal_from_window_start():
    """2 kWh on an 11 kW wallbox: never 0.17 kW over the whole window."""
    result = build_shaped_flex_kw_per_slot(48, [EV], {"ev": 2.0}, {}, {"ev": list(range(4, 48))})
    powers = _kw(result, "ev")
    assert powers[:4] == [0.0] * 4
    assert powers[4] == pytest.approx(8.0)
    assert powers[5:] == [0.0] * 43
    assert energy_kwh_from_kw(powers) == pytest.approx(2.0)
    assert result.no_shape_ids == ["ev"]


def test_zero_shape_inside_the_window_counts_as_no_shape():
    result = build_shaped_flex_kw_per_slot(
        4, [EV], {"ev": 1.0}, {"ev": [5.0, 0.0, 0.0, 0.0]}, {"ev": [1, 2, 3]}
    )
    assert result.no_shape_ids == ["ev"]
    assert energy_kwh_from_kw(_kw(result, "ev")) == pytest.approx(1.0)


def test_cap_moves_excess_to_the_next_slots_and_keeps_the_energy():
    consumer = {"id": "wp", "name": "WP", "nominal_power_kw": 2.0}
    result = build_shaped_flex_kw_per_slot(
        4, [consumer], {"wp": 1.5}, {"wp": [4.0, 1.0, 1.0, 0.0]}, {"wp": [0, 1, 2, 3]}
    )
    powers = _kw(result, "wp")
    assert max(powers) <= 2.0
    assert powers == pytest.approx([2.0, 2.0, 2.0, 0.0])
    assert energy_kwh_from_kw(powers) == pytest.approx(1.5)


def test_excess_at_the_window_end_moves_to_earlier_slots():
    consumer = {"id": "wp", "name": "WP", "nominal_power_kw": 2.0}
    result = build_shaped_flex_kw_per_slot(
        3, [consumer], {"wp": 1.0}, {"wp": [0.0, 0.0, 1.0]}, {"wp": [0, 1, 2]}
    )
    assert _kw(result, "wp") == pytest.approx([0.0, 2.0, 2.0])


def test_infeasible_target_fails_loud_with_the_missing_kwh():
    consumer = {"id": "wp", "name": "WP", "nominal_power_kw": 2.0}
    with pytest.raises(ValueError, match=r"'wp'.*fehlen 1\.000 kWh"):
        build_shaped_flex_kw_per_slot(
            2, [consumer], {"wp": 2.0}, {"wp": [1.0, 1.0]}, {"wp": [0, 1]}
        )


def test_target_without_any_eligible_slot_fails_loud():
    with pytest.raises(ValueError, match=r"'ev'.*fehlen 3\.000 kWh"):
        build_shaped_flex_kw_per_slot(4, [EV], {"ev": 3.0}, {}, {"ev": []})


def test_zero_target_delivers_nothing_and_is_not_a_missing_shape():
    result = build_shaped_flex_kw_per_slot(3, [EV], {"ev": 0.0}, {}, {"ev": [0, 1, 2]})
    assert _kw(result, "ev") == [0.0, 0.0, 0.0]
    assert result.no_shape_ids == []


def test_chart_row_columns_follow_the_given_consumers(monkeypatch):
    from optimizer.sim_baseline import _simulate_single_hour_baseline
    from optimizer.targets import consumer_column_name

    monkeypatch.setattr(
        "optimizer.sim_baseline.config.get_flexible_consumers",
        lambda optimizer_only=False: [{"id": "live_only", "name": "Nur Live"}],
    )
    row = {
        "hour": 12,
        "slot_datetime": datetime(2026, 6, 1, 12),
        "expected_p_pv": 0.0,
        "expected_p_act": 0.5,
        "k_act": 20.0,
    }
    battery = {
        "battery_capacity_kwh": 0.0,
        "efficiency": 1.0,
        "min_soc": 0.0,
        "max_soc": 100.0,
        "max_power_kw": 0.0,
    }
    _, chart_row = _simulate_single_hour_baseline(
        row, 50.0, battery, flex_kw_override={"ev": 3.0}, consumers=[EV]
    )
    assert chart_row[consumer_column_name(EV)] == 3.0
    assert not any("Nur Live" in key for key in chart_row)


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


def _run_l1(env, start, end, *, scenario=None, horizon_mode=SUNRISE_WINDOW, initial_soc=50.0):
    from simulation.reference_ladder import compute_l1_reference_costs

    return compute_l1_reference_costs(
        pd.Timestamp(start),
        pd.Timestamp(end),
        scenario if scenario is not None else env["scenario"],
        env["prices"],
        env["cache"],
        initial_soc=initial_soc,
        horizon_mode=horizon_mode,
    )


def _no_battery(scenario: dict) -> dict:
    return {**scenario, "battery_capacity_kwh": 0.0}


def test_energy_parity_per_window_passes_the_plausibility_check(ladder_env):
    result = _run_l1(ladder_env, SOC_CHAIN_START_DAY, SOC_CHAIN_END_DAY)
    assert result.plausibility.results
    assert result.plausibility.failed == []
    assert result.frame["sim_cost"].notna().all()


def test_l1_books_the_slots_of_the_optimized_run(ladder_env):
    from simulation.engine import run_simulation

    day = pd.Timestamp(LOW_EAUTO_DAY)
    optimized, _, _ = run_simulation(
        day, day, ladder_env["scenario"], ladder_env["prices"], cache=ladder_env["cache"]
    )
    result = _run_l1(ladder_env, LOW_EAUTO_DAY, LOW_EAUTO_DAY)
    assert list(result.frame.index) == list(optimized.index)
    assert result.frame["k_act"].tolist() == pytest.approx(optimized["k_act"].tolist())


def test_soc_never_resets_between_anchors(ladder_env):
    """Book k starts with the SoC book k-1 ended on, whatever the start SoC of the run."""
    result = _run_l1(ladder_env, SOC_CHAIN_START_DAY, SOC_CHAIN_END_DAY, initial_soc=37.0)
    frame = result.frame
    assert frame["sim_soc"].iloc[0] == pytest.approx(37.0)
    dt_h = float(DEFAULT_DT_H)
    capacity = float(ladder_env["scenario"]["battery_capacity_kwh"])
    # Largest SoC step of one slot at full power: any reset at a window edge would exceed it.
    max_step = float(ladder_env["scenario"]["battery_max_power_kw"]) * dt_h / capacity * 100.0
    assert frame["sim_soc"].diff().abs().max() <= max_step + 1e-6


def test_battery_changes_the_result_and_saves_money(ladder_env):
    with_battery = _run_l1(ladder_env, SOC_CHAIN_START_DAY, SOC_CHAIN_END_DAY)
    without = _run_l1(
        ladder_env,
        SOC_CHAIN_START_DAY,
        SOC_CHAIN_END_DAY,
        scenario=_no_battery(ladder_env["scenario"]),
    )
    assert without.frame["sim_soc"].nunique() == 1
    assert with_battery.frame["sim_soc"].nunique() > 1
    assert with_battery.frame["import_kwh"].sum() < without.frame["import_kwh"].sum()


def test_l1_without_battery_equals_l0_slot_for_slot(ladder_env, monkeypatch):
    """Nominal power lifted: the logged flex exceeds it, and L1 would move that excess."""
    import config
    from simulation import engine_scenario
    from simulation.engine import compute_historical_reference_costs

    original = engine_scenario._flexible_consumers_from_scenario
    monkeypatch.setattr(
        engine_scenario,
        "_flexible_consumers_from_scenario",
        lambda params: [{**c, "nominal_power_kw": 50.0} for c in original(params)],
    )
    scenario = _no_battery(ladder_env["scenario"])
    day = pd.Timestamp(LOW_EAUTO_DAY)
    l0 = compute_historical_reference_costs(
        day,
        day,
        ladder_env["prices"],
        config.get_backtesting_feed_in_settings(runtime_override=scenario),
        cache=ladder_env["cache"],
        scenario_params=scenario,
        horizon_mode=SUNRISE_WINDOW,
    )
    l1 = _run_l1(ladder_env, LOW_EAUTO_DAY, LOW_EAUTO_DAY, scenario=scenario)
    assert list(l1.frame.index) == list(l0.index)
    for column in ("consumption_kw", "import_kwh", "export_kwh", "sim_cost"):
        assert l1.frame[column].to_numpy() == pytest.approx(
            l0[column].to_numpy(), abs=0.02 if column == "consumption_kw" else 0.005
        ), column


def test_fixed_24h_mode_is_supported(ladder_env):
    result = _run_l1(ladder_env, LOW_EAUTO_DAY, LOW_EAUTO_DAY, horizon_mode=FIXED_24H)
    assert len(result.frame) == 96
    assert result.plausibility.failed == []


def test_scenario_consumers_are_used_not_the_live_ones(ladder_env, monkeypatch):
    """The run plans its own consumers, even when Live has others."""
    from optimizer import sim_baseline
    from simulation import engine_scenario, reference_ladder

    scenario_consumer = {
        "id": "nur_szenario",
        "name": "Nur Szenario",
        "nominal_power_kw": 3.0,
        "optimizer_enabled": True,
    }
    monkeypatch.setattr(
        engine_scenario,
        "_flexible_consumers_from_scenario",
        lambda params: [scenario_consumer],
    )
    seen: list[list[str]] = []
    original = sim_baseline.build_shaped_flex_kw_per_slot

    def spy(slot_count, consumers, targets, shapes, eligible):
        seen.append([c["id"] for c in consumers])
        return original(slot_count, consumers, targets, shapes, eligible)

    monkeypatch.setattr(reference_ladder, "build_shaped_flex_kw_per_slot", spy)
    _run_l1(ladder_env, LOW_EAUTO_DAY, LOW_EAUTO_DAY)
    assert seen and all(ids == ["nur_szenario"] for ids in seen)


def test_heating_rod_stays_at_zero(ladder_env, monkeypatch):
    from simulation import engine_scenario, reference_ladder

    rod = {
        "id": "stab",
        "name": "Heizstab",
        "nominal_power_kw": 3.0,
        "optimizer_enabled": True,
        "daily_target_source": "heating_rod",
        "parent_heat_electric": True,
        "parent_heat_efficiency": 3.0,
    }
    real = engine_scenario._flexible_consumers_from_scenario(ladder_env["scenario"])
    monkeypatch.setattr(
        engine_scenario,
        "_flexible_consumers_from_scenario",
        lambda params: [*real, rod],
    )
    planned_ids: list[list[str]] = []
    original = reference_ladder.build_shaped_flex_kw_per_slot

    def spy(slot_count, consumers, targets, shapes, eligible):
        planned_ids.append([c["id"] for c in consumers])
        return original(slot_count, consumers, targets, shapes, eligible)

    monkeypatch.setattr(reference_ladder, "build_shaped_flex_kw_per_slot", spy)
    result = _run_l1(ladder_env, LOW_EAUTO_DAY, LOW_EAUTO_DAY)
    assert planned_ids and all("stab" not in ids for ids in planned_ids)
    assert result.frame["sim_cost"].notna().all()


def test_fingerprint_separates_battery_and_flex_but_not_identical_setups(ladder_env):
    from simulation.reference_ladder import ladder_reference_fingerprint

    scenario = ladder_env["scenario"]
    assert ladder_reference_fingerprint(scenario) == ladder_reference_fingerprint(dict(scenario))
    assert ladder_reference_fingerprint(scenario) != ladder_reference_fingerprint(
        {**scenario, "battery_capacity_kwh": 10.0}
    )
    assert ladder_reference_fingerprint(scenario) != ladder_reference_fingerprint(
        {
            **scenario,
            "_planning_flex_consumers": [
                {
                    "id": "extra",
                    "name": "Extra",
                    "nominal_power_kw": 1.0,
                    "optimizer_enabled": True,
                }
            ],
        }
    )


def test_l0_sharing_key_is_unchanged_by_the_battery(ladder_env):
    from house_config.planning_flex_bridge import reference_fingerprint

    scenario = ladder_env["scenario"]
    assert reference_fingerprint(scenario) == reference_fingerprint(
        {**scenario, "battery_capacity_kwh": 10.0}
    )

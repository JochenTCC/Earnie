"""SE reference boxes: what a run plans for each choice, and which series share their flows."""
from __future__ import annotations

import os

import pytest

from simulation.reference_costs import HISTORICAL_REFERENCE_ID
from simulation.reference_selection import (
    effective_references,
    format_references,
    parse_references,
    plan_references,
)
from tests.fixtures.backtesting_fixtures import (
    activate_backtesting_fixtures,
    fixture_scenario_params,
    fixture_tariff_params,
)

os.environ.setdefault("EARNIE_OFFLINE", "1")


def test_parse_and_format_round_trip():
    assert parse_references("l1,historical") == ("historical", "l1")
    assert parse_references("none") == ()
    assert format_references(()) == "none"
    assert format_references(["l0", "historical"]) == "historical,l0"


@pytest.mark.parametrize("text", ["", "l2", "historical,foo"])
def test_parse_fails_loud_on_unknown_or_empty(text):
    with pytest.raises(ValueError):
        parse_references(text)


def test_rule_reference_adds_l0_and_l1():
    assert effective_references((), rule_reference=True) == ("l0", "l1")
    assert effective_references(("historical",), rule_reference=False) == ("historical",)


@pytest.fixture
def scenarios(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch):
        live = fixture_scenario_params()
        yield {
            "live": live,
            # Same house, PV and battery as Live, other tariff: shares Live's flows.
            "dyn": {**live, **fixture_tariff_params("awattar_at", "fixed_37ct")},
            "big_pv": {**live, "pv_kwp": 12.0},
        }


def _plan(scenarios, references, *, rule_reference=False):
    from house_config.entity_resolution import strip_assets_for_reference

    return plan_references(
        scenarios,
        scenarios,
        live_scenario_id="live",
        references=references,
        rule_reference=rule_reference,
        historical_params=strip_assets_for_reference(scenarios["live"]),
        historical_label="Historisch",
    )


def test_no_box_runs_only_the_scenarios(scenarios):
    plan = _plan(scenarios, ())
    assert plan.references == ()
    assert plan.l0_specs == [] and plan.ladder_specs == []
    assert plan.reference_by_scenario == {} and plan.l1_by_scenario == {}
    assert plan.parallel_task_count(3) == 3


def test_historical_alone_is_one_series(scenarios):
    plan = _plan(scenarios, ("historical",))
    assert [spec[0] for spec in plan.l0_specs] == [HISTORICAL_REFERENCE_ID]
    assert plan.reference_by_scenario == {}


def test_l0_per_scenario_books_other_tariffs_from_shared_flows(scenarios):
    plan = _plan(scenarios, ("l0",))
    assert plan.reference_by_scenario == {"live": "ref:live", "dyn": "ref:dyn", "big_pv": "ref:big_pv"}
    assert not plan.runs_historical
    assert plan.l0_sharing.computed == ["ref:live", "ref:big_pv"]
    assert plan.l0_sharing.rebooked == {"ref:dyn": "ref:live"}
    assert plan.parallel_task_count(3) == 5


def test_l0_of_a_scenario_without_pv_on_lives_tariff_is_historical(scenarios):
    from house_config.entity_resolution import strip_assets_for_reference

    scenarios = {**scenarios, "bare": strip_assets_for_reference(scenarios["live"])}
    plan = _plan(scenarios, ("l0",))
    assert plan.reference_by_scenario["bare"] == HISTORICAL_REFERENCE_ID
    assert plan.runs_historical


def test_l1_box_plans_l1_only_and_shares_across_tariffs(scenarios):
    plan = _plan(scenarios, ("l1",))
    assert plan.l1_by_scenario == {"live": "l1:live", "dyn": "l1:dyn", "big_pv": "l1:big_pv"}
    assert plan.ladder_by_scenario == {}
    assert [spec.step for spec in plan.ladder_specs] == ["l1", "l1", "l1"]
    assert plan.l1_sharing.rebooked == {"l1:dyn": "l1:live"}
    assert [spec.ref_id for spec in plan.computed_ladder_specs] == ["l1:live", "l1:big_pv"]


def test_rule_reference_runs_l2_per_tariff_with_l0_and_l1(scenarios):
    plan = _plan(scenarios, (), rule_reference=True)
    assert plan.references == ("l0", "l1")
    assert plan.ladder_by_scenario["dyn"] == {"l1": "l1:dyn", "l2": "l2:dyn"}
    computed = [spec.ref_id for spec in plan.computed_ladder_specs]
    # L2 curtails and locks on price: never shared across tariffs.
    assert {"l2:live", "l2:dyn", "l2:big_pv"} <= set(computed)
    assert "l1:dyn" not in computed

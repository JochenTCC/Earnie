"""SE references: flows computed once per physical setup, booked per tariff."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from simulation.horizon_mode import SUNRISE_WINDOW
from simulation.reference_dedup import (
    physical_setup_key,
    rebook_reference_frame,
    share_by_physical_setup,
)
from tests.fixtures.backtesting_fixtures import (
    SOC_CHAIN_END_DAY,
    SOC_CHAIN_START_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    fixture_tariff_params,
    load_fixture_cache,
)

os.environ.setdefault("EARNIE_OFFLINE", "1")

_COST_COLUMNS = ("k_act", "k_push_act", "import_cost_eur", "export_earn_eur", "sim_cost")
_FLOW_COLUMNS = ("consumption_kw", "import_kwh", "export_kwh")


@pytest.fixture
def env(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch):
        scenario = fixture_scenario_params()
        yield {
            "cache": load_fixture_cache(),
            "scenario": scenario,
            # Dynamic import tariff: prices differ slot by slot from the fixed one.
            "other_tariff": {**scenario, **fixture_tariff_params("awattar_at", "fixed_37ct")},
            "prices": build_synthetic_prices_df(
                pd.Timestamp("2024-07-01"), pd.Timestamp("2026-06-26")
            ),
        }


def test_tariff_is_not_part_of_the_physical_setup(env):
    assert physical_setup_key(env["scenario"]) == physical_setup_key(env["other_tariff"])
    assert physical_setup_key({**env["scenario"], "pv_kwp": 9.0}) != physical_setup_key(
        env["scenario"]
    )
    assert physical_setup_key(None) is None


def test_first_of_a_setup_is_computed_the_others_rebooked(env):
    other_pv = {**env["scenario"], "pv_kwp": 9.0}
    plan = share_by_physical_setup(
        [
            ("ref:a", env["scenario"]),
            ("ref:b", env["other_tariff"]),
            ("ref:c", other_pv),
            ("historical_reference", None),
            ("ref:d", None),
        ]
    )
    assert plan.computed == ["ref:a", "ref:c", "historical_reference", "ref:d"]
    assert plan.rebooked == {"ref:b": "ref:a"}


def _assert_same_booking(rebooked: pd.DataFrame, direct: pd.DataFrame) -> None:
    assert list(rebooked.index) == list(direct.index)
    for column in (*_FLOW_COLUMNS, *_COST_COLUMNS):
        assert rebooked[column].to_numpy() == pytest.approx(
            direct[column].to_numpy(), abs=1e-9
        ), column


def test_l0_on_another_tariff_equals_its_own_run(env):
    import config
    from simulation.engine import compute_historical_reference_costs

    def l0(params):
        return compute_historical_reference_costs(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
            env["prices"],
            config.get_backtesting_feed_in_settings(runtime_override=params),
            cache=env["cache"],
            scenario_params=params,
            horizon_mode=SUNRISE_WINDOW,
        )

    own = l0(env["scenario"])
    direct = l0(env["other_tariff"])
    assert direct["sim_cost"].sum() != pytest.approx(own["sim_cost"].sum())
    _assert_same_booking(rebook_reference_frame(own, env["prices"], env["other_tariff"]), direct)


def test_l1_on_another_tariff_equals_its_own_run(env):
    from simulation.reference_ladder import compute_l1_reference_costs

    def l1(params):
        return compute_l1_reference_costs(
            pd.Timestamp(SOC_CHAIN_START_DAY),
            pd.Timestamp(SOC_CHAIN_END_DAY),
            params,
            env["prices"],
            env["cache"],
            initial_soc=50.0,
            horizon_mode=SUNRISE_WINDOW,
        ).frame

    own = l1(env["scenario"])
    direct = l1(env["other_tariff"])
    assert direct["sim_cost"].sum() != pytest.approx(own["sim_cost"].sum())
    rebooked = rebook_reference_frame(own, env["prices"], env["other_tariff"])
    _assert_same_booking(rebooked, direct)
    assert rebooked["sim_soc"].tolist() == direct["sim_soc"].tolist()
    assert rebooked.attrs == direct.attrs

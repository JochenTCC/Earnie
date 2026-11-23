"""``run_simulation`` hands the solver overrides back, also when the run stops at the start.

Found in the KPI split review (2026-11-23): an invalid import cap raised after the overrides were
set and before the ``try`` of the run, so the CBC / solver ContextVars stayed changed for the
rest of the process (the next run, a test, the UI worker thread).
"""
from __future__ import annotations

import pandas as pd
import pytest

from optimizer import cbc_solver
from simulation import engine
from tests.fixtures.backtesting_fixtures import (
    HIGH_EAUTO_DAY,
    SOC_CHAIN_END_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)


def _overrides() -> tuple:
    return (
        cbc_solver._cbc_gap_rel_override.get(),
        cbc_solver._cbc_strict_time_limit_override.get(),
        cbc_solver._milp_solver_override.get(),
    )


@pytest.mark.parametrize(
    "cap",
    [
        {"import_cap_kw": 3.0},  # half set
        {"import_cap_kw": 3.0, "import_cap_margin_kw": 3.0},  # margin not below the cap
        {"import_cap_kw": 0.0, "import_cap_margin_kw": 0.0},  # cap must be > 0
    ],
)
def test_an_invalid_import_cap_leaves_the_solver_overrides_as_they_were(monkeypatch, cap):
    # Values that differ from the idle state, so a leak is visible whatever the config says.
    monkeypatch.setattr(engine.config, "get_backtesting_cbc_gap_rel", lambda: 0.123)
    monkeypatch.setattr(engine.config, "get_backtesting_cbc_strict_time_limit_sec", lambda: 77.0)
    monkeypatch.setattr(engine.config, "get_backtesting_milp_solver", lambda: "cbc")
    before = _overrides()
    with activate_backtesting_fixtures(monkeypatch):
        with pytest.raises(ValueError):
            engine.run_simulation(
                pd.Timestamp(HIGH_EAUTO_DAY),
                pd.Timestamp(SOC_CHAIN_END_DAY),
                {**fixture_scenario_params(), **cap},
                build_synthetic_prices_df(pd.Timestamp("2024-07-01"), pd.Timestamp("2026-06-26")),
                cache=load_fixture_cache(),
            )
    assert _overrides() == before

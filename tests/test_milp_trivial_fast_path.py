"""2.3.c.1 — trivial MILP fast path (no battery + no remaining flex)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from optimizer.milp import (
    ENV_MILP_TRIVIAL_FAST_PATH,
    EMPTY_MILP_PLAN,
    is_trivial_milp_window,
    milp_horizon_schedule,
    milp_optimizer,
    milp_trivial_fast_path_enabled,
)
from optimizer.simulation import calculate_cost_euro_from_rows, simulate_horizon

_ZERO_BATTERY = {
    "battery_capacity_kwh": 0.0,
    "max_power_kw": 0.0,
    "min_soc": 0.0,
    "max_soc": 100.0,
    "efficiency": 1.0,
}

_BATTERY = {
    "battery_capacity_kwh": 10.0,
    "max_power_kw": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "efficiency": 0.95,
}


def _matrix_row(hour: int, day: datetime, *, price: float = 20.0) -> dict:
    slot = day.replace(hour=hour, minute=0, second=0, microsecond=0)
    return {
        "hour": hour,
        "date": day.date(),
        "slot_datetime": slot,
        "expected_p_pv": 0.5 if 10 <= hour <= 16 else 0.0,
        "expected_p_act": 1.0,
        "k_act": price,
        "k_push_act": 5.0,
    }


def _small_matrix(n: int = 4) -> list[dict]:
    day = datetime(2025, 6, 1)
    return [_matrix_row(h, day, price=15.0 + h) for h in range(n)]


@pytest.fixture(autouse=True)
def _clear_trivial_env(monkeypatch):
    monkeypatch.delenv(ENV_MILP_TRIVIAL_FAST_PATH, raising=False)


def test_predicate_requires_zero_capacity_and_zero_remaining():
    assert is_trivial_milp_window(_ZERO_BATTERY, {})
    assert is_trivial_milp_window(_ZERO_BATTERY, {"a": 0.0})
    assert not is_trivial_milp_window(_ZERO_BATTERY, {"a": 0.1})
    assert not is_trivial_milp_window(_BATTERY, {})
    assert not is_trivial_milp_window(_BATTERY, {"a": 0.0})


def test_env_gate_defaults_on(monkeypatch):
    assert milp_trivial_fast_path_enabled() is True
    monkeypatch.setenv(ENV_MILP_TRIVIAL_FAST_PATH, "0")
    assert milp_trivial_fast_path_enabled() is False
    monkeypatch.setenv(ENV_MILP_TRIVIAL_FAST_PATH, "1")
    assert milp_trivial_fast_path_enabled() is True


def test_trivial_horizon_skips_solver():
    matrix = _small_matrix(3)
    with patch("optimizer.milp._solve_milp_to_model") as mock_solve:
        schedule = milp_horizon_schedule(
            matrix,
            current_soc=50.0,
            battery_params=_ZERO_BATTERY,
            k_push=5.0,
            verbose=False,
            consumers=[],
            consumer_remaining_kwh={},
        )
    assert mock_solve.call_count == 0
    assert len(schedule) == len(matrix)
    assert schedule[0]["milp_plan"] == EMPTY_MILP_PLAN
    assert schedule[0]["consumer_powers"] == {}


def test_trivial_optimizer_skips_solver():
    matrix = _small_matrix(2)
    with patch("optimizer.milp._solve_milp_to_model") as mock_solve:
        mode, target_power, target_soc, powers, _, plan, _ = milp_optimizer(
            matrix,
            current_hour=0,
            current_soc=50.0,
            battery_params=_ZERO_BATTERY,
            k_push=5.0,
            verbose=False,
            consumers=[],
            consumer_remaining_kwh={},
        )
    assert mock_solve.call_count == 0
    assert mode == 0
    assert target_power == 0.0
    assert target_soc == pytest.approx(50.0)
    assert powers == {}
    assert plan == EMPTY_MILP_PLAN


def test_nontrivial_capacity_still_solves():
    matrix = _small_matrix(2)
    with patch(
        "optimizer.milp._solve_milp_to_model",
        return_value=None,
    ) as mock_solve:
        milp_horizon_schedule(
            matrix,
            current_soc=50.0,
            battery_params=_BATTERY,
            k_push=5.0,
            verbose=False,
            consumers=[],
            consumer_remaining_kwh={},
        )
    assert mock_solve.call_count == 1


def test_nontrivial_remaining_flex_still_solves():
    matrix = _small_matrix(2)
    consumer = {
        "id": "flex_a",
        "daily_target_kwh": 2.0,
        "power_kw": 1.0,
    }
    with patch(
        "optimizer.milp._solve_milp_to_model",
        return_value=None,
    ) as mock_solve:
        milp_horizon_schedule(
            matrix,
            current_soc=50.0,
            battery_params=_ZERO_BATTERY,
            k_push=5.0,
            verbose=False,
            consumers=[consumer],
            consumer_remaining_kwh={"flex_a": 1.5},
        )
    assert mock_solve.call_count == 1


def test_env_zero_disables_skip_even_when_trivial(monkeypatch):
    monkeypatch.setenv(ENV_MILP_TRIVIAL_FAST_PATH, "0")
    matrix = _small_matrix(2)
    with patch(
        "optimizer.milp._solve_milp_to_model",
        return_value=None,
    ) as mock_solve:
        milp_horizon_schedule(
            matrix,
            current_soc=50.0,
            battery_params=_ZERO_BATTERY,
            k_push=5.0,
            verbose=False,
            consumers=[],
            consumer_remaining_kwh={},
        )
    assert mock_solve.call_count == 1


def test_euro_parity_fast_path_on_vs_off(monkeypatch):
    matrix = _small_matrix(4)

    def _run() -> float:
        rows = simulate_horizon(
            matrix,
            50.0,
            battery_params=_ZERO_BATTERY,
            verbose=False,
            flexible_consumers=[],
            commit_hours=len(matrix),
        )
        return calculate_cost_euro_from_rows(rows)

    monkeypatch.setenv(ENV_MILP_TRIVIAL_FAST_PATH, "0")
    cost_off = _run()
    monkeypatch.setenv(ENV_MILP_TRIVIAL_FAST_PATH, "1")
    cost_on = _run()
    assert cost_on == pytest.approx(cost_off, abs=1e-6)


def test_reference_costs_never_call_milp_solver(monkeypatch):
    import config
    from simulation.engine import compute_historical_reference_costs
    from tests.fixtures.backtesting_fixtures import (
        LOW_EAUTO_DAY,
        activate_backtesting_fixtures,
        build_synthetic_prices_df,
        fixture_scenario_params,
        load_fixture_cache,
    )

    with activate_backtesting_fixtures(monkeypatch):
        cache = load_fixture_cache()
        scenario = fixture_scenario_params()
        prices_df = build_synthetic_prices_df(
            pd.Timestamp("2024-07-01"),
            pd.Timestamp("2026-06-26"),
            base_cent=10.0,
            peak_cent=35.0,
        )
        day = pd.Timestamp(LOW_EAUTO_DAY)
        ref_settings = config.get_backtesting_feed_in_settings(
            runtime_override=scenario
        )

        def _boom(*_a, **_k):
            raise AssertionError("reference path must not call MILP solver")

        with patch(
            "optimizer.cbc_solver.solve_with_strict_fallback",
            side_effect=_boom,
        ):
            with patch(
                "optimizer.milp._solve_milp_to_model",
                side_effect=_boom,
            ):
                df = compute_historical_reference_costs(
                    day,
                    day,
                    prices_df,
                    ref_settings,
                    cache=cache,
                )
        assert len(df) == 24
        assert df["sim_cost"].notna().all()

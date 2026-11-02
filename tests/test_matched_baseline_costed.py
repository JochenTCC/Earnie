"""Ledger P2: BL Ziel € without the profile-fallback energy (savings-ledger D3)."""

from __future__ import annotations

import pytest

from optimizer import sim_costs
from optimizer.simulation import (
    calculate_cost_euro_from_rows,
    delivered_flex_kwh_from_rows,
    hourly_cost_euro_from_rows,
    simulate_baseline_horizon,
    total_consumption_kwh_from_rows,
)
from optimizer.targets import build_energy_comparison_detail


def _matrix() -> list[dict]:
    return [
        {
            "hour": h,
            "expected_p_pv": 0.2,
            "expected_p_act": 0.5,
            "k_act": 30.0,
            "k_push_act": 8.0,
            "expected_flex_kw": {
                "swimspa": 0.5,
                "waschmaschine": 2.0 if h < 2 else 0.0,
            },
        }
        for h in range(24)
    ]


CONSUMERS = [
    {"id": "swimspa", "name": "Swimspa", "daily_target_source": "config", "daily_target_kwh": 4.0},
    {"id": "waschmaschine", "name": "Waschmaschine", "daily_target_source": "config", "daily_target_kwh": 0.0},
]


@pytest.fixture(autouse=True)
def _consumers(monkeypatch):
    monkeypatch.setattr(
        "config.get_flexible_consumers", lambda *_a, **_k: [dict(c) for c in CONSUMERS]
    )


def _patch_targets(monkeypatch, matched: dict, costed: dict) -> None:
    monkeypatch.setattr(
        "optimizer.simulation.simulate_horizon",
        lambda matrix, initial_soc, **_: simulate_baseline_horizon(matrix, initial_soc),
    )
    monkeypatch.setattr(
        "optimizer.targets.resolve_matched_baseline_horizon_targets",
        lambda *_args, **_kw: dict(matched),
    )
    monkeypatch.setattr(
        "optimizer.targets.resolve_horizon_consumer_targets_kwh",
        lambda *_args, **_kw: dict(costed),
    )


def _run(matrix: list[dict]):
    return sim_costs._run_savings_horizons(
        matrix,
        60.0,
        None,
        None,
        None,
        sunrise_soc_min_index=None,
        consumers=None,
    )


def test_fallback_energy_stays_in_soc_run_but_not_in_costed_run(monkeypatch):
    _patch_targets(
        monkeypatch,
        matched={"swimspa": 4.0, "waschmaschine": 4.0},
        costed={"swimspa": 4.0, "waschmaschine": 0.0},
    )

    rows = _run(_matrix())

    assert rows.profile_fallback_kwh == {"waschmaschine": 4.0}
    soc_flex = delivered_flex_kwh_from_rows(rows.matched_baseline)
    costed_flex = delivered_flex_kwh_from_rows(rows.matched_baseline_costed)
    assert soc_flex["waschmaschine"] == pytest.approx(4.0, abs=0.05)
    assert costed_flex.get("waschmaschine", 0.0) == pytest.approx(0.0, abs=1e-6)
    assert costed_flex["swimspa"] == pytest.approx(soc_flex["swimspa"], abs=0.05)
    # the fallback still drains the BL Ziel battery shown in Chart 1
    soc = [row["Simulierter SoC (%)"] for row in rows.matched_baseline]
    costed_soc = [row["Simulierter SoC (%)"] for row in rows.matched_baseline_costed]
    assert all(a <= b + 1e-9 for a, b in zip(soc, costed_soc))
    assert any(a < b for a, b in zip(soc, costed_soc))


def test_bl_ziel_cost_and_kwh_come_from_the_costed_run(monkeypatch):
    _patch_targets(
        monkeypatch,
        matched={"swimspa": 4.0, "waschmaschine": 4.0},
        costed={"swimspa": 4.0, "waschmaschine": 0.0},
    )
    rows = _run(_matrix())

    costs = sim_costs._savings_cost_block(rows)
    hourly = sim_costs._savings_hourly_block(rows, rows.optimized)

    costed_cost = calculate_cost_euro_from_rows(rows.matched_baseline_costed, None)
    soc_cost = calculate_cost_euro_from_rows(rows.matched_baseline, None)
    assert soc_cost > costed_cost
    assert costs["matched_baseline_cost_euro"] == pytest.approx(costed_cost, abs=1e-3)
    assert costs["matched_baseline_consumption_kwh"] == pytest.approx(
        total_consumption_kwh_from_rows(rows.matched_baseline_costed), abs=1e-3
    )
    assert hourly["hourly_matched_baseline_cost_euro"] == pytest.approx(
        hourly_cost_euro_from_rows(rows.matched_baseline_costed, None)
    )
    assert sum(hourly["hourly_savings_euro"]) == pytest.approx(
        costs["matched_baseline_cost_euro"] - costs["optimized_cost_euro"], abs=1e-3
    )


def test_without_fallback_the_matched_run_is_reused(monkeypatch):
    targets = {"swimspa": 4.0, "waschmaschine": 2.0}
    _patch_targets(monkeypatch, matched=targets, costed=targets)

    rows = _run(_matrix())

    assert rows.profile_fallback_kwh == {}
    assert rows.matched_baseline_costed is rows.matched_baseline


def test_energy_comparison_lists_the_fallback_energy(monkeypatch):
    consumers = [CONSUMERS[1]]
    monkeypatch.setattr(
        "optimizer.targets.build_baseline_targets_detail",
        lambda *_a, **_k: [{"id": "waschmaschine", "target_kwh": 4.0}],
    )
    monkeypatch.setattr(
        "optimizer.targets.build_applied_targets_detail",
        lambda *_a, **_k: [{"id": "waschmaschine", "target_kwh": 0.0, "source": "config.json"}],
    )
    monkeypatch.setattr("optimizer.targets.resolve_baseload_kwh", lambda *_a: 10.0)

    rows = build_energy_comparison_detail(
        _matrix(),
        None,
        matched_flex_kwh={"waschmaschine": 4.0},
        profile_fallback_kwh={"waschmaschine": 4.0},
        consumers=consumers,
    )

    assert rows[0]["profile_fallback_kwh"] == 0.0
    assert rows[1]["profile_fallback_kwh"] == pytest.approx(4.0)
    assert rows[1]["optimization_kwh"] == 0.0

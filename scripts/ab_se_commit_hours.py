#!/usr/bin/env python3
"""A/B: SE commit_hours=1 (hourly MPC) vs open-loop (commit_hours=len(matrix)).

Uses offline backtesting fixtures (tests/fixtures/backtesting). Reports wall time,
€ cost, end SoC, and flex delivery for fixed_24h and sunrise_window on a few days.

Example:
  python -m scripts.ab_se_commit_hours
  python -m scripts.ab_se_commit_hours --days 2026-06-23,2026-06-25
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _activate_fixtures() -> None:
    import config as config_module
    from data import open_meteo_solar_archive as archive
    from tests.fixtures.backtesting_fixtures import fixture_path
    from tests.fixtures.open_meteo_mock import _fake_fetch_hourly_archive_chunk

    os.environ["ENERGY_OPTIMIZER_CONFIG_PATH"] = str(fixture_path("config.json"))
    os.environ["ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH"] = str(
        fixture_path("backtesting_scenarios.json")
    )
    os.environ["ENERGY_OPTIMIZER_TARIFFS_PATH"] = str(fixture_path("tariffs.json"))
    os.environ["ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH"] = str(
        fixture_path("house_profiles.json")
    )
    os.environ["ENERGY_OPTIMIZER_OFFLINE"] = "1"
    config_module.reinit_config()
    archive._fetch_hourly_archive_chunk = _fake_fetch_hourly_archive_chunk  # type: ignore[method-assign]


def _parse_days(raw: str) -> list[date]:
    days: list[date] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        days.append(date.fromisoformat(part))
    return days


def _run_window(
    *,
    day: date,
    horizon_mode: str,
    commit_hours_mode: str,
    cache,
    prices_df: pd.DataFrame,
    scenario: dict,
    battery: dict,
) -> dict:
    import config
    from optimizer.simulation import (
        calculate_cost_euro_from_rows,
        delivered_flex_kwh_from_rows,
        horizon_end_soc_from_chart_rows,
        simulate_horizon,
    )
    from simulation.backtesting_horizon import truncate_matrix_for_step_simulation
    from simulation.engine import (
        _flexible_consumers_from_scenario,
        build_historical_window_matrix,
        build_sunrise_window_matrix,
        window_anchor_for_date,
    )
    from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW

    anchor = window_anchor_for_date(day)
    feed_in = config.get_backtesting_feed_in_settings(runtime_override=scenario)
    sunrise_idx = None
    if horizon_mode == SUNRISE_WINDOW:
        matrix, meta, sunrise_idx, _ = build_sunrise_window_matrix(
            anchor,
            cache,
            prices_df,
            scenario,
            feed_in,
        )
        matrix = truncate_matrix_for_step_simulation(matrix, sunrise_idx or 0)
    else:
        matrix, meta = build_historical_window_matrix(
            anchor,
            cache,
            prices_df,
            feed_in_settings=feed_in,
            scenario_params=scenario,
        )
        horizon_mode = FIXED_24H

    commit_hours = 1 if commit_hours_mode == "k1" else len(matrix)
    flex_consumers = _flexible_consumers_from_scenario(scenario)
    t0 = time.perf_counter()
    rows = simulate_horizon(
        matrix,
        50.0,
        battery_params=battery,
        verbose=False,
        consumer_daily_targets_kwh=meta["consumer_daily_targets_kwh"],
        sunrise_soc_min_index=sunrise_idx,
        flexible_consumers=flex_consumers,
        commit_hours=commit_hours,
    )
    elapsed = time.perf_counter() - t0
    end_soc = horizon_end_soc_from_chart_rows(rows)
    flex = delivered_flex_kwh_from_rows(rows, flexible_consumers=flex_consumers)
    return {
        "day": day.isoformat(),
        "horizon_mode": horizon_mode,
        "commit_hours": commit_hours,
        "wall_s": round(elapsed, 3),
        "cost_euro": round(calculate_cost_euro_from_rows(rows), 4),
        "end_soc": None if end_soc is None else round(float(end_soc), 2),
        "flex_kwh": {cid: round(v, 3) for cid, v in flex.items()},
        "hours": len(rows),
    }


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description="A/B SE commit_hours=1 vs open-loop on fixture days."
    )
    parser.add_argument(
        "--days",
        type=str,
        default="2026-06-23,2026-06-25",
        help="Comma-separated ISO dates (default: fixture high/low E-Auto days)",
    )
    args = parser.parse_args(argv)
    _activate_fixtures()

    from simulation.engine import _scenario_to_battery_params
    from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW
    from tests.fixtures.backtesting_fixtures import (
        build_synthetic_prices_df,
        fixture_scenario_params,
        load_fixture_cache,
    )

    days = _parse_days(args.days)
    cache = load_fixture_cache()
    scenario = fixture_scenario_params()
    battery = _scenario_to_battery_params(scenario)
    prices_df = build_synthetic_prices_df(
        pd.Timestamp("2024-07-01"),
        pd.Timestamp("2026-06-26"),
        base_cent=10.0,
        peak_cent=35.0,
    )

    print("SE commit-K A/B (fixture offline)")
    sid = scenario.get("id") or scenario.get("name") or "fixture"
    print(f"days={','.join(d.isoformat() for d in days)} scenario={sid}")
    print()
    for mode in (FIXED_24H, SUNRISE_WINDOW):
        for day in days:
            k1 = _run_window(
                day=day,
                horizon_mode=mode,
                commit_hours_mode="k1",
                cache=cache,
                prices_df=prices_df,
                scenario=scenario,
                battery=battery,
            )
            open_loop = _run_window(
                day=day,
                horizon_mode=mode,
                commit_hours_mode="open",
                cache=cache,
                prices_df=prices_df,
                scenario=scenario,
                battery=battery,
            )
            speedup = (
                (k1["wall_s"] / open_loop["wall_s"])
                if open_loop["wall_s"] > 0
                else float("inf")
            )
            d_cost = open_loop["cost_euro"] - k1["cost_euro"]
            print(
                f"{mode} {day.isoformat()}: "
                f"K=1 {k1['wall_s']:.2f}s EUR {k1['cost_euro']:.3f} SoC={k1['end_soc']} | "
                f"open-loop K={open_loop['commit_hours']} {open_loop['wall_s']:.2f}s "
                f"EUR {open_loop['cost_euro']:.3f} SoC={open_loop['end_soc']} | "
                f"dEUR={d_cost:+.3f} speedup~{speedup:.1f}x"
            )
            print(f"  flex K=1={k1['flex_kwh']} open={open_loop['flex_kwh']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

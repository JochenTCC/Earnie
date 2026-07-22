#!/usr/bin/env python3
"""A/B: SE trivial MILP fast path on vs off (2.3.c.1).

Compares ENERGY_OPTIMIZER_MILP_TRIVIAL_FAST_PATH=0 vs 1 on fixture days.
Includes a no-battery / zero-flex scenario (where the skip applies) plus the
normal fixture scenario (battery present — € must stay unchanged).

Example:
  python -m scripts.ab_se_trivial_fast_path
  python -m scripts.ab_se_trivial_fast_path --days 2026-06-23,2026-06-25
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


def _zero_battery() -> dict:
    return {
        "battery_capacity_kwh": 0.0,
        "min_soc": 0.0,
        "max_soc": 100.0,
        "max_power_kw": 0.0,
        "efficiency": 1.0,
    }


def _run_window(
    *,
    day: date,
    horizon_mode: str,
    cache,
    prices_df: pd.DataFrame,
    scenario: dict,
    battery: dict,
    flexible_consumers: list,
    consumer_targets: dict[str, float] | None = None,
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

    targets = (
        consumer_targets
        if consumer_targets is not None
        else meta["consumer_daily_targets_kwh"]
    )
    commit_hours = len(matrix)
    t0 = time.perf_counter()
    rows = simulate_horizon(
        matrix,
        50.0,
        battery_params=battery,
        verbose=False,
        consumer_daily_targets_kwh=targets,
        sunrise_soc_min_index=sunrise_idx,
        flexible_consumers=flexible_consumers,
        commit_hours=commit_hours,
    )
    elapsed = time.perf_counter() - t0
    end_soc = horizon_end_soc_from_chart_rows(rows)
    flex = delivered_flex_kwh_from_rows(rows, flexible_consumers=flexible_consumers)
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


def _compare_pair(label: str, off: dict, on: dict) -> None:
    speedup = (off["wall_s"] / on["wall_s"]) if on["wall_s"] > 0 else float("inf")
    d_cost = on["cost_euro"] - off["cost_euro"]
    print(
        f"{label}: "
        f"off {off['wall_s']:.2f}s EUR {off['cost_euro']:.3f} SoC={off['end_soc']} | "
        f"on {on['wall_s']:.2f}s EUR {on['cost_euro']:.3f} SoC={on['end_soc']} | "
        f"dEUR={d_cost:+.4f} speedup~{speedup:.1f}x"
    )
    print(f"  flex off={off['flex_kwh']} on={on['flex_kwh']}")


def main(argv: list[str] | None = None) -> int:
    from optimizer.milp import ENV_MILP_TRIVIAL_FAST_PATH

    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description="A/B SE trivial MILP fast path on vs off (fixtures)."
    )
    parser.add_argument(
        "--days",
        type=str,
        default="2026-06-23,2026-06-25",
        help="Comma-separated ISO dates (default: fixture high/low E-Auto days)",
    )
    args = parser.parse_args(argv)
    _activate_fixtures()

    from simulation.engine import (
        _flexible_consumers_from_scenario,
        _scenario_to_battery_params,
    )
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
    flex_consumers = _flexible_consumers_from_scenario(scenario)
    prices_df = build_synthetic_prices_df(
        pd.Timestamp("2024-07-01"),
        pd.Timestamp("2026-06-26"),
        base_cent=10.0,
        peak_cent=35.0,
    )

    print("SE trivial fast-path A/B (fixture offline)")
    sid = scenario.get("id") or scenario.get("name") or "fixture"
    print(f"days={','.join(d.isoformat() for d in days)} env={ENV_MILP_TRIVIAL_FAST_PATH}")
    print()

    cases = [
        (
            "with_battery_flex",
            scenario,
            battery,
            flex_consumers,
            None,
        ),
        (
            "no_battery_zero_flex",
            scenario,
            _zero_battery(),
            flex_consumers,
            {c["id"]: 0.0 for c in flex_consumers},
        ),
    ]

    totals_off = 0.0
    totals_on = 0.0
    for case_name, scen, batt, consumers, targets in cases:
        print(f"=== {case_name} (scenario={sid}) ===")
        for mode in (FIXED_24H, SUNRISE_WINDOW):
            for day in days:
                os.environ[ENV_MILP_TRIVIAL_FAST_PATH] = "0"
                off = _run_window(
                    day=day,
                    horizon_mode=mode,
                    cache=cache,
                    prices_df=prices_df,
                    scenario=scen,
                    battery=batt,
                    flexible_consumers=consumers,
                    consumer_targets=targets,
                )
                os.environ[ENV_MILP_TRIVIAL_FAST_PATH] = "1"
                on = _run_window(
                    day=day,
                    horizon_mode=mode,
                    cache=cache,
                    prices_df=prices_df,
                    scenario=scen,
                    battery=batt,
                    flexible_consumers=consumers,
                    consumer_targets=targets,
                )
                totals_off += off["wall_s"]
                totals_on += on["wall_s"]
                _compare_pair(f"{case_name} {mode} {day.isoformat()}", off, on)
        print()

    pool_speedup = (totals_off / totals_on) if totals_on > 0 else float("inf")
    print(
        f"POOL wall: off={totals_off:.2f}s on={totals_on:.2f}s "
        f"speedup~{pool_speedup:.2f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

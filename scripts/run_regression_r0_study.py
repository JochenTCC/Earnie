"""Regression R0 — HiGHS determinism / tolerance study on recorder cycles.

Reduced 2.7 scope (spec §16): 2–3 full 96-slot cases, production vs
EARNIE_CBC_STRICT, idle vs parallel load, HiGHS only.

  python -m scripts.run_regression_r0_study --recorder-dir PATH
  python -m scripts.run_regression_r0_study --seed --env-path earnie_env

Prefer ``--recorder-dir`` pointing at live ``runtime/recorder/`` once it has
full 96-slot cycles. ``--seed`` (historical backtesting windows rewritten into
recorder format) is a bootstrap only — substitute with newer live recordings
as soon as they exist (spec §16 R0 follow-up).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

os.environ.setdefault("EARNIE_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SolverMode = Literal["production", "strict"]
MODES: tuple[SolverMode, ...] = ("production", "strict")


@dataclass(frozen=True)
class StudyRun:
    case_id: str
    mode: str
    load: str
    rep: int
    stage: str
    status: str
    seconds: float
    cost_euro: float | None
    plan_hash: str
    n_slots: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regression R0 solver determinism study (recorder cycles).",
    )
    parser.add_argument(
        "--recorder-dir",
        type=Path,
        default=None,
        help="Path to recorder root (cycles_*.jsonl.gz + configs/).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "backtesting_logs" / "regression_r0",
        help="Report output directory (gitignored under backtesting_logs/).",
    )
    parser.add_argument("--reps", type=int, default=5, help="Repetitions per mode.")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel workers for load arm (default: min(CPU, reps)).",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=3,
        help="Max full-horizon cases to use (default 3).",
    )
    parser.add_argument(
        "--min-slots",
        type=int,
        default=96,
        help="Minimum matrix rows for a case (default 96).",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help=(
            "Bootstrap only: seed recorder cycles from historical backtesting "
            "windows. Prefer live runtime/recorder/ via --recorder-dir ASAP."
        ),
    )
    parser.add_argument(
        "--env-path",
        type=Path,
        default=None,
        help="Earnie env root for --seed (default: EARNIE_ENV_PATH or earnie_env).",
    )
    parser.add_argument(
        "--hour-offsets",
        type=int,
        nargs="*",
        default=[1392, 2400, 3600],
        help="Backtesting hour offsets for --seed (distinct 24h windows).",
    )
    return parser.parse_args()


def _default_env_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    raw = os.environ.get("EARNIE_ENV_PATH") or "earnie_env"
    return Path(raw)


def _seed_recorder(
    *,
    env_path: Path,
    copy_to: Path,
    hour_offsets: list[int],
    min_slots: int,
) -> Path:
    """Write 2–3 full-horizon cycles via the live recorder API, then copy to ``copy_to``.

    Uses the env's natural ``runtime/`` (needs cons_data.csv). Does **not** redirect
    ``EARNIE_RUNTIME_PATH``, so historical cache and config sidecars keep working.
    """
    import pandas as pd
    import shutil

    from data.data_loader import load_market_prices
    from runtime_store.config_load import load_config_or_exit
    from runtime_store import cycle_recorder
    from scripts.run_backtesting import resolve_backtesting_window
    from simulation.engine import (
        HistoricalDataCache,
        list_simulation_anchors,
        window_slot_datetimes,
    )
    from simulation.matrix_builder import build_historical_window_matrix

    if not env_path.is_dir():
        raise SystemExit(f"--env-path missing: {env_path}")
    os.environ["EARNIE_ENV_PATH"] = str(env_path.resolve())
    os.environ.pop("EARNIE_RUNTIME_PATH", None)
    os.environ.pop("EARNIE_CONFIG_PATH", None)
    config = load_config_or_exit()
    config.reinit_config()
    cycle_recorder.reset_for_tests()

    sim_cfg = config.get_scenario_explorer_conf()
    # Window must overlap cons_data (this env: 2025-10 … 2026-09).
    start, end = resolve_backtesting_window(
        pd.Timestamp(2025, 10, 1),
        pd.Timestamp(2026, 3, 1),
        sim_cfg.get("price_range", "last_12_months"),
    )
    prices = load_market_prices(
        start,
        end,
        sim_cfg,
        awattar_url=config.get("AWATTAR_URL"),
        timeout=config.get_global_timeout(default=30),
    )
    cache = HistoricalDataCache()
    cache.load()
    anchors = list_simulation_anchors(start, end, cache)
    if not anchors:
        raise SystemExit("no simulation anchors for seed windows")
    scenario_params = dict(config.get_backtesting_scenarios()["live"])
    feed_in = config.get_backtesting_feed_in_settings(runtime_override=scenario_params)

    written = 0
    for hour_offset in hour_offsets:
        win_idx = hour_offset // 24
        if win_idx < 0 or win_idx >= len(anchors):
            print(f"skip hour-offset {hour_offset}: out of range")
            continue
        anchor = anchors[win_idx]
        slots = window_slot_datetimes(anchor)
        matrix, meta = build_historical_window_matrix(
            anchor,
            cache,
            prices,
            feed_in_settings=feed_in,
            scenario_params=scenario_params,
        )
        if len(matrix) < min_slots:
            print(f"skip {anchor}: only {len(matrix)} slots")
            continue
        # Segment day must be "today" or prune_old_segments deletes historical anchors.
        seed_ts = datetime.now().replace(microsecond=0)
        token = cycle_recorder.begin_cycle(
            optimization_matrix=matrix,
            planning_window={
                "start": slots[0].isoformat(timespec="seconds"),
                "end": slots[-1].isoformat(timespec="seconds"),
                "slot_datetimes": [s.isoformat(timespec="seconds") for s in slots],
                "horizon_hours": 24,
                "seed_anchor": anchor.isoformat(timespec="seconds"),
            },
            soc_percent=50.0,
            targets=meta.get("consumer_daily_targets_kwh") or {},
            timestamp=seed_ts,
        )
        if token is None:
            raise SystemExit("begin_cycle returned None (recorder disabled?)")
        ok = cycle_recorder.finish_cycle(
            token,
            mode=0,
            target_power_kw=0.0,
            battery_plan_kw=0.0,
            consumer_powers_kw={},
            flags={
                "override": False,
                "immediate_charging": False,
                "outage": False,
                "manual_intervention": False,
            },
        )
        if not ok:
            raise SystemExit("finish_cycle failed while seeding")
        written += 1
        print(f"seeded case {written}: {anchor.isoformat()} ({len(matrix)} slots)")
        if written >= 3:
            break
    if written < 2:
        raise SystemExit(
            f"seed produced only {written} cases; need at least 2 "
            f"(check cons_data / anchors under {env_path})"
        )
    live_recorder = Path(cycle_recorder.recorder_dir())
    if copy_to.exists():
        shutil.rmtree(copy_to)
    shutil.copytree(live_recorder, copy_to)
    print(f"seeded {written} cycles; copied recorder to {copy_to}")
    return copy_to


def _case_id(entry: dict[str, Any], index: int) -> str:
    ts = str(entry.get("timestamp") or f"case{index}")
    safe = ts.replace(":", "").replace(" ", "T")
    return f"R0-{index}-{safe}"


def _worker_run(
    payload: dict[str, Any],
) -> StudyRun:
    """Process entry point: replay one (case, mode, rep) under controlled env."""
    from runtime_store.recorder_replay import replay_recorded_cycle

    result = replay_recorded_cycle(
        payload["entry"],
        recorder_root=Path(payload["recorder_root"]),
        solver_mode=payload["mode"],
        verbose=False,
    )
    return StudyRun(
        case_id=payload["case_id"],
        mode=payload["mode"],
        load=payload["load"],
        rep=int(payload["rep"]),
        stage=result.stage,
        status=result.status,
        seconds=result.seconds,
        cost_euro=result.cost_euro,
        plan_hash=result.plan_hash,
        n_slots=result.n_slots,
    )


def _run_idle(
    cases: list[tuple[str, dict[str, Any]]],
    recorder_root: Path,
    reps: int,
) -> list[StudyRun]:
    runs: list[StudyRun] = []
    for case_id, entry in cases:
        for mode in MODES:
            for rep in range(1, reps + 1):
                print(f"idle {case_id} {mode} rep={rep}/{reps}")
                runs.append(
                    _worker_run(
                        {
                            "entry": entry,
                            "recorder_root": str(recorder_root),
                            "case_id": case_id,
                            "mode": mode,
                            "load": "idle",
                            "rep": rep,
                        }
                    )
                )
    return runs


def _run_parallel(
    cases: list[tuple[str, dict[str, Any]]],
    recorder_root: Path,
    reps: int,
    workers: int,
) -> list[StudyRun]:
    payloads: list[dict[str, Any]] = []
    for case_id, entry in cases:
        for mode in MODES:
            for rep in range(1, reps + 1):
                payloads.append(
                    {
                        "entry": entry,
                        "recorder_root": str(recorder_root),
                        "case_id": case_id,
                        "mode": mode,
                        "load": "parallel",
                        "rep": rep,
                    }
                )
    runs: list[StudyRun] = []
    print(f"parallel arm: {len(payloads)} jobs, workers={workers}")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_worker_run, payload) for payload in payloads]
        for future in as_completed(futures):
            run = future.result()
            print(
                f"parallel done {run.case_id} {run.mode} rep={run.rep} "
                f"{run.seconds:.2f}s hash={run.plan_hash}"
            )
            runs.append(run)
    return runs


def _group_key(run: StudyRun) -> tuple[str, str, str]:
    return (run.case_id, run.mode, run.load)


def _summarize(runs: list[StudyRun]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[StudyRun]] = {}
    for run in runs:
        groups.setdefault(_group_key(run), []).append(run)
    rows: list[dict[str, Any]] = []
    for key, items in sorted(groups.items()):
        case_id, mode, load = key
        costs = [r.cost_euro for r in items if r.cost_euro is not None]
        hashes = {r.plan_hash for r in items}
        stages = {r.stage for r in items}
        statuses = {r.status for r in items}
        seconds = [r.seconds for r in items]
        cost_spread_pct = None
        if costs:
            mid = statistics.mean(costs)
            if mid != 0:
                cost_spread_pct = 100.0 * (max(costs) - min(costs)) / abs(mid)
            else:
                cost_spread_pct = 0.0 if max(costs) == min(costs) else None
        rows.append(
            {
                "case_id": case_id,
                "mode": mode,
                "load": load,
                "n_reps": len(items),
                "unique_plan_hashes": len(hashes),
                "plan_hashes": sorted(hashes),
                "stages": sorted(stages),
                "statuses": sorted(statuses),
                "cost_min": min(costs) if costs else None,
                "cost_max": max(costs) if costs else None,
                "cost_mean": statistics.mean(costs) if costs else None,
                "cost_spread_pct": cost_spread_pct,
                "seconds_mean": statistics.mean(seconds) if seconds else None,
                "seconds_max": max(seconds) if seconds else None,
            }
        )
    return rows


def _recommend_tolerances(summary: list[dict[str, Any]]) -> dict[str, Any]:
    strict_rows = [r for r in summary if r["mode"] == "strict"]
    prod_rows = [r for r in summary if r["mode"] == "production"]
    strict_optimal = [
        r for r in strict_rows if set(r["statuses"]) == {"Optimal"}
    ]
    strict_stable = bool(strict_optimal) and all(
        r["unique_plan_hashes"] == 1 for r in strict_optimal
    )
    strict_cost_spreads = [
        r["cost_spread_pct"]
        for r in strict_optimal
        if r["cost_spread_pct"] is not None
    ]
    max_strict_spread = max(strict_cost_spreads) if strict_cost_spreads else 0.0
    # Headroom: 2× measured spread, floor 0.05 % when bit-stable under strict.
    if strict_stable:
        tol = max(0.05, min(0.5, 2.0 * max_strict_spread)) if max_strict_spread else 0.05
    else:
        tol = 0.5
    skipped = [
        r["case_id"]
        for r in strict_rows
        if set(r["statuses"]) != {"Optimal"}
    ]
    return {
        "regression_solver_mode": "strict",
        "env": "EARNIE_CBC_STRICT=1",
        "strict_plan_hash_stable": strict_stable,
        "strict_optimal_case_groups": len(strict_optimal),
        "strict_max_cost_spread_pct": max_strict_spread,
        "recommended_metric_tolerance_pct": round(tol, 4),
        "non_optimal_cases": sorted(set(skipped)),
        "production_path_sample": "open (follow-up)",
        "notes": (
            "Goldens use deterministic strict HiGHS (no wall-clock). "
            "Production-path sample stays open per backlog R0. "
            "Tolerances derived from Optimal strict groups only."
        ),
    }


def _highspy_version() -> str:
    try:
        import highspy
        import importlib.metadata

        return importlib.metadata.version("highspy")
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({exc})"


def _write_report(
    out_dir: Path,
    *,
    runs: list[StudyRun],
    summary: list[dict[str, Any]],
    recommendation: dict[str, Any],
    recorder_root: Path,
    highspy: str,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = out_dir / f"r0_runs_{stamp}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(runs[0]).keys()))
        writer.writeheader()
        for run in runs:
            writer.writerow(asdict(run))
    md_path = out_dir / f"r0_report_{stamp}.md"
    lines = [
        "# Regression R0 — solver determinism report",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Recorder: `{recorder_root}`",
        f"- highspy: `{highspy}`",
        f"- Runs CSV: `{csv_path.name}`",
        "",
        "## Recommendation",
        "",
        "```json",
        json.dumps(recommendation, indent=2),
        "```",
        "",
        "## Summary by case / mode / load",
        "",
        "| case | mode | load | hashes | cost spread % | stages | status |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for row in summary:
        spread = row["cost_spread_pct"]
        spread_s = "n/a" if spread is None else f"{spread:.4f}"
        lines.append(
            f"| {row['case_id']} | {row['mode']} | {row['load']} | "
            f"{row['unique_plan_hashes']} | {spread_s} | "
            f"{','.join(row['stages'])} | {','.join(row['statuses'])} |"
        )
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    (out_dir / f"r0_summary_{stamp}.json").write_text(
        json.dumps(
            {
                "highspy": highspy,
                "recorder_root": str(recorder_root),
                "recommendation": recommendation,
                "summary": summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return md_path


def main() -> int:
    args = _parse_args()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.seed:
        recorder_root = _seed_recorder(
            env_path=_default_env_path(args.env_path),
            copy_to=out_dir / "seed_recorder",
            hour_offsets=list(args.hour_offsets),
            min_slots=args.min_slots,
        )
    else:
        if args.recorder_dir is None:
            raise SystemExit("pass --recorder-dir or --seed")
        recorder_root = args.recorder_dir
        if not recorder_root.is_dir():
            raise SystemExit(f"--recorder-dir missing: {recorder_root}")

    from runtime_store.recorder_replay import list_full_horizon_cycles

    entries = list_full_horizon_cycles(
        recorder_root,
        min_slots=args.min_slots,
        max_cases=args.max_cases,
        require_unflagged=True,
    )
    if len(entries) < 2:
        raise SystemExit(
            f"need at least 2 unflagged cycles with >={args.min_slots} slots; "
            f"found {len(entries)} under {recorder_root}. "
            f"Use --seed if live recorder is empty."
        )
    cases = [(_case_id(entry, i + 1), entry) for i, entry in enumerate(entries)]
    print(f"using {len(cases)} cases from {recorder_root}")

    cpu = os.cpu_count() or 2
    workers = args.workers if args.workers is not None else min(cpu, args.reps)
    workers = max(1, int(workers))

    t0 = time.perf_counter()
    runs = _run_idle(cases, recorder_root, args.reps)
    runs.extend(_run_parallel(cases, recorder_root, args.reps, workers))
    elapsed = time.perf_counter() - t0
    summary = _summarize(runs)
    recommendation = _recommend_tolerances(summary)
    highspy = _highspy_version()
    report = _write_report(
        out_dir,
        runs=runs,
        summary=summary,
        recommendation=recommendation,
        recorder_root=recorder_root,
        highspy=highspy,
    )
    print(f"\nStudy finished in {elapsed:.1f}s")
    print(f"Report: {report}")
    print(json.dumps(recommendation, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

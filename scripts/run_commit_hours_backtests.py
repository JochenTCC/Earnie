"""Run earnie_env SE backtesting at commit_hours=K=24 for 12 months.

Default period: last 12 *complete* calendar months in cons_data
(`resolve_simulation_window`) — not months 1–12 of the incomplete current year
(e.g. 2026 clipped to July).

Compares `fixed_24h` vs `sunrise_window` at the same K.

Does not mutate earnie_env: each run gets a temp scenarios JSON with only
commit_hours (and optional scenario filter) changed.

Example:
  python -m scripts.run_commit_hours_backtests
  python -m scripts.run_commit_hours_backtests --workers 2
  python -m scripts.run_commit_hours_backtests --start-month 1 --end-month 12
  python -m scripts.run_commit_hours_backtests --skip-runs
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_COMMIT_HOURS = 24
DEFAULT_BASELINE_HORIZON = "fixed_24h"


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _parse_str_list(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _default_scenarios_path(env_path: Path) -> Path:
    return env_path / "config" / "backtesting_scenarios.json"


def _write_scenarios_override(
    source: Path,
    dest: Path,
    *,
    commit_hours: int,
    scenario_ids: list[str] | None,
) -> None:
    doc = json.loads(source.read_text(encoding="utf-8"))
    doc["commit_hours"] = int(commit_hours)
    if scenario_ids:
        scenarios = doc.get("scenarios") or []
        wanted = set(scenario_ids)
        filtered = [s for s in scenarios if str(s.get("id", "")) in wanted]
        missing = wanted - {str(s.get("id", "")) for s in filtered}
        if missing:
            raise SystemExit(
                f"Unknown scenario id(s) in {source}: {sorted(missing)}"
            )
        if not filtered:
            raise SystemExit(f"No scenarios left after filter {scenario_ids!r}")
        doc["scenarios"] = filtered
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(doc, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def _run_one(
    *,
    output_dir: Path,
    commit_hours: int,
    horizon_mode: str,
    start_month: int | None,
    end_month: int | None,
    workers: int,
    env_path: Path,
    scenarios_source: Path,
    scenario_ids: list[str] | None,
    extra_args: list[str],
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    override_path = output_dir / f"backtesting_scenarios_commit_{commit_hours}.json"
    _write_scenarios_override(
        scenarios_source,
        override_path,
        commit_hours=commit_hours,
        scenario_ids=scenario_ids,
    )
    env = os.environ.copy()
    env["EARNIE_ENV_PATH"] = str(env_path)
    env["EARNIE_BACKTESTING_SCENARIOS_PATH"] = str(override_path)
    env["ENERGY_OPTIMIZER_OFFLINE"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    cmd = [
        sys.executable,
        "-m",
        "scripts.run_backtesting",
        "--horizon-mode",
        horizon_mode,
        "--workers",
        str(workers),
        "--output-dir",
        str(output_dir),
        "--log-file",
        str(output_dir / f"run_k{commit_hours}.log"),
    ]
    # Omit months → run_backtesting uses last 12 complete cons_data months.
    if start_month is not None and end_month is not None:
        cmd.extend(
            ["--start-month", str(start_month), "--end-month", str(end_month)]
        )
    elif start_month is not None or end_month is not None:
        raise SystemExit("Pass both --start-month and --end-month, or neither.")
    cmd.extend(extra_args)

    period_label = (
        f"months {start_month}–{end_month} (base year of cons_data max)"
        if start_month is not None
        else "last 12 complete months (cons_data)"
    )
    print(
        f"\n=== commit_hours={commit_hours} horizon={horizon_mode} "
        f"period={period_label} → {output_dir} ==="
    )
    t0 = time.perf_counter()
    subprocess.run(cmd, check=True, env=env, cwd=str(ROOT))
    wall_s = time.perf_counter() - t0
    timing = {
        "commit_hours": commit_hours,
        "horizon_mode": horizon_mode,
        "wall_s": round(wall_s, 3),
        "start_month": start_month,
        "end_month": end_month,
        "period": period_label,
        "workers": workers,
        "scenarios_override": str(override_path),
    }
    (output_dir / "wall_time.json").write_text(
        json.dumps(timing, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wall time: {wall_s:.1f}s")
    return timing


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _wall_s(run_dir: Path) -> float | None:
    path = run_dir / "wall_time.json"
    if not path.is_file():
        return None
    raw = _load_json(path).get("wall_s")
    return None if raw is None else float(raw)


def _plaus_ok(plausibility: dict, scenario_id: str) -> str:
    report = plausibility.get(scenario_id) or {}
    return f"{report.get('ok_count', 0)}/{report.get('total_windows', 0)}"


def _discover_mode_runs(
    output_root: Path,
    *,
    commit_hours: int,
    horizon_modes: list[str],
) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for mode in horizon_modes:
        candidate = output_root / mode / f"k{commit_hours}"
        if (candidate / "backtesting_log.json").is_file():
            found[mode] = candidate
    return found


def _compare_horizon_modes(
    output_root: Path,
    *,
    commit_hours: int,
    horizon_modes: list[str],
    baseline_mode: str,
) -> None:
    """Write Markdown + CSV comparing horizon modes at fixed K."""
    run_dirs = _discover_mode_runs(
        output_root,
        commit_hours=commit_hours,
        horizon_modes=horizon_modes,
    )
    if len(run_dirs) < 2:
        raise SystemExit(
            f"Need at least two horizon runs under {output_root} "
            f"(found: {sorted(run_dirs)})."
        )
    if baseline_mode not in run_dirs:
        raise SystemExit(
            f"Baseline horizon {baseline_mode!r} missing among runs "
            f"{sorted(run_dirs)}."
        )

    runs = {m: _load_json(d / "backtesting_log.json") for m, d in run_dirs.items()}
    base = runs[baseline_mode]
    labels = base.get("labels", {})
    ref_id = base.get("reference_id", "historical_reference")
    base_totals = base["summary"]["total_eur"]
    period = base.get("period", {})
    modes = [m for m in horizon_modes if m in runs]

    rows: list[dict] = []
    for sid, label in labels.items():
        if sid == ref_id:
            continue
        row: dict = {
            "scenario_id": sid,
            "label": label,
            "ref_eur": base_totals.get(ref_id),
        }
        for mode in modes:
            totals = runs[mode]["summary"]["total_eur"]
            eur = totals.get(sid)
            row[f"eur_{mode}"] = eur
            if eur is not None and base_totals.get(sid) is not None:
                row[f"d_eur_{mode}_vs_{baseline_mode}"] = round(
                    float(eur) - float(base_totals[sid]), 4
                )
            else:
                row[f"d_eur_{mode}_vs_{baseline_mode}"] = None
            row[f"plaus_{mode}"] = _plaus_ok(
                runs[mode].get("plausibility", {}), sid
            )
        rows.append(row)

    ref_eur = base_totals.get(ref_id)
    if ref_eur is not None:
        ref_line = f"- Reference ({labels.get(ref_id, ref_id)}): {ref_eur:.2f} €"
    else:
        ref_line = f"- Reference: {ref_id}"

    lines = [
        "# Horizon-mode Backtesting Comparison (fixed K)",
        "",
        f"- Output root: `{output_root.as_posix()}`",
        f"- Period: `{period.get('start')}` – `{period.get('end')}` "
        f"· windows={period.get('windows')}",
        f"- commit_hours (K): **{commit_hours}**",
        f"- Baseline horizon: **{baseline_mode}**",
        f"- Modes: {', '.join(f'`{m}`' for m in modes)}",
        ref_line,
        "",
        "## Wall time (full backtesting process)",
        "",
        f"| horizon_mode | wall_s | speedup vs {baseline_mode} |",
        "|--------------|--------|---------------------------|",
    ]
    base_wall = _wall_s(run_dirs[baseline_mode])
    for mode in modes:
        wall = _wall_s(run_dirs[mode])
        if wall is None:
            wall_s, speed = "—", "—"
        else:
            wall_s = f"{wall:.1f}"
            if base_wall and wall > 0:
                speed = f"{base_wall / wall:.2f}x"
            else:
                speed = "—"
        lines.append(f"| `{mode}` | {wall_s} | {speed} |")

    eur_cols = " | ".join(f"€ {m}" for m in modes)
    d_cols = " | ".join(
        f"Δ€ vs {baseline_mode} ({m})" for m in modes if m != baseline_mode
    )
    header = f"| Scenario | {eur_cols} |"
    if d_cols:
        header = f"| Scenario | {eur_cols} | {d_cols} |"
    sep = "|" + "|".join(["----------"] * (header.count("|") - 1)) + "|"
    lines.extend(["", "## Costs by scenario", "", header, sep])

    for row in rows:
        cells = [str(row["label"])]
        for mode in modes:
            val = row.get(f"eur_{mode}")
            cells.append(f"{val:.2f}" if val is not None else "—")
        for mode in modes:
            if mode == baseline_mode:
                continue
            dval = row.get(f"d_eur_{mode}_vs_{baseline_mode}")
            cells.append(f"{dval:+.3f}" if dval is not None else "—")
        lines.append("| " + " | ".join(cells) + " |")

    plaus_cols = " | ".join(f"plaus {m}" for m in modes)
    lines.extend(
        [
            "",
            "## Plausibility (ok/total windows)",
            "",
            f"| Scenario | {plaus_cols} |",
            "|" + "|".join(["----------"] * (len(modes) + 1)) + "|",
        ]
    )
    for row in rows:
        cells = [str(row["label"])] + [
            str(row.get(f"plaus_{mode}", "—")) for mode in modes
        ]
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    md_path = output_root / "comparison.md"
    csv_path = output_root / "comparison.csv"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    if rows:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(rows[0].keys()), delimiter=";"
            )
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")
    print(f"Horizon comparison written: {md_path}")
    print(f"CSV written: {csv_path}")


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description=(
            "Run earnie_env backtesting at commit_hours=24 for the last 12 "
            "complete cons_data months and compare fixed_24h vs sunrise_window."
        )
    )
    parser.add_argument(
        "--env-path",
        type=Path,
        default=Path("earnie_env"),
        help="Earnie env root (default: earnie_env).",
    )
    parser.add_argument(
        "--scenarios-file",
        type=Path,
        default=None,
        help="Source backtesting_scenarios.json (default: <env>/config/...).",
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default="",
        help="Optional comma-separated scenario ids (default: all in file).",
    )
    parser.add_argument(
        "--commit-hours",
        type=int,
        default=DEFAULT_COMMIT_HOURS,
        metavar="K",
        help=f"MILP commit-K (default: {DEFAULT_COMMIT_HOURS}).",
    )
    parser.add_argument(
        "--horizon-modes",
        type=str,
        default="fixed_24h,sunrise_window",
        help="Comma-separated horizon modes to compare (default: both).",
    )
    parser.add_argument(
        "--baseline-horizon",
        type=str,
        default=DEFAULT_BASELINE_HORIZON,
        help=(
            "Baseline horizon for € deltas / wall speedup "
            f"(default: {DEFAULT_BASELINE_HORIZON})."
        ),
    )
    parser.add_argument(
        "--start-month",
        type=int,
        default=None,
        metavar="MONAT",
        help=(
            "Optional first month (1–12) in cons_data base year. "
            "Omit with --end-month for last 12 complete months."
        ),
    )
    parser.add_argument(
        "--end-month",
        type=int,
        default=None,
        metavar="MONAT",
        help=(
            "Optional last month (1–12) in cons_data base year. "
            "Omit with --start-month for last 12 complete months."
        ),
    )
    parser.add_argument("--workers", type=int, default=1, metavar="N")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Output root (default: "
            "backtesting_logs/horizon_k24_compare_last12m)."
        ),
    )
    parser.add_argument(
        "--skip-runs",
        action="store_true",
        help="Only rebuild horizon comparison from existing logs.",
    )
    parser.add_argument(
        "backtesting_args",
        nargs=argparse.REMAINDER,
        help="Extra args for run_backtesting after --.",
    )
    args = parser.parse_args(argv)

    if args.commit_hours < 1:
        raise SystemExit("--commit-hours must be >= 1")

    env_path = args.env_path
    if not env_path.is_absolute():
        env_path = (ROOT / env_path).resolve()
    scenarios_source = args.scenarios_file or _default_scenarios_path(env_path)
    if not scenarios_source.is_file():
        raise SystemExit(f"Scenarios file not found: {scenarios_source}")

    modes = _parse_str_list(args.horizon_modes)
    if len(modes) < 2 and not args.skip_runs:
        print(
            "Warning: fewer than two horizon modes — comparison needs ≥2 runs.",
            file=sys.stderr,
        )
    scenario_ids = _parse_str_list(args.scenarios) or None
    extra = [a for a in args.backtesting_args if a != "--"]
    k = int(args.commit_hours)

    if args.output_root is None:
        if args.start_month is None and args.end_month is None:
            tag = "last12m"
        elif args.start_month == args.end_month:
            tag = f"{args.start_month:02d}"
        else:
            tag = f"{args.start_month:02d}-{args.end_month:02d}"
        output_root = ROOT / "backtesting_logs" / f"horizon_k{k}_compare_{tag}"
    else:
        output_root = args.output_root
        if not output_root.is_absolute():
            output_root = (ROOT / output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    all_timings: list[dict] = []
    if not args.skip_runs:
        for mode in modes:
            timing = _run_one(
                output_dir=output_root / mode / f"k{k}",
                commit_hours=k,
                horizon_mode=mode,
                start_month=args.start_month,
                end_month=args.end_month,
                workers=args.workers,
                env_path=env_path,
                scenarios_source=scenarios_source,
                scenario_ids=scenario_ids,
                extra_args=extra,
            )
            all_timings.append(timing)
        timing_path = output_root / "timing.json"
        timing_path.write_text(
            json.dumps({"runs": all_timings}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nTiming summary: {timing_path}")
    else:
        print(f"Skipping runs; comparing existing logs under {output_root}")

    _compare_horizon_modes(
        output_root,
        commit_hours=k,
        horizon_modes=modes,
        baseline_mode=args.baseline_horizon,
    )

    print(f"\nDone. Artifacts under: {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

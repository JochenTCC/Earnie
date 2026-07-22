"""Year A/B: truncated sunrise_window vs full SA_0-->SA_2 + flex_book (2.3.c.3).

Default period: last 12 complete calendar months in cons_data.
Baseline arm forces sunrise_full_horizon_trial=false (old truncate);
full arm uses true (product default since 2026-07-22).

Example:
  python -m scripts.run_sunrise_full_ab_backtests
  python -m scripts.run_sunrise_full_ab_backtests --output-root backtesting_logs/sunrise_full_flexbook_ab_last12m
  python -m scripts.run_sunrise_full_ab_backtests --skip-runs
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

ARM_BASELINE = "truncated"
ARM_FULL = "full"


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
    sunrise_full_horizon_trial: bool,
    scenario_ids: list[str] | None,
) -> None:
    doc = json.loads(source.read_text(encoding="utf-8"))
    doc["sunrise_full_horizon_trial"] = bool(sunrise_full_horizon_trial)
    if not sunrise_full_horizon_trial:
        doc.pop("disable_horizon_soc_anchor", None)
    if scenario_ids:
        scenarios = doc.get("scenarios") or []
        wanted = set(scenario_ids)
        filtered = [s for s in scenarios if str(s.get("id", "")) in wanted]
        missing = wanted - {str(s.get("id", "")) for s in filtered}
        if missing:
            raise SystemExit(f"Unknown scenario id(s) in {source}: {sorted(missing)}")
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
    full_trial: bool,
    start_month: int | None,
    end_month: int | None,
    workers: int,
    env_path: Path,
    scenarios_source: Path,
    scenario_ids: list[str] | None,
    extra_args: list[str],
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    arm = ARM_FULL if full_trial else ARM_BASELINE
    override_path = output_dir / f"backtesting_scenarios_{arm}.json"
    _write_scenarios_override(
        scenarios_source,
        override_path,
        sunrise_full_horizon_trial=full_trial,
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
        "sunrise_window",
        "--workers",
        str(workers),
        "--output-dir",
        str(output_dir),
        "--log-file",
        str(output_dir / f"run_{arm}.log"),
    ]
    if start_month is not None and end_month is not None:
        cmd.extend(["--start-month", str(start_month), "--end-month", str(end_month)])
    elif start_month is not None or end_month is not None:
        raise SystemExit("Pass both --start-month and --end-month, or neither.")
    cmd.extend(extra_args)

    period_label = (
        f"months {start_month}–{end_month}"
        if start_month is not None
        else "last 12 complete months (cons_data)"
    )
    print(f"\n=== sunrise_window arm={arm} period={period_label} → {output_dir} ===")
    t0 = time.perf_counter()
    subprocess.run(cmd, check=True, env=env, cwd=str(ROOT))
    wall_s = time.perf_counter() - t0
    timing = {
        "horizon_mode": "sunrise_window",
        "sunrise_full_horizon_trial": full_trial,
        "arm": arm,
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


def _compare(output_root: Path) -> None:
    base_dir = output_root / ARM_BASELINE
    full_dir = output_root / ARM_FULL
    for label, path in ((ARM_BASELINE, base_dir), (ARM_FULL, full_dir)):
        if not (path / "backtesting_log.json").is_file():
            raise SystemExit(f"Missing backtesting_log.json for arm {label}: {path}")

    base_log = _load_json(base_dir / "backtesting_log.json")
    full_log = _load_json(full_dir / "backtesting_log.json")
    labels = base_log.get("labels", {})
    ref_id = base_log.get("reference_id", "historical_reference")
    base_totals = base_log["summary"]["total_eur"]
    full_totals = full_log["summary"]["total_eur"]
    period = base_log.get("period", {})

    rows: list[dict] = []
    for sid, label in labels.items():
        if sid == ref_id:
            continue
        base_eur = base_totals.get(sid)
        full_eur = full_totals.get(sid)
        delta = None
        if base_eur is not None and full_eur is not None:
            delta = round(float(full_eur) - float(base_eur), 4)
        rows.append(
            {
                "scenario_id": sid,
                "label": label,
                "eur_truncated": base_eur,
                "eur_full": full_eur,
                "d_eur_full_minus_truncated": delta,
                "plaus_truncated": _plaus_ok(base_log.get("plausibility", {}), sid),
                "plaus_full": _plaus_ok(full_log.get("plausibility", {}), sid),
            }
        )

    base_wall = _wall_s(base_dir)
    full_wall = _wall_s(full_dir)
    speed = "—"
    if base_wall and full_wall and full_wall > 0:
        speed = f"{base_wall / full_wall:.2f}x (baseline/full)"

    lines = [
        "# Sunrise Full-Horizon A/B (truncated vs full+flexbook)",
        "",
        f"- Output root: `{output_root.as_posix()}`",
        f"- Period: `{period.get('start')}` – `{period.get('end')}` "
        f"· windows={period.get('windows')}",
        "- horizon_mode: **sunrise_window**",
        f"- Arms: `{ARM_BASELINE}` = default truncate+SA1 SOC_min; "
        f"`{ARM_FULL}` = `sunrise_full_horizon_trial` + `flex_book_hours=24`",
        "",
        "## Wall time",
        "",
        "| arm | wall_s | note |",
        "|-----|--------|------|",
        (
            f"| {ARM_BASELINE} | {base_wall:.1f} | |"
            if base_wall is not None
            else f"| {ARM_BASELINE} | — | |"
        ),
        (
            f"| {ARM_FULL} | {full_wall:.1f} | {speed} |"
            if full_wall is not None
            else f"| {ARM_FULL} | — | |"
        ),
        "",
        "## Costs by scenario (dEUR = full − truncated)",
        "",
        "| Scenario | EUR truncated | EUR full | dEUR |",
        "|----------|---------------|----------|------|",
    ]
    for row in rows:
        b_s = f"{row['eur_truncated']:.2f}" if row["eur_truncated"] is not None else "—"
        f_s = f"{row['eur_full']:.2f}" if row["eur_full"] is not None else "—"
        d_s = (
            f"{row['d_eur_full_minus_truncated']:+.3f}"
            if row["d_eur_full_minus_truncated"] is not None
            else "—"
        )
        lines.append(f"| {row['label']} | {b_s} | {f_s} | {d_s} |")

    lines.extend(
        [
            "",
            "## Plausibility (ok/total)",
            "",
            "| Scenario | truncated | full |",
            "|----------|-----------|------|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['plaus_truncated']} | {row['plaus_full']} |"
        )
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
    print(f"Comparison written: {md_path}")


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(
        description=(
            "A/B truncated sunrise_window vs sunrise_full_horizon_trial "
            "(with flex_book_hours clamp)."
        )
    )
    parser.add_argument("--env-path", type=Path, default=Path("earnie_env"))
    parser.add_argument("--scenarios-file", type=Path, default=None)
    parser.add_argument("--scenarios", type=str, default="")
    parser.add_argument("--start-month", type=int, default=None)
    parser.add_argument("--end-month", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument(
        "--skip-runs",
        action="store_true",
        help="Only rebuild comparison from existing logs.",
    )
    parser.add_argument(
        "backtesting_args",
        nargs=argparse.REMAINDER,
        help="Extra args for run_backtesting after --.",
    )
    args = parser.parse_args(argv)

    env_path = args.env_path
    if not env_path.is_absolute():
        env_path = (ROOT / env_path).resolve()
    scenarios_source = args.scenarios_file or _default_scenarios_path(env_path)
    if not scenarios_source.is_file():
        raise SystemExit(f"Scenarios file not found: {scenarios_source}")

    scenario_ids = _parse_str_list(args.scenarios) or None
    extra = [a for a in args.backtesting_args if a != "--"]

    if args.output_root is None:
        tag = (
            "last12m"
            if args.start_month is None
            else (
                f"m{args.start_month:02d}"
                if args.start_month == args.end_month
                else f"m{args.start_month:02d}-{args.end_month:02d}"
            )
        )
        output_root = ROOT / "backtesting_logs" / f"sunrise_full_flexbook_ab_{tag}"
    else:
        output_root = args.output_root
        if not output_root.is_absolute():
            output_root = (ROOT / output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    all_timings: list[dict] = []
    if not args.skip_runs:
        for full_trial in (False, True):
            timing = _run_one(
                output_dir=output_root
                / (ARM_FULL if full_trial else ARM_BASELINE),
                full_trial=full_trial,
                start_month=args.start_month,
                end_month=args.end_month,
                workers=args.workers,
                env_path=env_path,
                scenarios_source=scenarios_source,
                scenario_ids=scenario_ids,
                extra_args=extra,
            )
            all_timings.append(timing)
        (output_root / "timings.json").write_text(
            json.dumps(all_timings, indent=2) + "\n",
            encoding="utf-8",
        )

    _compare(output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run SE (Live only) for matrix cells × seasonal months.

Forces --year via patched backtesting_base_year (stock CLI uses cons_data max year).
Uses max useful ProcessPool workers: min(CPU, parallel jobs). Live-only ≈ 3 jobs
(historisch + ref:live + live).

Examples:
  python -m scripts.se_calc_test_run --cells M0,M1,M2 --months 1,4,7,10 --year 2025
  python -m scripts.se_calc_test_run --internal --cell M0 --year 2025 --month 1
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Live-only SE: historisch + per-scenario ref + live scenario.
_DEFAULT_PARALLEL_JOBS = 3


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _python_exe() -> str:
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return str(venv)
    return sys.executable


def _max_useful_workers(*, parallel_jobs: int) -> int:
    cpu = os.cpu_count() or 1
    return max(1, min(cpu, max(1, parallel_jobs)))


def _child_env(cell_meta: dict) -> dict[str, str]:
    env = os.environ.copy()
    env["ENERGY_OPTIMIZER_OFFLINE"] = "1"
    env["EARNIE_ENV_PATH"] = cell_meta["env_root"]
    env["ENERGY_OPTIMIZER_ENV_PATH"] = cell_meta["env_root"]
    env["EARNIE_HOUSE_PROFILES_PATH"] = cell_meta["house_profiles_path"]
    env["ENERGY_OPTIMIZER_HOUSE_PROFILES_PATH"] = cell_meta["house_profiles_path"]
    env["EARNIE_BACKTESTING_SCENARIOS_PATH"] = cell_meta["scenarios_path"]
    env["ENERGY_OPTIMIZER_BACKTESTING_SCENARIOS_PATH"] = cell_meta["scenarios_path"]
    existing = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{existing}" if existing else str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_internal(
    cell: str,
    year: int,
    month: int,
    output_dir: Path,
    *,
    workers: int,
) -> int:
    """In-process: patch year, then call run_backtesting.main()."""
    output_dir.mkdir(parents=True, exist_ok=True)
    import scripts.run_backtesting as rb

    rb.backtesting_base_year = lambda: int(year)  # type: ignore[assignment]
    rb.BACKTESTING_YEAR = int(year)
    sys.argv = [
        "run_backtesting",
        "--start-month",
        str(month),
        "--end-month",
        str(month),
        "--output-dir",
        str(output_dir),
        "--workers",
        str(workers),
    ]
    try:
        rb.main()
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return int(code) if isinstance(code, int) else 1
    return 0


def _run_cell_month(
    cell_meta: dict,
    *,
    cell: str,
    year: int,
    month: int,
    workers: int,
) -> int:
    from scripts.se_calc_test_common import run_output_dir

    out = run_output_dir(cell, year, month)
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        _python_exe(),
        "-m",
        "scripts.se_calc_test_run",
        "--internal",
        "--cell",
        cell,
        "--year",
        str(year),
        "--month",
        str(month),
        "--output-dir",
        str(out),
        "--workers",
        str(workers),
    ]
    print(
        f"\n=== SE calc {cell} {year}-{month:02d} workers={workers} → {out} ===",
        flush=True,
    )
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=_child_env(cell_meta),
        check=False,
    )
    return int(proc.returncode)


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    from scripts.se_calc_test_common import (
        DEFAULT_YEAR,
        DESCRIPTORS_PATH,
        PRIORITIZED_CELLS,
        load_json,
        materialize_cells,
        parse_csv_ids,
        parse_months,
        run_output_dir,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cell", default=None)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--cells", default=",".join(PRIORITIZED_CELLS))
    parser.add_argument("--months", default="1,4,7,10")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="0 = auto max useful (min(CPU, parallel jobs))",
    )
    parser.add_argument(
        "--parallel-jobs",
        type=int,
        default=_DEFAULT_PARALLEL_JOBS,
        help="Expected top-level jobs (refs + scenarios) for auto workers",
    )
    parser.add_argument(
        "--skip-materialize",
        action="store_true",
        help="Reuse existing matrix_descriptors.json",
    )
    args = parser.parse_args(argv)

    workers = (
        args.workers
        if args.workers > 0
        else _max_useful_workers(parallel_jobs=args.parallel_jobs)
    )

    if args.internal:
        if not args.cell or args.month is None or not args.output_dir:
            print("internal mode needs --cell --month --output-dir", file=sys.stderr)
            return 2
        return _run_internal(
            args.cell,
            args.year,
            args.month,
            Path(args.output_dir),
            workers=workers,
        )

    cell_ids = parse_csv_ids(args.cells, PRIORITIZED_CELLS)
    months = parse_months(args.months)
    if args.skip_materialize and DESCRIPTORS_PATH.is_file():
        descriptors = load_json(DESCRIPTORS_PATH)
    else:
        descriptors = materialize_cells(cell_ids)

    print(
        f"SE calc matrix workers={workers} "
        f"(parallel_jobs={args.parallel_jobs}, cpu={os.cpu_count() or 1})",
        flush=True,
    )

    failures: list[str] = []
    for cell_id in cell_ids:
        meta = (descriptors.get("cells") or {}).get(cell_id) or {}
        if meta.get("skipped"):
            print(f"Skip {cell_id}: {meta.get('skip_reason')}")
            continue
        if meta.get("b_gate"):
            failures.append(f"{cell_id}: B-gate True")
            continue
        if not meta.get("house_profiles_path"):
            failures.append(f"{cell_id}: missing materialized paths")
            continue
        for month in months:
            code = _run_cell_month(
                meta,
                cell=cell_id,
                year=args.year,
                month=month,
                workers=workers,
            )
            if code != 0:
                failures.append(f"{cell_id} {args.year}-{month:02d} exit={code}")
            else:
                log = run_output_dir(cell_id, args.year, month) / "backtesting_log.json"
                if not log.is_file():
                    failures.append(f"{cell_id} {args.year}-{month:02d} missing log")

    if failures:
        print("\nFailures:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nAll requested SE calc runs completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run full-year SE for earnie_env_se_m2 (M2 CSV overlays, Live only).

Forces calendar year (stock CLI uses cons_data max year). Uses max useful
ProcessPool workers: min(CPU, parallel jobs). Parallel jobs = refs + scenarios
(~3 for Live-only).

Example:
  set EARNIE_ENV_PATH=earnie_env_se_m2
  python -m scripts.run_se_m2_year
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _max_useful_workers(*, parallel_jobs: int) -> int:
    cpu = os.cpu_count() or 1
    return max(1, min(cpu, max(1, parallel_jobs)))


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-month", type=int, default=12)
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="0 = auto max useful (min(CPU, parallel jobs))",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Default: <EARNIE_ENV_PATH>/runtime",
    )
    parser.add_argument(
        "--parallel-jobs",
        type=int,
        default=3,
        help="Expected top-level jobs (refs + scenarios) for auto workers",
    )
    args = parser.parse_args(argv)

    # Stale se_calc_test cell overlays must not win over the env's house_profiles.
    for key in (
        "EARNIE_HOUSE_PROFILES_PATH",
        "EARNIE_HOUSE_PROFILES_PATH",
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
        "EARNIE_BACKTESTING_SCENARIOS_PATH",
    ):
        os.environ.pop(key, None)

    env_root = Path(
        os.environ.get("EARNIE_ENV_PATH")
        or os.environ.get("EARNIE_ENV_PATH")
        or (ROOT / "earnie_env_se_m2")
    )
    os.environ["EARNIE_ENV_PATH"] = str(env_root)
    os.environ["EARNIE_ENV_PATH"] = str(env_root)
    os.environ.setdefault("EARNIE_OFFLINE", "1")

    out = Path(args.output_dir) if args.output_dir else env_root / "runtime"
    out.mkdir(parents=True, exist_ok=True)

    workers = (
        args.workers
        if args.workers > 0
        else _max_useful_workers(parallel_jobs=args.parallel_jobs)
    )

    import scripts.run_backtesting as rb

    year = int(args.year)
    rb.backtesting_base_year = lambda: year  # type: ignore[assignment]
    rb.BACKTESTING_YEAR = year

    print(
        f"SE M2 year={year} months={args.start_month}-{args.end_month} "
        f"workers={workers} env={env_root} → {out}",
        flush=True,
    )
    sys.argv = [
        "run_backtesting",
        "--start-month",
        str(args.start_month),
        "--end-month",
        str(args.end_month),
        "--output-dir",
        str(out),
        "--workers",
        str(workers),
    ]
    try:
        rb.main()
    except SystemExit as exc:
        if exc.code is None:
            return 0
        return int(exc.code) if isinstance(exc.code, int) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

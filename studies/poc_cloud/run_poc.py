"""Cloud POC runner: offline backtest of a frozen study pack, without Streamlit.

A study directory holds:
  pack/config/        house + scenario configuration
  pack/runtime/       synthetic cons_data.csv (generated when missing)
  cache/open_meteo/   Open-Meteo archive bundles (copied into data/cache/open_meteo)
The price CSV is referenced from ``pack/config/config.json`` (``path_price``).

  python -m studies.poc_cloud.run_poc [--study-dir studies/poc_cloud] [--start-month 1 --end-month 12]

Network is blocked on purpose (dead proxy): a cache miss fails loudly instead of
silently fetching live data. ``--allow-network`` lifts the guard to build caches.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
WEATHER_DST = REPO_ROOT / "data" / "cache" / "open_meteo"
REF_JOBS = 2  # historical + Live reference (see backtesting-max-workers rule)


def _env(pack_dir: Path, *, offline_guard: bool) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "EARNIE_ENV_PATH": str(pack_dir),
            "EARNIE_OFFLINE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    for key in ("EARNIE_CONFIG_PATH", "EARNIE_RUNTIME_PATH", "EARNIE_HOUSE_PROFILES_PATH",
                "EARNIE_BACKTESTING_SCENARIOS_PATH", "EARNIE_COMPONENTS_PATH", "EARNIE_TARIFFS_PATH"):
        env.pop(key, None)
    if offline_guard:
        dead = "http://127.0.0.1:9"
        env.update({"HTTP_PROXY": dead, "HTTPS_PROXY": dead, "http_proxy": dead,
                    "https_proxy": dead, "NO_PROXY": "", "no_proxy": ""})
    return env


def _install_weather_cache(weather_src: Path) -> int:
    if not weather_src.is_dir():
        raise SystemExit(f"Weather cache missing: {weather_src}")
    WEATHER_DST.mkdir(parents=True, exist_ok=True)
    copied = 0
    # The current calendar year is requested as 01-01..(yesterday); alias the frozen
    # partial-year file to that name. Only its January days are used by the study.
    cap = (datetime.now(ZoneInfo("Europe/Vienna")).date() - timedelta(days=1)).isoformat()
    current_year = f"_{cap[:4]}-01-01_"
    for src in sorted(weather_src.glob("*.json")):
        names = [src.name]
        if current_year in src.name:
            head, _, tail = src.name.partition(current_year)
            names.append(f"{head}{current_year}{cap}_{tail.split('_', 1)[1]}")
        for name in names:
            dst = WEATHER_DST / name
            if not dst.exists():
                shutil.copy2(src, dst)
                copied += 1
    return copied


def _run(args: list[str], env: dict[str, str]) -> None:
    print("+", " ".join(args), flush=True)
    result = subprocess.run([sys.executable, *args], cwd=REPO_ROOT, env=env)
    if result.returncode != 0:
        raise SystemExit(f"Step failed ({result.returncode}): {' '.join(args)}")


def _summarize(out_dir: Path) -> dict:
    log = json.loads((out_dir / "backtesting_log.json").read_text(encoding="utf-8"))
    summary = {
        "period": log.get("period"),
        "scenario_ids": log.get("scenario_ids"),
        "reference_id": log.get("reference_id"),
        "labels": log.get("labels"),
        "summary": log.get("summary"),
        "critical_cases_summary": log.get("critical_cases_summary"),
        "cbc_events_summary": log.get("cbc_events_summary"),
        "plausibility": log.get("plausibility"),
        "written_by_app_version": log.get("written_by_app_version"),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return summary


def _job_count(pack_dir: Path) -> int:
    path = pack_dir / "config" / "backtesting_scenarios.json"
    scenarios = json.loads(path.read_text(encoding="utf-8")).get("scenarios", [])
    return REF_JOBS + sum(1 for s in scenarios if s.get("enabled", True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-dir", type=Path, default=STUDY_DIR)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-month", type=int, default=12)
    parser.add_argument("--workers", type=int, default=None,
                        help="Default: min(CPU count, number of parallel jobs).")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--allow-network", action="store_true",
                        help="Disable the offline guard (only for building the caches).")
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="Open-Meteo cache directory (default: <study-dir>/cache/open_meteo).")
    parser.add_argument("--harvest", action="store_true",
                        help="With --allow-network: copy weather files created by this run into --cache-dir.")
    args = parser.parse_args()

    study_dir = args.study_dir.resolve()
    pack_dir = study_dir / "pack"
    out_dir = args.out or study_dir / "results" / "run"
    cache_dir = (args.cache_dir or study_dir / "cache" / "open_meteo").resolve()
    workers = args.workers or min(os.cpu_count() or 1, _job_count(pack_dir))

    env = _env(pack_dir, offline_guard=not args.allow_network)
    if args.harvest:
        cache_dir.mkdir(parents=True, exist_ok=True)
    copied = _install_weather_cache(cache_dir)
    print(f"Weather cache: {copied} file(s) installed into {WEATHER_DST}")
    started_at = time.time()

    if not (pack_dir / "runtime" / "cons_data.csv").is_file():
        _run(["-m", "scripts.generate_cons_data", "--source", "synthetic",
              "--synthetic-start", "2025-01-01", "--synthetic-end", "2025-12-31"], env)

    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    _run(["-m", "scripts.run_backtesting",
          "--start-month", str(args.start_month), "--end-month", str(args.end_month),
          "--workers", str(workers), "--output-dir", str(out_dir)], env)
    summary = _summarize(out_dir)
    if args.harvest:
        harvested = 0
        for src in WEATHER_DST.glob("*.json"):
            if src.stat().st_mtime >= started_at and not (cache_dir / src.name).exists():
                shutil.copy2(src, cache_dir / src.name)
                harvested += 1
        print(f"Harvested {harvested} new weather file(s) into {cache_dir}")
    print(f"\nDone in {time.time() - started:.0f} s -> {out_dir}")
    print(json.dumps(summary.get("summary", {}).get("total_eur"), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

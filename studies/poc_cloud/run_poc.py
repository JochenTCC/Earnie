"""Cloud POC: one house, one scenario, 12 months, fully offline and without Streamlit.

Inputs are frozen in ``studies/poc_cloud/``:
  pack/config/        house + scenario configuration (public example data)
  cache/prices_*.csv  day-ahead prices (fetch_prices.py, one-off online step)
  cache/open_meteo/   Open-Meteo archive bundles (copied into data/cache/open_meteo)

  python -m studies.poc_cloud.run_poc [--start-month 1 --end-month 12] [--workers 3]

Network is blocked on purpose (dead proxy): a cache miss fails loudly instead of
silently fetching live data.
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
PACK_DIR = STUDY_DIR / "pack"
WEATHER_SRC = STUDY_DIR / "cache" / "open_meteo"
WEATHER_DST = REPO_ROOT / "data" / "cache" / "open_meteo"
LIVE_JOBS = 3  # historical + reference + Live scenario (see backtesting-max-workers rule)


def _env(*, offline_guard: bool) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "EARNIE_ENV_PATH": str(PACK_DIR),
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


def _install_weather_cache() -> int:
    if not WEATHER_SRC.is_dir():
        raise SystemExit(f"Weather cache missing: {WEATHER_SRC}")
    WEATHER_DST.mkdir(parents=True, exist_ok=True)
    copied = 0
    # The current calendar year is requested as 01-01..(yesterday); alias the frozen
    # partial-year file to that name. Only its January days are used by the study.
    cap = (datetime.now(ZoneInfo("Europe/Vienna")).date() - timedelta(days=1)).isoformat()
    current_year = f"_{cap[:4]}-01-01_"
    for src in sorted(WEATHER_SRC.glob("*.json")):
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-month", type=int, default=12)
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 1, LIVE_JOBS))
    parser.add_argument("--out", type=Path, default=STUDY_DIR / "results" / "run")
    parser.add_argument("--allow-network", action="store_true",
                        help="Disable the offline guard (only for building the caches).")
    args = parser.parse_args()

    env = _env(offline_guard=not args.allow_network)
    copied = _install_weather_cache()
    print(f"Weather cache: {copied} file(s) installed into {WEATHER_DST}")

    cons_data = PACK_DIR / "runtime" / "cons_data.csv"
    if not cons_data.is_file():
        _run(["-m", "scripts.generate_cons_data", "--source", "synthetic",
              "--synthetic-start", "2025-01-01", "--synthetic-end", "2025-12-31"], env)

    args.out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    _run(["-m", "scripts.run_backtesting",
          "--start-month", str(args.start_month), "--end-month", str(args.end_month),
          "--workers", str(args.workers), "--output-dir", str(args.out)], env)
    summary = _summarize(args.out)
    print(f"\nDone in {time.time() - started:.0f} s -> {args.out}")
    print(json.dumps(summary.get("summary"), indent=2, ensure_ascii=False, default=str)[:1500])


if __name__ == "__main__":
    main()

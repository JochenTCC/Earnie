"""Run the reference ladder L0–L3 over built house packs, several houses at a time.

  python -m studies.viability.run_houses --ids S1,S3 --packs studies/viability/packs --houses-parallel 8 --workers 6
  python -m studies.viability.run_houses --alle --ueberspringen --packs studies/viability/packs_stufe1 --houses-parallel 8 --workers 6

Each house gets ``<packs>/<id>/results/<run>/`` with the SE log, the ladder CSVs of
``scripts.run_reference_ladder`` and its own ``run.log``. References finish quickly, then a house
runs one MILP process per scenario, so more houses use the cores better than more workers per
house. The sensitivity is off by default. Without ``--allow-network`` a missing weather file
fails loud; with it, new files are copied back into the study's cache. ``--ueberspringen`` skips
houses whose run wrote its summary, so a stopped batch continues where it was.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from studies.poc_cloud.run_poc import REPO_ROOT, _env, _harvest_weather_cache, _install_weather_cache

STUDY_DIR = Path(__file__).resolve().parent
WEATHER_CACHE = STUDY_DIR / "cache" / "open_meteo"
DONE_FILE = "reference_ladder_summary.csv"
RUN_SWITCHES = ("EARNIE_SE_LOOKAHEAD_H", "EARNIE_BASE_LEVEL", "EARNIE_PLAN_VENDOR_MODE")


def house_ids(packs: Path, ids: str | None) -> list[str]:
    """The named houses, or all built packs (those with a ``house.json``) if ``ids`` is None."""
    if ids is not None:
        return [house_id.strip() for house_id in ids.split(",")]
    return sorted(path.parent.name for path in packs.glob("*/house.json"))


def is_done(packs: Path, house_id: str, run: str) -> bool:
    return (packs / house_id / "results" / run / DONE_FILE).is_file()


def _run_logged(command: list[str], env: dict[str, str], log) -> None:
    log.write("+ " + " ".join(command) + "\n")
    log.flush()
    result = subprocess.run([sys.executable, *command], cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"Schritt fehlgeschlagen ({result.returncode}): {' '.join(command)}")


def run_house(root: Path, args: argparse.Namespace) -> float:
    pack_dir = root / "pack"
    year = int(json.loads((root / "house.json").read_text(encoding="utf-8"))["preisjahr"])
    env = _env(pack_dir, offline_guard=not args.allow_network, climate_year=year)
    out_dir = root / "results" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "-m", "scripts.run_reference_ladder", "--workers", str(args.workers), "--output-dir", str(out_dir),
        "--start-month", str(args.start_month), "--end-month", str(args.end_month),
        "--skip-historical-reference",
    ]
    if not args.sensitivity:
        command.append("--skip-sensitivity")
    if args.forecast_price_strategy:
        command += ["--forecast-price-strategy", args.forecast_price_strategy]
    else:
        command.append("--skip-forecast")
    started = time.time()
    with open(out_dir / "run.log", "w", encoding="utf-8") as log:
        log.write("Schalter: " + ", ".join(f"{key}={env.get(key, '')}" for key in RUN_SWITCHES) + "\n")
        if not (pack_dir / "runtime" / "cons_data.csv").is_file():
            _run_logged(
                ["-m", "scripts.generate_cons_data", "--source", "synthetic",
                 "--synthetic-start", f"{year}-01-01", "--synthetic-end", f"{year}-12-31"],
                env, log,
            )
        _run_logged(command, env, log)
    return time.time() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--ids", help="Kommagetrennte Haus-IDs")
    which.add_argument("--alle", action="store_true", help="Alle gebauten Pakete unter --packs")
    parser.add_argument("--ueberspringen", action="store_true", help="Haeuser mit fertigem Lauf auslassen")
    parser.add_argument("--packs", type=Path, default=STUDY_DIR / "packs")
    parser.add_argument("--run", default="year", help="Name des Ergebnisordners")
    parser.add_argument("--workers", type=int, required=True, help="Parallele Worker je Haus")
    parser.add_argument("--houses-parallel", type=int, default=1, help="Haeuser gleichzeitig")
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-month", type=int, default=12)
    parser.add_argument("--sensitivity", action="store_true")
    parser.add_argument(
        "--forecast-price-strategy",
        choices=("mirror", "forecast"),
        help="Zweiter Lauf im Forecast-Modus fuer die Untergrenze von L2 - L3; ohne Angabe keiner.",
    )
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()

    WEATHER_CACHE.mkdir(parents=True, exist_ok=True)
    _install_weather_cache(WEATHER_CACHE)
    started_at = time.time()
    ids = house_ids(args.packs, args.ids)
    if not ids:
        raise SystemExit(f"Keine Pakete unter {args.packs}.")
    if args.ueberspringen:
        done = [house_id for house_id in ids if is_done(args.packs, house_id, args.run)]
        ids = [house_id for house_id in ids if house_id not in done]
        print(f"{len(done)} Haeuser schon fertig, {len(ids)} offen.", flush=True)
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=args.houses_parallel) as pool:
        futures = {pool.submit(run_house, args.packs / house_id, args): house_id for house_id in ids}
        for future in as_completed(futures):
            house_id = futures[future]
            try:
                print(f"=== {house_id}: {future.result() / 60.0:.1f} min", flush=True)
            except RuntimeError as exc:
                failed.append(house_id)
                print(f"=== {house_id}: FEHLER {exc}", flush=True)
    if args.allow_network:
        _harvest_weather_cache(WEATHER_CACHE, started_at)
    if failed:
        raise SystemExit(f"Fehlgeschlagen: {', '.join(failed)}")


if __name__ == "__main__":
    main()

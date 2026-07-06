"""Jahres-Backtesting: Spiegelung vs. OLS-Prognose in der grünen Zone (sunset_window)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run_backtesting(
    output_dir: Path,
    *,
    price_strategy: str,
    start_month: int,
    end_month: int,
    workers: int,
    extra_args: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "scripts.run_backtesting",
        "--horizon-mode",
        "sunset_window",
        "--price-strategy",
        price_strategy,
        "--start-month",
        str(start_month),
        "--end-month",
        str(end_month),
        "--workers",
        str(workers),
        "--output-dir",
        str(output_dir),
        "--log-file",
        str(output_dir / f"run_{price_strategy}.log"),
    ]
    cmd.extend(extra_args)
    print(f"\n=== Backtesting price_strategy={price_strategy} → {output_dir} ===")
    subprocess.run(cmd, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Führt zwei sunset_window-Jahresläufe aus (mirror + forecast) "
            "und schreibt einen Vergleichsbericht."
        )
    )
    parser.add_argument("--start-month", type=int, default=1, metavar="MONAT")
    parser.add_argument("--end-month", type=int, default=12, metavar="MONAT")
    parser.add_argument("--workers", type=int, default=1, metavar="N")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("backtesting_logs/price_strategy_compare"),
        help="Basisordner für mirror/, forecast/ und comparison.md",
    )
    parser.add_argument(
        "--comparison-output",
        type=Path,
        default=None,
        help="Markdown-Bericht (Standard: <output-root>/comparison.md)",
    )
    parser.add_argument(
        "--skip-runs",
        action="store_true",
        help="Nur Vergleich aus vorhandenen Logs in output-root/mirror und forecast.",
    )
    parser.add_argument(
        "backtesting_args",
        nargs=argparse.REMAINDER,
        help="Weitere Argumente für run_backtesting (z. B. --feature-dataset …)",
    )
    args = parser.parse_args(argv)
    root = args.output_root
    mirror_dir = root / "mirror"
    forecast_dir = root / "forecast"
    extra = [a for a in args.backtesting_args if a != "--"]

    if not args.skip_runs:
        _run_backtesting(
            mirror_dir,
            price_strategy="mirror",
            start_month=args.start_month,
            end_month=args.end_month,
            workers=args.workers,
            extra_args=extra,
        )
        _run_backtesting(
            forecast_dir,
            price_strategy="forecast",
            start_month=args.start_month,
            end_month=args.end_month,
            workers=args.workers,
            extra_args=extra,
        )

    mirror_json = mirror_dir / "backtesting_log.json"
    forecast_json = forecast_dir / "backtesting_log.json"
    if not mirror_json.is_file() or not forecast_json.is_file():
        raise SystemExit(
            f"Erwarte {mirror_json} und {forecast_json}. "
            "Ohne --skip-runs fehlgeschlagen oder Pfade prüfen."
        )

    comparison_path = args.comparison_output or (root / "comparison.md")
    compare_cmd = [
        sys.executable,
        "-m",
        "scripts.compare_price_strategy_backtests",
        str(mirror_json),
        str(forecast_json),
        "-o",
        str(comparison_path),
        "--mirror-hourly",
        str(mirror_dir / "backtesting_hourly.csv"),
        "--forecast-hourly",
        str(forecast_dir / "backtesting_hourly.csv"),
    ]
    subprocess.run(compare_cmd, check=True)
    print(f"\nFertig. Vergleich: {comparison_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

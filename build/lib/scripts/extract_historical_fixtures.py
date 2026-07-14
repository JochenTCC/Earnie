#!/usr/bin/env python3
"""Kopiert runtime/cons_data_hourly.csv nach tests/fixtures/historical/."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "runtime" / "cons_data_hourly.csv"
DEFAULT_TARGET = REPO_ROOT / "tests" / "fixtures" / "historical" / "cons_data_hourly.csv"


def extract(source: Path, target: Path) -> int:
    if not source.is_file():
        raise FileNotFoundError(
            f"Quelldatei fehlt: {source}. "
            "Bitte zuerst python -m scripts.generate_cons_data --source loxone ausführen."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    line_count = sum(1 for _ in target.open(encoding="utf-8")) - 1
    return line_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    rows = extract(args.source, args.target)
    print(f"{rows} Datenzeilen nach {args.target} kopiert.")


if __name__ == "__main__":
    main()

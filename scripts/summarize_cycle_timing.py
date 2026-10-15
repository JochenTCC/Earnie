"""Summarize ``runtime/timing/cycles.jsonl`` from a live profiling window.

Usage::

    python -m scripts.summarize_cycle_timing path/to/cycles.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def _load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(rows: list[dict]) -> str:
    if not rows:
        return "No cycles in file."
    by_phase: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        phases = row.get("phases_sec") or {}
        if not isinstance(phases, dict):
            continue
        for name, sec in phases.items():
            try:
                by_phase[str(name)].append(float(sec))
            except (TypeError, ValueError):
                continue
    lines = [f"Cycles: {len(rows)}", ""]
    ranked = sorted(
        by_phase.items(),
        key=lambda item: _mean(item[1]),
        reverse=True,
    )
    lines.append(f"{'phase':<22} {'n':>4} {'mean_s':>10} {'max_s':>10} {'pct_total':>10}")
    total_mean = _mean(by_phase.get("total") or [])
    for name, values in ranked:
        mean_s = _mean(values)
        pct = (100.0 * mean_s / total_mean) if total_mean > 0 and name != "total" else (
            100.0 if name == "total" and total_mean > 0 else 0.0
        )
        lines.append(
            f"{name:<22} {len(values):>4} {mean_s:>10.3f} {max(values):>10.3f} {pct:>9.1f}%"
        )
    lines.append("")
    lines.append("Acceleration candidates: phases with high mean_s below total "
                 "(often milp_live / savings / savings_optimized).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "jsonl",
        type=Path,
        help="Path to cycles.jsonl (from earnie_env/runtime/timing/)",
    )
    args = parser.parse_args(argv)
    if not args.jsonl.is_file():
        print(f"File not found: {args.jsonl}", file=sys.stderr)
        return 1
    print(summarize(_load_rows(args.jsonl)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

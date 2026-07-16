#!/usr/bin/env python3
"""Partial replay / validation for unified debug-dump ZIPs (chart + prod)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from runtime_store.debug_dump_archive import (
    DUMP_TYPE_CHART,
    DUMP_TYPE_PROD,
    DUMP_TYPES,
    extract_dump_to_dir,
    validate_dump_layout,
)


def _configure_console_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name} line {line_no}: {exc}") from exc
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _replay_chart(root: Path, manifest: dict[str, Any], *, html_out: Path | None) -> int:
    chart = manifest.get("chart") or {}
    display_rows = chart.get("display_rows") or []
    if not display_rows:
        print("FAIL: chart.display_rows missing or empty")
        return 1
    display_df = pd.DataFrame(display_rows)
    baseline_rows = chart.get("baseline_rows") or []
    baseline_df = pd.DataFrame(baseline_rows) if baseline_rows else None
    matched_rows = chart.get("matched_baseline_rows") or []
    matched_df = pd.DataFrame(matched_rows) if matched_rows else None

    from ui.charts import build_power_soc_chart_figure

    qualities = chart.get("chart_qualities")
    slot_qualities = tuple(qualities) if qualities else None
    fig = build_power_soc_chart_figure(
        display_df,
        baseline_df,
        matched_df,
        history_slot_count=chart.get("history_slot_count"),
        chart_header_label=chart.get("chart_header_label"),
        slot_qualities=slot_qualities,
        battery_params=chart.get("battery_params"),
    )
    window_path = root / "runtime" / "optimization_history_window.jsonl"
    window_entries = _load_jsonl(window_path)
    plotly = chart.get("chart1_plotly")
    print(
        "OK chart replay: "
        f"display_rows={len(display_rows)} "
        f"history_window_entries={len(window_entries)} "
        f"chart1_plotly={'yes' if plotly else 'no'} "
        f"traces={len(fig.data)}"
    )
    if html_out is not None:
        html_out.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(html_out), include_plotlyjs="cdn")
        print(f"Wrote Chart 1 HTML: {html_out}")
    return 0


def _replay_prod(root: Path, manifest: dict[str, Any]) -> int:
    history_path = root / "runtime" / "optimization_history.jsonl"
    # Fixture promotion / extracted flat layout may place history at root.
    if not history_path.is_file():
        alt = root / "optimization_history.jsonl"
        if alt.is_file():
            history_path = alt
    entries = _load_jsonl(history_path)
    if not entries:
        print("FAIL: optimization_history.jsonl empty or unreadable")
        return 1
    prod = manifest.get("prod") or {}
    state_names = (
        "flexible_consumers_state.json",
        "optimizer_run_state.json",
        "live_optimization_debug.json",
        "pv_counter_state.json",
    )
    present = []
    for name in state_names:
        for candidate in (root / "runtime" / name, root / name):
            if candidate.is_file():
                present.append(name)
                break
    print(
        "OK prod replay: "
        f"history_entries={len(entries)} "
        f"title={prod.get('title')!r} "
        f"symptom={prod.get('symptom')!r} "
        f"state_files={present}"
    )
    return 0


def replay_debug_dump(
    source: Path,
    *,
    dump_type: str | None = None,
    html_out: Path | None = None,
    keep_extract: Path | None = None,
) -> int:
    root = extract_dump_to_dir(source, target=keep_extract)
    manifest = validate_dump_layout(root, dump_type=dump_type)
    resolved = dump_type or manifest["dump_type"]
    print(
        f"Dump root={root} schema_version={manifest.get('schema_version')} "
        f"dump_type={resolved} app_version={manifest.get('app_version')}"
    )
    if resolved == DUMP_TYPE_CHART:
        return _replay_chart(root, manifest, html_out=html_out)
    if resolved == DUMP_TYPE_PROD:
        return _replay_prod(root, manifest)
    print(f"FAIL: unsupported dump_type {resolved!r}")
    return 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and partially replay a debug-dump ZIP or directory",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to debug_dump_*.zip or extracted dump directory",
    )
    parser.add_argument(
        "--dump-type",
        choices=DUMP_TYPES,
        default=None,
        help="Override dump_type from manifest",
    )
    parser.add_argument(
        "--html-out",
        type=Path,
        default=None,
        help="Optional Chart 1 HTML output (chart dumps only)",
    )
    parser.add_argument(
        "--extract-dir",
        type=Path,
        default=None,
        help="Extract ZIP into this directory instead of a temp dir",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_console_utf8()
    args = _parse_args(argv)
    try:
        return replay_debug_dump(
            args.source,
            dump_type=args.dump_type,
            html_out=args.html_out,
            keep_extract=args.extract_dir,
        )
    except (OSError, ValueError, FileNotFoundError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

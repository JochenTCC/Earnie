"""Shared helpers for Szenario-Explorer backtesting progress (CLI + Streamlit UI)."""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TypeVar

from simulation.engine import (
    HISTORICAL_REFERENCE_ID,
    scenario_reference_id,
    scenario_reference_label,
)

_SCENARIO_REFERENCE_SUFFIX = " — ohne Optimierung"

T = TypeVar("T")


def ordered_backtesting_result_ids(
    scenarios: Mapping[str, object],
    *,
    live_scenario_id: str,
    extra_ref_ids: Iterable[str],
    historical_id: str = HISTORICAL_REFERENCE_ID,
) -> list[str]:
    """
    Canonical SE result order:

    historical → Live ref → other refs → Live optimized → other optimized.
    """
    extra = list(dict.fromkeys(extra_ref_ids))
    ordered: list[str] = [historical_id]
    live_ref = (
        scenario_reference_id(live_scenario_id) if live_scenario_id else None
    )
    if live_ref and live_ref in extra:
        ordered.append(live_ref)
    for rid in extra:
        if rid not in ordered:
            ordered.append(rid)
    if live_scenario_id and live_scenario_id in scenarios:
        ordered.append(live_scenario_id)
    for sid in scenarios:
        if sid not in ordered:
            ordered.append(sid)
    return ordered


def ordered_progress_labels(
    ordered_ids: Iterable[str],
    labels: Mapping[str, str],
) -> list[str]:
    """Map canonical result ids to display labels (stable order)."""
    return [labels.get(rid, rid) for rid in ordered_ids]


def reorder_results_by_ids(
    results: Mapping[str, T],
    ordered_ids: Iterable[str],
) -> dict[str, T]:
    """Rebuild a results mapping in canonical id order; unknowns append last."""
    ordered: dict[str, T] = {}
    for rid in ordered_ids:
        if rid in results:
            ordered[rid] = results[rid]
    for rid, value in results.items():
        if rid not in ordered:
            ordered[rid] = value
    return ordered


def sort_progress_snapshot_keys(
    labels: Iterable[str],
    *,
    historical_reference_label: str | None = None,
    live_scenario_label: str | None = None,
    preferred_order: list[str] | None = None,
) -> list[str]:
    """Sort progress bar labels by preferred_order, else legacy Live-first ranks."""
    present = list(dict.fromkeys(labels))
    if preferred_order is not None:
        order_index = {lab: i for i, lab in enumerate(preferred_order)}
        unknown = len(preferred_order)

        def preferred_rank(label: str) -> tuple[int, str]:
            return (order_index.get(label, unknown), label)

        return sorted(present, key=preferred_rank)

    hist = historical_reference_label or ""
    live_reference_label = (
        scenario_reference_label(live_scenario_label)
        if live_scenario_label
        else ""
    )

    def rank(label: str) -> tuple[int, str]:
        if hist and label == hist:
            return (0, label)
        if live_reference_label and label == live_reference_label:
            return (1, label)
        if (
            label.startswith("Referenz (")
            and label.endswith(_SCENARIO_REFERENCE_SUFFIX)
        ):
            return (2, label)
        if live_scenario_label and label == live_scenario_label:
            return (3, label)
        return (4, label)

    return sorted(present, key=rank)


def resolve_progress_dir(progress_path: str | None) -> Path | None:
    """Directory for per-worker JSON snapshots; legacy *.json paths map to a sibling folder."""
    if not progress_path:
        return None
    path = Path(progress_path)
    if path.suffix.lower() == ".json":
        return path.parent / ".backtesting_workers"
    return path


def worker_progress_path(progress_path: str | None, worker_key: str) -> str | None:
    progress_dir = resolve_progress_dir(progress_path)
    if progress_dir is None:
        return None
    safe = re.sub(r"[^\w\-]+", "_", str(worker_key)).strip("_") or "worker"
    return str(progress_dir / f"{safe}.json")


def prepare_progress_dir(progress_path: str | None) -> None:
    progress_dir = resolve_progress_dir(progress_path)
    if progress_dir is None:
        return
    if progress_dir.is_dir():
        for child in progress_dir.glob("*.json"):
            child.unlink(missing_ok=True)
    progress_dir.mkdir(parents=True, exist_ok=True)


def clear_progress_dir(progress_path: str | None) -> None:
    progress_dir = resolve_progress_dir(progress_path)
    if progress_dir is None:
        return
    if progress_dir.is_dir():
        for child in progress_dir.glob("*.json"):
            child.unlink(missing_ok=True)


def read_progress_file(path: str) -> dict | None:
    progress_path = Path(path)
    if not progress_path.is_file():
        return None
    try:
        return json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_progress_snapshot(progress_path: str) -> dict[str, dict]:
    """All worker progress entries keyed by scenario label."""
    path = Path(progress_path)
    if path.suffix.lower() == ".json" and path.is_file():
        payload = read_progress_file(str(path))
        if payload is None:
            return {}
        key = str(payload.get("scenario") or "active")
        return {key: payload}

    progress_dir = resolve_progress_dir(progress_path)
    if progress_dir is None or not progress_dir.is_dir():
        return {}

    snapshot: dict[str, dict] = {}
    for file_path in sorted(progress_dir.glob("*.json")):
        payload = read_progress_file(str(file_path))
        if payload is None:
            continue
        key = str(payload.get("scenario") or file_path.stem)
        snapshot[key] = payload
    return snapshot

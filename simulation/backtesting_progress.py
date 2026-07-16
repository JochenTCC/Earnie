"""Shared helpers for Szenario-Explorer backtesting progress (CLI + Streamlit UI)."""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from simulation.engine import scenario_reference_label

_SCENARIO_REFERENCE_SUFFIX = " — ohne Optimierung"


def sort_progress_snapshot_keys(
    labels: Iterable[str],
    *,
    historical_reference_label: str,
    live_scenario_label: str,
) -> list[str]:
    """UI order: historical ref, live ref, other refs, then optimized scenarios."""
    live_reference_label = scenario_reference_label(live_scenario_label)

    def rank(label: str) -> tuple[int, str]:
        if label == historical_reference_label:
            return (0, label)
        if label == live_reference_label:
            return (1, label)
        if (
            label.startswith("Referenz (")
            and label.endswith(_SCENARIO_REFERENCE_SUFFIX)
        ):
            return (2, label)
        return (3, label)

    return sorted(labels, key=rank)


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

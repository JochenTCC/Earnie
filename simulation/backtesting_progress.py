"""Shared helpers for Szenario-Explorer backtesting progress (CLI + Streamlit UI)."""
from __future__ import annotations

import json
import math
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
_ETA_MIN_ELAPSED_SEC = 5.0

T = TypeVar("T")


def progress_entry_key(payload: Mapping[str, object], *, fallback: str = "active") -> str:
    """Stable snapshot key: prefer result_id, else scenario label / fallback."""
    result_id = payload.get("result_id")
    if result_id is not None and str(result_id).strip():
        return str(result_id)
    scenario = payload.get("scenario")
    if scenario is not None and str(scenario).strip():
        return str(scenario)
    return fallback


def estimate_remaining_seconds(
    *,
    current: int,
    total: int,
    delta_current: int,
    delta_t_sec: float,
    min_elapsed_sec: float = _ETA_MIN_ELAPSED_SEC,
) -> float | None:
    """Estimate seconds left from recent hour progress; None if not yet reliable."""
    if total <= 0 or current <= 0 or current >= total:
        return None
    if delta_current <= 0 or delta_t_sec < min_elapsed_sec:
        return None
    rate = delta_current / delta_t_sec
    if rate <= 0 or not math.isfinite(rate):
        return None
    remaining = (total - current) / rate
    if remaining < 0 or not math.isfinite(remaining):
        return None
    return remaining


def format_eta_caption(seconds: float | None) -> str | None:
    """German short ETA fragment, e.g. 'noch ~8 Min'. None if unavailable."""
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return None
    if seconds < 60:
        return f"noch ~{max(1, int(round(seconds)))}s"
    minutes = int(round(seconds / 60.0))
    if minutes < 60:
        return f"noch ~{minutes} Min"
    hours, rem_min = divmod(minutes, 60)
    if rem_min == 0:
        return f"noch ~{hours} Std"
    return f"noch ~{hours} Std {rem_min} Min"


def build_progress_display_rows(
    preferred_ids: Iterable[str],
    snapshot: Mapping[str, Mapping[str, object]],
    labels: Mapping[str, str],
) -> list[dict]:
    """
    Fixed-order progress rows for preferred result ids.

    Missing snapshot entries become placeholders (Wartend…, progress 0).
    """
    rows: list[dict] = []
    for result_id in preferred_ids:
        progress = snapshot.get(result_id)
        label = labels.get(result_id, result_id)
        if progress is None:
            rows.append(
                {
                    "result_id": result_id,
                    "label": label,
                    "current": 0,
                    "total": 0,
                    "phase": "",
                    "placeholder": True,
                }
            )
            continue
        rows.append(
            {
                "result_id": result_id,
                "label": str(progress.get("scenario") or label),
                "current": int(progress.get("current") or 0),
                "total": int(progress.get("total") or 0),
                "phase": str(progress.get("phase") or ""),
                "placeholder": False,
            }
        )
    return rows


def format_progress_bar_caption(
    *,
    label: str,
    current: int,
    total: int,
    phase: str,
    placeholder: bool,
    eta_seconds: float | None = None,
) -> str:
    """Caption text for one SE progress bar (hours + optional ETA)."""
    if placeholder or total <= 0:
        return f"{label} — Wartend…"
    eta = format_eta_caption(eta_seconds)
    if phase == "reference":
        base = f"{label} — Referenz"
    else:
        base = f"{label} — {current}/{total} h"
    if eta:
        return f"{base} · {eta}"
    return base


class ProgressEtaTracker:
    """Per-task ETA from monotonic samples of current/total hours."""

    def __init__(self, *, min_elapsed_sec: float = _ETA_MIN_ELAPSED_SEC) -> None:
        self._min_elapsed_sec = min_elapsed_sec
        self._samples: dict[str, tuple[int, float]] = {}
        self._eta: dict[str, float] = {}
        self._eta_at: dict[str, float] = {}

    def update(
        self,
        result_id: str,
        *,
        current: int,
        total: int,
        now_monotonic: float,
    ) -> float | None:
        if total <= 0 or current >= total:
            self._eta.pop(result_id, None)
            self._eta_at.pop(result_id, None)
            self._samples[result_id] = (current, now_monotonic)
            return None

        prev = self._samples.get(result_id)
        if prev is None:
            self._samples[result_id] = (current, now_monotonic)
            return None

        prev_current, prev_t = prev
        if current < prev_current:
            self._samples[result_id] = (current, now_monotonic)
            self._eta.pop(result_id, None)
            self._eta_at.pop(result_id, None)
            return None

        if current > prev_current:
            eta = estimate_remaining_seconds(
                current=current,
                total=total,
                delta_current=current - prev_current,
                delta_t_sec=now_monotonic - prev_t,
                min_elapsed_sec=self._min_elapsed_sec,
            )
            if eta is not None:
                self._samples[result_id] = (current, now_monotonic)
                self._eta[result_id] = eta
                self._eta_at[result_id] = now_monotonic
            # else: keep anchor so elapsed time can accumulate across fast steps

        stored = self._eta.get(result_id)
        stored_at = self._eta_at.get(result_id)
        if stored is None or stored_at is None:
            return None
        return max(0.0, stored - (now_monotonic - stored_at))


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
    """All worker progress entries keyed by result_id (fallback: scenario label)."""
    path = Path(progress_path)
    if path.suffix.lower() == ".json" and path.is_file():
        payload = read_progress_file(str(path))
        if payload is None:
            return {}
        return {progress_entry_key(payload): payload}

    progress_dir = resolve_progress_dir(progress_path)
    if progress_dir is None or not progress_dir.is_dir():
        return {}

    snapshot: dict[str, dict] = {}
    for file_path in sorted(progress_dir.glob("*.json")):
        payload = read_progress_file(str(file_path))
        if payload is None:
            continue
        key = progress_entry_key(payload, fallback=file_path.stem)
        snapshot[key] = payload
    return snapshot

"""Live month peak of grid import for the capacity charge (max-power tariff P5).

One entry per calendar month in the house's local time (the host clock, as the sampler uses it):
the highest quarter-hour import, its slot and source, and how much of the month was measured.
A month without an entry is unknown, never 0. The value is Earnie's own measurement and can be
lower than the meter's (window offset, clock, missing quarter hours).

The import cap's observe mode (plan P6d, decision O3) keeps a second file of the same shape with
the hypothetical peak (``capacity_peaks_observe.json``): measured import plus what the plan with
the cap would have changed, recorded through ``record_slot``. A third file
(``capacity_peaks_observe_measured.json``) keeps the measured import of exactly those quarter
hours, so the saving compares two peaks of one period.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from optimizer.schedule import QUARTER_HOUR_MINUTES
from runtime_store.file_metadata import stamp_payload, strip_metadata
from runtime_store.persist_paths import (
    capacity_observe_baseline_file,
    capacity_observe_peak_file,
    capacity_peak_store_file,
)
from runtime_store.power_interval_sampler import (
    GRID_IMPORT_SOURCE_MEAN,
    MIN_IMPORT_WINDOW_SEC,
    MIN_SAMPLE_COUNT_FOR_MEAN,
)

logger = logging.getLogger(__name__)

_SCHEMA = 1
_SLOT = timedelta(minutes=QUARTER_HOUR_MINUTES)


@dataclass(frozen=True)
class MonthPeak:
    """``first_slot``: measured since; quarter hours before it in the month are not known."""

    month: str
    peak_kw: float
    peak_slot: str
    peak_source: str
    first_slot: str
    last_slot: str
    slots_logged: int
    slots_missing: int


def _path(path: str | None) -> str:
    return path or capacity_peak_store_file()


def _load(path: str) -> dict[str, Any]:
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return {}
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or not isinstance(raw.get("months", {}), dict):
        raise ValueError(f"capacity_peak_store: {path} has no months object")
    return dict(strip_metadata(raw).get("months") or {})


def _save(path: str, months: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(stamp_payload({"months": months}, schema_version=_SCHEMA), handle, indent=2)
    os.replace(tmp, path)


def _slot(value: Any) -> datetime:
    moment = datetime.fromisoformat(str(value))
    return moment.replace(tzinfo=None) if moment.tzinfo else moment


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def measured_import_kw(closed: dict[str, Any]) -> float | None:
    """Import of the slot, or ``None`` when a sample mean covers too little of it to count.

    A mean needs at least ``MIN_SAMPLE_COUNT_FOR_MEAN`` samples over ``MIN_IMPORT_WINDOW_SEC``,
    the same window a counter needs: after a restart late in the slot, three samples from its
    last minute would otherwise mark the whole quarter hour as measured.
    """
    if "grid_import_kw" not in closed or "grid_import_source" not in closed:
        raise ValueError(
            f"capacity_peak_store: closed interval {closed.get('interval_start')} has no grid import"
        )
    if closed["grid_import_source"] == GRID_IMPORT_SOURCE_MEAN:
        if int(closed.get("sample_count") or 0) < MIN_SAMPLE_COUNT_FOR_MEAN:
            return None
        window = _slot(closed["grid_import_end"]) - _slot(closed["grid_import_start"])
        if window.total_seconds() < MIN_IMPORT_WINDOW_SEC:
            return None
    return float(closed["grid_import_kw"])


def record_closed_interval(closed: dict[str, Any], *, path: str | None = None) -> MonthPeak | None:
    """Add one closed quarter hour; returns the month after it, ``None`` if nothing was stored.

    A slot that was not measured well enough counts as missing. A slot at or before the last
    one stored is ignored (logged), so a clock step backwards cannot rewrite a month.
    """
    return record_slot(
        closed["interval_start"],
        measured_import_kw(closed),
        str(closed["grid_import_source"]),
        path=path,
    )


def observe_path() -> str:
    """The observe mode's file of hypothetical month peaks."""
    return capacity_observe_peak_file()


def observe_baseline_path() -> str:
    """The observe mode's file of measured month peaks over the same quarter hours."""
    return capacity_observe_baseline_file()


def record_slot(
    interval_start: Any, kw: float | None, source: str, *, path: str | None = None
) -> MonthPeak | None:
    """Add one quarter hour with its import ``kw`` (``None``: missing) from ``source``.

    Same rules as ``record_closed_interval``; the observe mode records its hypothetical import
    through here with ``path=observe_path()``.
    """
    target = _path(path)
    slot = _slot(interval_start)
    month = slot.strftime("%Y-%m")
    months = _load(target)
    entry = months.get(month)
    if entry is not None and _slot(entry["last_slot"]) >= slot:
        logger.warning(
            "capacity_peak_store: slot %s not after the last stored %s — ignored.",
            _iso(slot),
            entry["last_slot"],
        )
        return MonthPeak(month=month, **entry)
    if entry is None:
        if kw is None:
            return None
        entry = {
            "peak_kw": kw,
            "peak_slot": _iso(slot),
            "peak_source": source,
            "first_slot": _iso(slot),
            "last_slot": _iso(slot),
            "slots_logged": 1,
            "slots_missing": 0,
        }
    else:
        skipped = int((slot - _slot(entry["last_slot"])) / _SLOT) - 1
        entry = {
            **entry,
            "last_slot": _iso(slot),
            "slots_logged": entry["slots_logged"] + (kw is not None),
            "slots_missing": entry["slots_missing"] + max(skipped, 0) + (kw is None),
        }
        if kw is not None and kw > float(entry["peak_kw"]):
            entry.update(
                peak_kw=kw,
                peak_slot=_iso(slot),
                peak_source=source,
            )
    months[month] = entry
    _save(target, months)
    return MonthPeak(month=month, **entry)


def month_peak(month: str, *, path: str | None = None) -> MonthPeak | None:
    """The stored month (``YYYY-MM``); ``None`` means unknown, not 0."""
    entry = _load(_path(path)).get(month)
    return None if entry is None else MonthPeak(month=month, **entry)

"""Live month peak of grid import for the capacity charge (max-power tariff P5).

One entry per calendar month in the house's local time (the host clock, as the sampler uses it):
the highest quarter-hour import, its slot and source, and how much of the month was measured.
A month without an entry is unknown, never 0. The value is Earnie's own measurement and can be
lower than the meter's (window offset, clock, missing quarter hours).
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
from runtime_store.persist_paths import capacity_peak_store_file
from runtime_store.power_interval_sampler import (
    GRID_IMPORT_SOURCE_MEAN,
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


def _measured_kw(closed: dict[str, Any]) -> float | None:
    """Import of the slot, or ``None`` when a sample mean rests on too few samples to count."""
    if "grid_import_kw" not in closed or "grid_import_source" not in closed:
        raise ValueError(
            f"capacity_peak_store: closed interval {closed.get('interval_start')} has no grid import"
        )
    if (
        closed["grid_import_source"] == GRID_IMPORT_SOURCE_MEAN
        and int(closed.get("sample_count") or 0) < MIN_SAMPLE_COUNT_FOR_MEAN
    ):
        return None
    return float(closed["grid_import_kw"])


def record_closed_interval(closed: dict[str, Any], *, path: str | None = None) -> MonthPeak | None:
    """Add one closed quarter hour; returns the month after it, ``None`` if nothing was stored.

    A slot that was not measured well enough counts as missing. A slot at or before the last
    one stored is ignored (logged), so a clock step backwards cannot rewrite a month.
    """
    target = _path(path)
    slot = _slot(closed["interval_start"])
    kw = _measured_kw(closed)
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
            "peak_source": str(closed["grid_import_source"]),
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
                peak_source=str(closed["grid_import_source"]),
            )
    months[month] = entry
    _save(target, months)
    return MonthPeak(month=month, **entry)


def month_peak(month: str, *, path: str | None = None) -> MonthPeak | None:
    """The stored month (``YYYY-MM``); ``None`` means unknown, not 0."""
    entry = _load(_path(path)).get(month)
    return None if entry is None else MonthPeak(month=month, **entry)

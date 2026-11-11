"""Live import cap report (max-power tariff P6a): the latest plan's report and measured overshoots.

``plan`` is the report of the latest Live cycle (``optimizer.import_cap_report``). ``measured``
lists, per month, closed quarter hours whose measured import lay above the cap or the month's
peak before them, whichever is higher, with the cause: the plan's own cause when the plan already
had that slot over its limit, ``forecast`` when the plan held, ``not_planned`` when no plan held
the cap, ``none_detected`` when the plan of that slot is not known. Only the current and the
previous month are kept.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from optimizer.import_cap_report import (
    CAUSE_FORECAST,
    CAUSE_NONE,
    CAUSE_NOT_PLANNED,
    REPORT_SCHEMA,
    SLACK_TOLERANCE_KW,
)
from runtime_store.file_metadata import stamp_payload, strip_metadata
from runtime_store.persist_paths import import_cap_report_file

_KEEP_MONTHS = 2


def _path(path: str | None) -> str:
    return path or import_cap_report_file()


def load(path: str | None = None) -> dict[str, Any]:
    """``{"plan": report | None, "measured": {month: [event, ...]}}``; empty without a file."""
    target = _path(path)
    if not os.path.isfile(target) or os.path.getsize(target) == 0:
        return {"plan": None, "measured": {}}
    with open(target, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or not isinstance(raw.get("measured", {}), dict):
        raise ValueError(f"import_cap_report_store: {target} has no measured object")
    data = strip_metadata(raw)
    return {"plan": data.get("plan"), "measured": dict(data.get("measured") or {})}


def _save(data: dict[str, Any], path: str | None) -> None:
    target = _path(path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{target}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(stamp_payload(data, schema_version=REPORT_SCHEMA), handle, indent=2)
    os.replace(tmp, target)


def save_plan_report(report: dict[str, Any] | None, *, path: str | None = None) -> None:
    """Store the latest cycle's report. ``None`` (no cap) only clears an existing report."""
    target = _path(path)
    if report is None and not os.path.isfile(target):
        return
    data = load(target)
    if report is None and data["plan"] is None:
        return
    data["plan"] = report
    _save(data, target)


def _slot(value: Any) -> datetime:
    moment = datetime.fromisoformat(str(value))
    return moment.replace(tzinfo=None) if moment.tzinfo else moment


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="minutes")


def _cause_from_plan(plan: dict[str, Any] | None, slot: str) -> tuple[str, bool]:
    """Cause of a measured overshoot from the plan of that slot, and whether the plan had it."""
    if not plan or plan.get("first_slot") != slot:
        return CAUSE_NONE, False
    if not plan.get("planned"):
        return CAUSE_NOT_PLANNED, False
    for entry in plan.get("slots") or []:
        if entry.get("slot") == slot:
            return str(entry["cause"]), True
    return CAUSE_FORECAST, False


def record_measured(
    interval_start: Any,
    import_kw: float | None,
    *,
    params: dict | None,
    peak_before_kw: float | None,
    path: str | None = None,
) -> dict[str, Any] | None:
    """Check one closed quarter hour against the cap; returns the event, ``None`` when within.

    ``params``: the resolved Live scenario. ``peak_before_kw``: the month's stored peak before
    this quarter hour, ``None`` when the month is unknown (then the cap alone is the threshold).
    ``import_kw`` ``None`` (not measured well enough) is never an overshoot.
    """
    from house_config.import_cap import parse_import_cap
    from optimizer.import_power_limit import import_caps_from_params

    if import_kw is None:
        return None
    cap = parse_import_cap(params)
    if cap is None:
        return None
    slot = _slot(interval_start)
    month = f"{slot:%Y-%m}"
    peaks = {} if peak_before_kw is None else {month: float(peak_before_kw)}
    caps = import_caps_from_params(params, [slot], peaks)
    if caps is None:
        return None
    threshold_kw = float(caps.limits_kw[0]) + cap.margin_kw
    over_kw = float(import_kw) - threshold_kw
    if over_kw <= SLACK_TOLERANCE_KW:
        return None
    target = _path(path)
    data = load(target)
    slot_iso = _iso(slot)
    cause, planned = _cause_from_plan(data["plan"], slot_iso)
    event = {
        "slot": slot_iso,
        "import_kw": round(float(import_kw), 3),
        "threshold_kw": round(threshold_kw, 3),
        "over_kw": round(over_kw, 3),
        "cause": cause,
        "planned": planned,
    }
    measured = data["measured"]
    events = [e for e in measured.get(month, []) if e.get("slot") != slot_iso]
    measured[month] = sorted([*events, event], key=lambda e: e["slot"])
    for old in sorted(measured)[:-_KEEP_MONTHS]:
        del measured[old]
    _save(data, target)
    return event

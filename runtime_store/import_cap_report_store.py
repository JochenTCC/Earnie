"""Live import cap report (max-power tariff P6a): the latest plan's report and measured overshoots.

``plan`` is the report of the latest Live cycle (``optimizer.import_cap_report``). ``measured``
lists, per month, closed quarter hours whose measured import lay above the cap or the month's
peak before them, whichever is higher, with the cause: the plan's own cause when the plan already
had that slot over its limit, ``forecast`` when the plan held, ``not_planned`` when no plan held
the cap, ``none_detected`` when the plan of that slot is not known. Only the current and the
previous month are kept.

Observe mode (plan P6d, decision O3): ``record_observed`` turns each closed quarter hour into a
hypothetical one, measured import plus ``delta_import_kw`` of the report whose slot 0 it was,
records that in the hypothetical peak store (and the measured import of the same quarter hour in
the baseline store, so the saving compares one period), keeps the quarter hours where the plan with the cap
would have acted differently under ``interventions``, and checks the hypothetical import like a
measured one (event with ``hypothetical: true`` and the measured value beside it).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from house_config.import_cap import MODE_OBSERVE
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
OBSERVE_PEAK_SOURCE = "measured_plus_plan_delta"
OBSERVE_BASELINE_SOURCE = "measured_while_observed"


def _path(path: str | None) -> str:
    return path or import_cap_report_file()


def load(path: str | None = None) -> dict[str, Any]:
    """``{"plan": report | None, "measured": {month: [event, ...]}, "interventions": {...}}``.

    Empty without a file. ``interventions`` (observe mode) has the same shape as ``measured``.
    """
    target = _path(path)
    if not os.path.isfile(target) or os.path.getsize(target) == 0:
        return {"plan": None, "measured": {}, "interventions": {}}
    with open(target, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or not isinstance(raw.get("measured", {}), dict):
        raise ValueError(f"import_cap_report_store: {target} has no measured object")
    if not isinstance(raw.get("interventions", {}), dict):
        raise ValueError(f"import_cap_report_store: {target} has no interventions object")
    data = strip_metadata(raw)
    return {
        "plan": data.get("plan"),
        "measured": dict(data.get("measured") or {}),
        "interventions": dict(data.get("interventions") or {}),
    }


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


def _add_by_month(store: dict[str, list], month: str, entry: dict[str, Any]) -> None:
    """Replace the entry of the same slot, keep slots sorted and only the latest months."""
    entries = [e for e in store.get(month, []) if e.get("slot") != entry["slot"]]
    store[month] = sorted([*entries, entry], key=lambda e: e["slot"])
    for old in sorted(store)[:-_KEEP_MONTHS]:
        del store[old]


def record_measured(
    interval_start: Any,
    import_kw: float | None,
    *,
    params: dict | None,
    peak_before_kw: float | None,
    path: str | None = None,
    measured_kw: float | None = None,
) -> dict[str, Any] | None:
    """Check one closed quarter hour against the cap; returns the event, ``None`` when within.

    ``params``: the resolved Live scenario. ``peak_before_kw``: the month's stored peak before
    this quarter hour, ``None`` when the month is unknown (then the cap alone is the threshold).
    ``import_kw`` ``None`` (not measured well enough) is never an overshoot. ``measured_kw``:
    observe mode only, ``import_kw`` is then the hypothetical import and this the metered one.
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
    if measured_kw is not None:
        event["hypothetical"] = True
        event["measured_kw"] = round(float(measured_kw), 3)
    _add_by_month(data["measured"], month, event)
    _save(data, target)
    return event


def _observe_block_of(plan: dict[str, Any] | None, slot_iso: str) -> dict[str, Any] | None:
    """The observe block of the report whose slot 0 was ``slot_iso``; ``None`` otherwise."""
    if not isinstance(plan, dict) or plan.get("mode") != MODE_OBSERVE:
        return None
    block = plan.get("observe")
    if not isinstance(block, dict):
        raise ValueError("import_cap_report_store: observe report without observe block")
    return block if block.get("slot") == slot_iso else None


def record_observed(
    interval_start: Any,
    measured_kw: float | None,
    *,
    params: dict | None,
    path: str | None = None,
    peak_path: str | None = None,
    baseline_path: str | None = None,
) -> dict[str, Any] | None:
    """Observe mode: one closed quarter hour in the world where Earnie had held the cap.

    Hypothetical import = max(0, ``measured_kw`` + delta), delta = slot-0 import of the shadow
    plan − that of the executed plan, from the latest report when its slot 0 was this quarter
    hour. Without that report (mode just switched, Automatik, failed shadow solve) or without a
    measurement the quarter hour counts as missing in the hypothetical store. The baseline store
    gets the measured import of the same quarter hours, missing where the hypothetical one is.
    Returns the overshoot event of the hypothetical import, ``None`` when within.
    """
    from runtime_store import capacity_peak_store

    slot = _slot(interval_start)
    slot_iso = _iso(slot)
    month = f"{slot:%Y-%m}"
    target = _path(path)
    peak_file = peak_path or capacity_peak_store.observe_path()
    baseline_file = baseline_path or capacity_peak_store.observe_baseline_path()
    data = load(target)
    block = _observe_block_of(data["plan"], slot_iso)
    delta = None if block is None else block["delta_import_kw"]
    hypothetical = (
        None if measured_kw is None or delta is None else max(0.0, float(measured_kw) + float(delta))
    )
    before = capacity_peak_store.month_peak(month, path=peak_file)
    capacity_peak_store.record_slot(slot, hypothetical, OBSERVE_PEAK_SOURCE, path=peak_file)
    capacity_peak_store.record_slot(
        slot,
        None if hypothetical is None else float(measured_kw),
        OBSERVE_BASELINE_SOURCE,
        path=baseline_file,
    )
    if delta is not None and abs(float(delta)) > SLACK_TOLERANCE_KW:
        cause = next(
            (e["cause"] for e in data["plan"].get("slots") or [] if e.get("slot") == slot_iso), None
        )
        _add_by_month(data["interventions"], month, {
            "slot": slot_iso,
            "measured_kw": None if measured_kw is None else round(float(measured_kw), 3),
            "hypothetical_kw": None if hypothetical is None else round(hypothetical, 3),
            "delta_kw": round(float(delta), 3),
            "executed": block["executed"],
            "shadow": block["shadow"],
            "cause": cause,
        })
        _save(data, target)
    if hypothetical is None:
        return None
    return record_measured(
        slot,
        hypothetical,
        params=params,
        peak_before_kw=None if before is None else before.peak_kw,
        path=target,
        measured_kw=measured_kw,
    )

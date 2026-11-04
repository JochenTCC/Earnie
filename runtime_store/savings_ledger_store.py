"""Savings ledger files and log pairing (spec ``docs/dev/savings-ledger.md`` § 4).

- ``savings_ledger.jsonl``: append-only, one row per closed SA-day.
- ``savings_ledger_slots.jsonl``: append-only, the slot series of one closed SA-day per line.
- ``savings_ledger_state.json``: shadow chain and the open day, written atomically.

The engine itself is ``runtime_store.savings_ledger`` (pure). This module reads and
writes the files and turns production-log entries into ``LedgerInput`` slots.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from data.planning_window import (
    align_to_planning_timezone,
    next_sunrise_after,
    previous_sunrise_before,
)
from optimizer.schedule import quarter_hour_slot_start
from runtime_store.history_chart_rows import (
    _import_price_cent_from_entry,
    _index_entries_by_slot,
)
from runtime_store.persist_paths_base import (
    savings_ledger_file,
    savings_ledger_slots_file,
    savings_ledger_state_file,
)
from runtime_store import savings_ledger as sl
from runtime_store.savings_ledger import (
    CHAIN_FIRST_RUN,
    CHAIN_SAVINGS_V_CHANGED,
    CHAIN_STATE_UNREADABLE,
    SAVINGS_V,
    DayBounds,
    LedgerInput,
    LedgerState,
)
from runtime_store.slot_ist_powers import index_closed_intervals_by_start

logger = logging.getLogger(__name__)

_SLOT_BACKFILL_HINT = "rebuild it with: python -m scripts.build_savings_ledger --since <chain date> --slots-only"


@dataclass(frozen=True)
class LoadedState:
    """State from disk, or ``None`` with the reason a new chain has to start."""

    state: LedgerState | None
    restart_reason: str | None


def load_state(path: str | None = None, *, now: datetime | None = None) -> LoadedState:
    """Read the ledger state.

    Missing file → new chain (``first_run``). A file of another ``savings_v`` → new
    chain (``savings_v_changed``). An unreadable or malformed file is moved aside
    to ``<path>.broken-<timestamp>`` with a warning and a new chain starts
    (``state_unreadable``); the first row of that chain carries the reason.
    """
    path = path or savings_ledger_state_file()
    if not os.path.isfile(path):
        return LoadedState(None, CHAIN_FIRST_RUN)
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError("state root must be an object")
        if int(raw.get("savings_v", -1)) != SAVINGS_V:
            logger.info(
                "savings ledger: state has savings_v %r, current is %d — new chain.",
                raw.get("savings_v"),
                SAVINGS_V,
            )
            return LoadedState(None, CHAIN_SAVINGS_V_CHANGED)
        return LoadedState(LedgerState.from_dict(raw), None)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        broken = f"{path}.broken-{stamp}"
        logger.warning(
            "savings ledger: state unreadable (%s) — moved to %s, new chain starts.",
            exc,
            broken,
        )
        os.replace(path, broken)
        return LoadedState(None, CHAIN_STATE_UNREADABLE)


def peek_state(path: str | None = None) -> LoadedState:
    """Read the state without touching the file, for readers other than the daemon.

    Same reasons as :func:`load_state`, but an unreadable file stays in place: moving
    it aside starts a new chain, and that is the daemon's call alone.
    """
    path = path or savings_ledger_state_file()
    if not os.path.isfile(path):
        return LoadedState(None, CHAIN_FIRST_RUN)
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError("state root must be an object")
        if int(raw.get("savings_v", -1)) != SAVINGS_V:
            return LoadedState(None, CHAIN_SAVINGS_V_CHANGED)
        return LoadedState(LedgerState.from_dict(raw), None)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("savings ledger: state unreadable (%s).", exc)
        return LoadedState(None, CHAIN_STATE_UNREADABLE)


def save_state(state: LedgerState, path: str | None = None) -> None:
    """Write the state atomically (temp file + ``os.replace``)."""
    path = path or savings_ledger_state_file()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(state.to_dict(), handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    os.replace(tmp, path)


def append_row(row: dict[str, Any], path: str | None = None) -> None:
    """Append one closed-day row to the ledger file."""
    path = path or savings_ledger_file()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")


def read_rows(path: str | None = None) -> list[dict[str, Any]]:
    """All ledger rows; a malformed line raises ``ValueError`` with its line number."""
    path = path or savings_ledger_file()
    if not os.path.isfile(path):
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"savings ledger: line {number} of {path} is not JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"savings ledger: line {number} of {path} is not an object")
            rows.append(row)
    return rows


class SlotFileError(ValueError):
    """The slot file is missing, broken or does not match the ledger."""


def append_day_slots(record: dict[str, Any], path: str | None = None) -> None:
    """Append the slot record of one closed SA-day to the slot file."""
    path = path or savings_ledger_slots_file()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _check_record_shape(record: Any) -> None:
    if not isinstance(record, dict):
        raise ValueError("not an object")
    if not isinstance(record.get("day_start"), str):
        raise ValueError("day_start missing")
    slots = record.get("slots")
    if not isinstance(slots, list):
        raise ValueError("slots must be a list")
    for slot in slots:
        if not isinstance(slot, dict) or not isinstance(slot.get("slot_start"), str):
            raise ValueError("slot without slot_start")
        if not isinstance(slot.get("counted"), bool):
            raise ValueError(f"slot {slot['slot_start']}: counted must be true or false")
        values = (slot.get("cost_with_eur"), slot.get("cost_without_eur"), slot.get("house_kwh"))
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in values):
            raise ValueError(f"slot {slot['slot_start']}: cost or house energy is not a number")
        if not slot["counted"] and any(values):
            raise ValueError(f"slot {slot['slot_start']}: a skipped slot must be zero")


def read_day_slots(path: str | None = None) -> dict[str, dict[str, Any]]:
    """Slot records by ``day_start``; a missing file or a broken line raises ``SlotFileError``."""
    path = path or savings_ledger_slots_file()
    if not os.path.isfile(path):
        raise SlotFileError(f"savings ledger: slot file {path} is missing; {_SLOT_BACKFILL_HINT}")
    records: dict[str, dict[str, Any]] = {}
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                _check_record_shape(record)
            except ValueError as exc:
                raise SlotFileError(
                    f"savings ledger: line {number} of {path} is broken ({exc}); {_SLOT_BACKFILL_HINT}"
                ) from exc
            if record["day_start"] in records:
                raise SlotFileError(
                    f"savings ledger: line {number} of {path} repeats day {record['day_start']}; "
                    f"{_SLOT_BACKFILL_HINT}"
                )
            records[record["day_start"]] = record
    return records


def check_rows_against_slots(
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Slots of every ledger row by ``day_start``; raises ``SlotFileError`` on any mismatch."""
    slots: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        record = records.get(row["day_start"])
        if record is None:
            raise SlotFileError(f"savings ledger: no slots for day {row['day_start']}; {_SLOT_BACKFILL_HINT}")
        try:
            sl.check_day_slots(row, record)
        except ValueError as exc:
            raise SlotFileError(f"savings ledger: {exc}; {_SLOT_BACKFILL_HINT}") from exc
        slots[row["day_start"]] = record["slots"]
    return slots


def closed_day_slots(
    rows: list[dict[str, Any]],
    path: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Slot series of the given closed-day ledger rows, by ``day_start``, for readers such as the chart.

    Without rows there is nothing to read (no day has closed yet, so no file is
    expected). With rows, a missing or broken file, a missing day or slots that do
    not add up to the row raise ``SlotFileError``.
    """
    if not rows:
        return {}
    return check_rows_against_slots(rows, read_day_slots(path))


def sunrise_day_bounds(latitude: float, longitude: float, timezone_name: str) -> DayBounds:
    """SA-day containing a moment: last sunrise at or before it → next sunrise after it."""

    def bounds(moment: datetime) -> tuple[datetime, datetime]:
        return (
            previous_sunrise_before(moment, latitude, longitude, timezone_name),
            next_sunrise_after(moment, latitude, longitude, timezone_name),
        )

    return bounds


def _planned_flex_kw(entry: dict[str, Any]) -> dict[str, float]:
    planned: dict[str, float] = {}
    for cid, item in (entry.get("delivery_compliance") or {}).items():
        if isinstance(item, dict) and item.get("planned_kw") is not None:
            planned[str(cid)] = float(item["planned_kw"])
    return planned


def pending_slot_from_entry(
    slot_start: datetime,
    slot_entry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Prices and slot-0 plan a log entry gives its own slot, or ``None`` without ``k_push_act``."""
    if slot_start.tzinfo is None:
        raise ValueError("savings ledger: slot_start must be timezone-aware")
    if slot_entry is None or slot_entry.get("k_push_act") is None:
        return None
    naive = slot_start.replace(tzinfo=None)
    return {
        "slot_start": slot_start.isoformat(),
        "k_act_cent": _import_price_cent_from_entry(slot_entry, slot_start=naive),
        "k_push_cent": float(slot_entry["k_push_act"]),
        "planned_flex_kw": _planned_flex_kw(slot_entry),
    }


def ledger_input_from_pending(
    slot_start: datetime,
    closed: dict[str, Any] | None,
    pending: dict[str, Any] | None,
) -> LedgerInput:
    """``LedgerInput`` for a closed slot; prices only when ``pending`` belongs to that slot."""
    if pending is None or pending.get("slot_start") != slot_start.isoformat():
        return LedgerInput(slot_start, closed, None, None)
    return LedgerInput(
        slot_start=slot_start,
        closed=closed,
        k_act_cent=float(pending["k_act_cent"]),
        k_push_cent=float(pending["k_push_cent"]),
        planned_flex_kw=dict(pending.get("planned_flex_kw") or {}),
    )


def ledger_input(
    slot_start: datetime,
    closed: dict[str, Any] | None,
    slot_entry: dict[str, Any] | None,
) -> LedgerInput:
    """Pair a slot's ``closed_interval`` with the prices and plan of the slot's own entry.

    The ``closed_interval`` of a slot arrives with the next cycle's entry; prices and
    the slot-0 plan come from the entry written in the slot itself (as the history
    chart pairs them). Without that entry, or without ``k_push_act`` in it, the
    prices are ``None`` and the ledger skips the slot (``no_price``).
    """
    return ledger_input_from_pending(
        slot_start, closed, pending_slot_from_entry(slot_start, slot_entry)
    )


def ledger_inputs_from_entries(
    entries: Iterable[dict[str, Any]],
    timezone_name: str,
) -> list[LedgerInput]:
    """Every closed slot in ``entries`` as ``LedgerInput``, oldest first."""
    entries = list(entries)
    closed_by = index_closed_intervals_by_start(entries)
    by_slot = _index_entries_by_slot(entries)
    inputs: list[LedgerInput] = []
    for naive_start in sorted(closed_by):
        slot_start = quarter_hour_slot_start(align_to_planning_timezone(naive_start, timezone_name))
        inputs.append(ledger_input(slot_start, closed_by[naive_start], by_slot.get(slot_start)))
    return inputs

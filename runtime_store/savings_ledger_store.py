"""Savings ledger files and log pairing (spec ``docs/dev/savings-ledger.md`` § 4).

- ``savings_ledger.jsonl``: append-only, one row per closed SA-day.
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
    savings_ledger_state_file,
)
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

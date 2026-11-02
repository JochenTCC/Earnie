"""Savings ledger daemon hook (Ledger P5, spec ``docs/dev/savings-ledger.md`` § 4).

``main.py`` calls ``on_cycle`` once per cycle, after the cycle's log entry is
written. Per call: book the slot whose ``closed_interval`` this cycle finalised
(with the prices the previous cycle stored for it), append a row when that slot
closes an SA-day, remember this cycle's prices for its own slot, save the state.
O(1): the production log is never re-read.

The shadow chain starts once, at the actual SoC of the first booked slot, and
then only resumes from the state file; it is never re-seeded from the live SoC.
Errors never stop the cycle: they log a warning and book the slot as skipped
(``error``), which the day row counts in ``errors``.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import Any

import config
from data.planning_window import align_to_planning_timezone
from optimizer.schedule import quarter_hour_slot_start
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from version import __version__

logger = logging.getLogger(__name__)

_state: sl.LedgerState | None = None
_loaded_path: str | None = None
_restart_reason: str | None = None
# Prices of the newest cycle while no chain exists yet (first slot without SoC).
_pending_without_chain: dict[str, Any] | None = None
_no_battery_logged = False


def reset() -> None:
    """Forget the in-memory state (tests; the next call reads the state file again)."""
    global _state, _loaded_path, _restart_reason, _pending_without_chain, _no_battery_logged
    _state = None
    _no_battery_logged = False
    _loaded_path = None
    _restart_reason = None
    _pending_without_chain = None


def _ensure_loaded() -> None:
    """Read the state file once per path (a changed runtime directory reads it again)."""
    global _state, _loaded_path, _restart_reason, _pending_without_chain
    path = store.savings_ledger_state_file()
    if _loaded_path == path:
        return
    loaded = store.load_state(path)
    _state = loaded.state
    _restart_reason = loaded.restart_reason
    _pending_without_chain = None
    _loaded_path = path


def _closed_slot_start(closed: dict[str, Any], timezone_name: str) -> datetime:
    naive = datetime.fromisoformat(str(closed["interval_start"]))
    return quarter_hour_slot_start(align_to_planning_timezone(naive, timezone_name))


def on_cycle(
    closed_interval: dict[str, Any] | None,
    run_payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Book this cycle into the ledger; returns the closed-day row, if any. Never raises."""
    try:
        return _on_cycle(closed_interval, run_payload, now=now)
    except Exception as exc:  # noqa: BLE001 — the ledger must never stop a live cycle
        logger.warning("savings ledger: cycle not booked (%s).", exc, exc_info=True)
        _book_error_slot(closed_interval)
        return None


def _book_error_slot(closed_interval: dict[str, Any] | None) -> None:
    global _state
    if _state is None or not isinstance(closed_interval, dict):
        return
    try:
        slot_start = _closed_slot_start(closed_interval, config.get_planning_timezone())
        _state = sl.record_error_slot(_state, slot_start)
        store.save_state(_state)
    except Exception as exc:  # noqa: BLE001
        logger.warning("savings ledger: error slot not recorded (%s).", exc)


def _on_cycle(
    closed_interval: dict[str, Any] | None,
    run_payload: dict[str, Any],
    *,
    now: datetime | None,
) -> dict[str, Any] | None:
    global _state, _pending_without_chain, _no_battery_logged
    batteries = config.get_battery_params_list()
    if not batteries:
        # v1 compares the battery strategy only; without a house battery there is nothing to book.
        if not _no_battery_logged:
            logger.info("savings ledger: no house battery configured — ledger inactive.")
            _no_battery_logged = True
        return None
    _ensure_loaded()
    timezone_name = config.get_planning_timezone()
    day_bounds = store.sunrise_day_bounds(
        config.get("LATITUDE", cast=float),
        config.get("LONGITUDE", cast=float),
        timezone_name,
    )
    battery = sl.shadow_battery_params(batteries)
    pending = _state.pending_slot if _state is not None else _pending_without_chain
    row = None
    if isinstance(closed_interval, dict) and closed_interval.get("interval_start"):
        slot_start = _closed_slot_start(closed_interval, timezone_name)
        inp = store.ledger_input_from_pending(slot_start, closed_interval, pending)
        if _state is None:
            _state = sl.start_chain(inp, day_bounds, reason=_restart_reason or sl.CHAIN_FIRST_RUN)
            if _state is not None:
                logger.info(
                    "savings ledger: chain started %s at SoC %.1f %% (%s).",
                    _state.chain_start.isoformat(),
                    _state.shadow_soc,
                    _state.chain_start_reason,
                )
        if _state is not None:
            advanced, row = sl.advance(_state, inp, battery, day_bounds, app_version=__version__)
            if row is not None:
                # Append before taking the new state: if the write fails, the next
                # slot closes the same day again instead of losing the row.
                store.append_row(row)
                logger.info(
                    "savings ledger: day %s closed, saving %.2f EUR (adjusted %.2f EUR, coverage %.2f).",
                    row["day_start"],
                    row["saving_eur"],
                    row["saving_adjusted_eur"],
                    row["coverage"],
                )
            _state = advanced
    moment = align_to_planning_timezone(now or datetime.now(), timezone_name)
    new_pending = store.pending_slot_from_entry(quarter_hour_slot_start(moment), run_payload)
    if _state is None:
        _pending_without_chain = new_pending
        return None
    _state = replace(_state, pending_slot=new_pending)
    store.save_state(_state)
    return row

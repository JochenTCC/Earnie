"""Chart 2 "Ersparnis bisher" from the savings ledger (spec ``docs/dev/savings-ledger.md`` § 5).

Every display slot left of *Jetzt* gets the ledger's ``cost_with`` and ``cost_without``
and a state (``ui.chart_account_view.SLOT_*``): the open SA-day from the ledger state,
closed days from the slot file (``savings_ledger_slots.jsonl``). Chart 2 draws its
account view from these (spec ``docs/dev/chart2-account-view.md`` § 4). Closed days
also bring their ledger figure. The result is a plain dict of JSON types: it lives in
``savings_view``, which debug dumps write out.

Reads only: the daemon owns the ledger files (``savings_ledger_store.peek_state``).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Sequence

import config
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store
from ui.chart_account_view import (
    SLOT_COUNTED,
    SLOT_NO_DATA,
    SLOT_PENDING,
    SLOT_PLAN,
    SLOT_SKIPPED,
)

logger = logging.getLogger(__name__)

HINT_NOT_RUNNING = (
    "Ersparnis bisher: Das Ersparnis-Buch läuft noch nicht. "
    "Die Linie erscheint, sobald die ersten Slots gebucht sind."
)
HINT_NO_DATA = "Ersparnis bisher: Das Ersparnis-Buch hat für diesen Zeitraum keine Daten."
HINT_UNREADABLE = "Ersparnis bisher: Das Ersparnis-Buch ist nicht lesbar, Details stehen im Log."
HINT_SLOTS_UNREADABLE = (
    "Ersparnis bisher: Die Slots der abgeschlossenen Tage sind nicht lesbar, sie sind orange "
    "markiert. Details und den Reparaturbefehl nennt das Log."
)



def _no_ledger(slot_count: int, history_slot_count: int, hint: str) -> dict[str, Any]:
    history = min(history_slot_count, slot_count)
    return {
        "slot_with_eur": [0.0] * slot_count,
        "slot_without_eur": [0.0] * slot_count,
        "slot_states": [SLOT_NO_DATA] * history + [SLOT_PLAN] * (slot_count - history),
        "slot_shadow_soc": [None] * slot_count,
        "open_day_start": None,
        "open_day_end": None,
        "saving_euro": None,
        "soc_correction_euro": None,
        "closed_days": [],
        "hint": hint,
    }


def _slot_series(
    slot_starts: Sequence[datetime],
    history_slot_count: int,
    state: sl.LedgerState,
    closed_slots: dict[str, list[dict[str, Any]]],
) -> tuple[list[float], list[float], list[str]]:
    """``cost_with``, ``cost_without`` and state per display slot.

    A slot of the open day after its last booked slot is ``pending`` (the daemon books
    it once it closes) and counts as zero without being marked. A slot the ledger
    knows nothing else about is ``no_data``.
    """
    booked: dict[datetime, dict[str, Any]] = {}
    for day in closed_slots.values():
        for slot in day:
            booked[datetime.fromisoformat(slot["slot_start"])] = slot
    for slot in state.slots:
        booked[datetime.fromisoformat(slot["slot_start"])] = slot
    count = len(slot_starts)
    with_eur = [0.0] * count
    without_eur = [0.0] * count
    states = [SLOT_PLAN] * count
    for index in range(min(history_slot_count, count)):
        start = slot_starts[index]
        record = booked.get(start)
        if record is not None:
            if record["counted"]:
                with_eur[index] = float(record["cost_with_eur"])
                without_eur[index] = float(record["cost_without_eur"])
                states[index] = SLOT_COUNTED
            else:
                states[index] = SLOT_SKIPPED
            continue
        in_open_day = state.day_start <= start < state.day_end
        after_booked = state.last_slot_start is None or start > state.last_slot_start
        states[index] = SLOT_PENDING if in_open_day and after_booked else SLOT_NO_DATA
    return with_eur, without_eur, states


def _slot_shadow_soc(
    slot_starts: Sequence[datetime],
    history_slot_count: int,
    state: sl.LedgerState,
) -> list[float | None]:
    """Shadow SoC at the end of each display slot left of *Jetzt*; the open day only (Chart 1)."""
    by_start = {
        datetime.fromisoformat(slot["slot_start"]): float(slot["shadow_soc_end"])
        for slot in state.slots
    }
    values: list[float | None] = [None] * len(slot_starts)
    for index in range(min(history_slot_count, len(slot_starts))):
        values[index] = by_start.get(slot_starts[index])
    return values


def open_day_figures(state: sl.LedgerState, battery_params: dict) -> tuple[float, float]:
    """Saving of the open SA-day so far and its SoC correction, as if the day closed now."""
    row = sl.close_day(state, battery_params, app_version="")
    saving = float(row["saving_eur"])
    return saving, float(row["saving_adjusted_eur"]) - saving


def build_ledger_chart_savings(
    slot_starts: Sequence[datetime],
    history_slot_count: int,
    state: sl.LedgerState,
    battery_params: dict,
    rows: Sequence[dict[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
    closed_slots: dict[str, list[dict[str, Any]]] | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    """Slot series and day figures of one chart window. Pure.

    ``closed_slots`` are the slot series of the closed days in the window, by
    ``day_start`` (``savings_ledger_store.closed_day_slots``); ``hint`` overrides the
    note under the chart, e.g. when the slot file is unreadable.

    The ``open_day_*``, ``saving_euro`` and ``soc_correction_euro`` fields depend on the
    state alone, not on the window, so the Monitor tile can read them on every page.
    Without a booked slot they are ``None``: there is nothing to report yet.
    """
    saving, soc_correction = (
        open_day_figures(state, battery_params) if state.slots else (None, None)
    )
    with_eur, without_eur, states = _slot_series(
        slot_starts, history_slot_count, state, closed_slots or {}
    )
    closed_days = [
        {
            "day_start": str(item["day_start"]),
            "day_end": str(item["day_end"]),
            "saving_eur": float(item["saving_eur"]),
            "saving_adjusted_eur": float(item["saving_adjusted_eur"]),
            "incomplete": bool(item.get("incomplete")),
        }
        for item in rows
        if datetime.fromisoformat(str(item["day_end"])) > window_start
        and datetime.fromisoformat(str(item["day_start"])) < window_end
    ]
    has_line = any(state_ in (SLOT_COUNTED, SLOT_SKIPPED) for state_ in states)
    if hint is None and not (has_line or closed_days):
        hint = HINT_NO_DATA
    return {
        "slot_with_eur": with_eur,
        "slot_without_eur": without_eur,
        "slot_states": states,
        "slot_shadow_soc": _slot_shadow_soc(slot_starts, history_slot_count, state),
        "open_day_start": state.day_start.isoformat(),
        "open_day_end": state.day_end.isoformat(),
        "saving_euro": saving,
        "soc_correction_euro": soc_correction,
        "closed_days": closed_days,
        "hint": hint,
    }


def load_ledger_chart_savings(
    slot_starts: Sequence[datetime],
    history_slot_count: int,
    *,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    """Ledger figures of a chart window from the runtime files, or a hint why there are none."""
    count = len(slot_starts)
    loaded = store.peek_state()
    if loaded.restart_reason == sl.CHAIN_STATE_UNREADABLE:
        return _no_ledger(count, history_slot_count, HINT_UNREADABLE)
    if loaded.state is None:
        return _no_ledger(count, history_slot_count, HINT_NOT_RUNNING)
    batteries = config.get_battery_params_list()
    if not batteries:
        return _no_ledger(count, history_slot_count, HINT_NOT_RUNNING)
    try:
        rows = store.read_rows()
        closed_slots, hint = _closed_slots_in_window(
            rows, window_start=window_start, window_end=window_end
        )
        return build_ledger_chart_savings(
            slot_starts,
            history_slot_count,
            loaded.state,
            sl.shadow_battery_params(batteries),
            rows,
            window_start=window_start,
            window_end=window_end,
            closed_slots=closed_slots,
            hint=hint,
        )
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("savings ledger: Chart 2 cannot read the ledger (%s).", exc)
        return _no_ledger(count, history_slot_count, HINT_UNREADABLE)


def _closed_slots_in_window(
    rows: Sequence[dict[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    """Slot series of the closed days the window touches; a broken slot file is a hint, not a crash.

    The open day and the closed days' figures stay usable, so the chart marks the
    closed days' slots orange and the log names the repair command.
    """
    in_window = [
        row
        for row in rows
        if datetime.fromisoformat(str(row["day_end"])) > window_start
        and datetime.fromisoformat(str(row["day_start"])) < window_end
    ]
    try:
        return store.closed_day_slots(in_window), None
    except store.SlotFileError as exc:
        logger.warning("%s", exc)
        return {}, HINT_SLOTS_UNREADABLE

"""Chart 2 "Ersparnis bisher" from the savings ledger (spec ``docs/dev/savings-ledger.md`` § 5).

The grey zone shows the booked slots of the open SA-day, cumulated as
``cost_without − cost_with`` (positive = saved). Closed days only have their ledger
row, so they get a figure but no line. The result is a plain dict of JSON types: it
lives in ``savings_view``, which debug dumps write out.

Reads only: the daemon owns the ledger files (``savings_ledger_store.peek_state``).
"""
from __future__ import annotations

import logging
from bisect import bisect_right
from datetime import datetime, timedelta
from typing import Any, Sequence

import config
from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_store as store

logger = logging.getLogger(__name__)

HINT_NOT_RUNNING = (
    "Ersparnis bisher: Das Ersparnis-Buch läuft noch nicht. "
    "Die Linie erscheint, sobald die ersten Slots gebucht sind."
)
HINT_NO_DATA = "Ersparnis bisher: Das Ersparnis-Buch hat für diesen Zeitraum keine Daten."
HINT_UNREADABLE = "Ersparnis bisher: Das Ersparnis-Buch ist nicht lesbar, Details stehen im Log."

# A chart day and a ledger day are the same SA-day when the chart day's middle lies in
# the ledger day. Both come from the sunrise calculation, but the stamps can differ.
_DAY_MIDDLE = timedelta(hours=12)


def _no_ledger(slot_count: int, hint: str) -> dict[str, Any]:
    return {
        "cumulative_euro": [float("nan")] * slot_count,
        "open_day_start": None,
        "open_day_end": None,
        "saving_euro": None,
        "soc_correction_euro": None,
        "closed_days": [],
        "hint": hint,
    }


def _cumulative_on_slots(
    slot_starts: Sequence[datetime],
    history_slot_count: int,
    state: sl.LedgerState,
) -> list[float]:
    """Cumulated saving per display slot; NaN outside the booked part of the open day."""
    booked = sorted(
        (datetime.fromisoformat(slot["slot_start"]), slot) for slot in state.slots
    )
    series = [float("nan")] * len(slot_starts)
    if not booked:
        return series
    starts = [start for start, _ in booked]
    totals: list[float] = []
    running = 0.0
    for _, slot in booked:
        running += float(slot["cost_without_eur"]) - float(slot["cost_with_eur"])
        totals.append(running)
    for index in range(min(history_slot_count, len(slot_starts))):
        slot = slot_starts[index]
        if not state.day_start <= slot < state.day_end or slot > starts[-1]:
            continue
        position = bisect_right(starts, slot)
        if position:
            series[index] = totals[position - 1]
    return series


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
) -> dict[str, Any]:
    """Slot series and day figures of one chart window. Pure.

    The ``open_day_*``, ``saving_euro`` and ``soc_correction_euro`` fields depend on the
    state alone, not on the window, so the Monitor tile can read them on every page.
    Without a booked slot they are ``None``: there is nothing to report yet.
    """
    saving, soc_correction = (
        open_day_figures(state, battery_params) if state.slots else (None, None)
    )
    series = _cumulative_on_slots(slot_starts, history_slot_count, state)
    closed_days = [
        {
            "day_start": str(item["day_start"]),
            "day_end": str(item["day_end"]),
            "saving_adjusted_eur": float(item["saving_adjusted_eur"]),
            "incomplete": bool(item.get("incomplete")),
        }
        for item in rows
        if datetime.fromisoformat(str(item["day_end"])) > window_start
        and datetime.fromisoformat(str(item["day_start"])) < window_end
    ]
    has_line = any(value == value for value in series)
    return {
        "cumulative_euro": series,
        "open_day_start": state.day_start.isoformat(),
        "open_day_end": state.day_end.isoformat(),
        "saving_euro": saving,
        "soc_correction_euro": soc_correction,
        "closed_days": closed_days,
        "hint": None if has_line or closed_days else HINT_NO_DATA,
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
        return _no_ledger(count, HINT_UNREADABLE)
    if loaded.state is None:
        return _no_ledger(count, HINT_NOT_RUNNING)
    batteries = config.get_battery_params_list()
    if not batteries:
        return _no_ledger(count, HINT_NOT_RUNNING)
    try:
        rows = store.read_rows()
        return build_ledger_chart_savings(
            slot_starts,
            history_slot_count,
            loaded.state,
            sl.shadow_battery_params(batteries),
            rows,
            window_start=window_start,
            window_end=window_end,
        )
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("savings ledger: Chart 2 cannot read the ledger (%s).", exc)
        return _no_ledger(count, HINT_UNREADABLE)


def ledger_figures_for_day(
    ledger: dict[str, Any] | None,
    day_start: datetime,
) -> dict[str, Any]:
    """Ledger figures of one chart SA-day: open day, closed day or none."""
    empty = {"saving_euro": None, "soc_correction_euro": None, "closed_saving_euro": None,
             "incomplete": False}
    if not ledger:
        return empty
    middle = day_start + _DAY_MIDDLE
    if ledger["open_day_start"] is not None and (
        datetime.fromisoformat(ledger["open_day_start"])
        <= middle
        < datetime.fromisoformat(ledger["open_day_end"])
    ):
        return {
            **empty,
            "saving_euro": ledger["saving_euro"],
            "soc_correction_euro": ledger["soc_correction_euro"],
        }
    for day in ledger["closed_days"]:
        if (
            datetime.fromisoformat(day["day_start"])
            <= middle
            < datetime.fromisoformat(day["day_end"])
        ):
            return {
                **empty,
                "closed_saving_euro": day["saving_adjusted_eur"],
                "incomplete": day["incomplete"],
            }
    return empty

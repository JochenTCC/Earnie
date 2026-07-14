"""Rolling-horizont-Zustand für generic-Flex min_on-Blöcke."""
from __future__ import annotations

from .generic_flex_context import generic_flex_window
from .milp_consumers import _min_on_hours


def is_generic_flex_consumer(consumer: dict) -> bool:
    return generic_flex_window(consumer) is not None


def continue_on_from_state(
    state: dict,
    consumers: list,
) -> dict[str, bool]:
    """True wenn der Verbraucher in Stunde t=0 weiterlaufen muss (offener min_on-Block)."""
    run_state = state.get("generic_flex_run") or {}
    result: dict[str, bool] = {}
    for consumer in consumers:
        cid = consumer["id"]
        if not is_generic_flex_consumer(consumer):
            continue
        entry = run_state.get(cid) or {}
        result[cid] = int(entry.get("block_hours_remaining", 0) or 0) > 0
    return result


def update_generic_flex_run_state(
    run_state: dict[str, dict],
    consumer: dict,
    power_kw: float,
) -> None:
    """Aktualisiert offene min_on-Stunden nach einer ausgeführten Stunde."""
    if not is_generic_flex_consumer(consumer):
        return
    cid = consumer["id"]
    min_hours = _min_on_hours(consumer)
    entry = dict(run_state.get(cid) or {"block_hours_remaining": 0})
    was_continuing = int(entry.get("block_hours_remaining", 0) or 0) > 0
    if power_kw > 1e-6:
        if was_continuing:
            entry["block_hours_remaining"] = max(
                0, int(entry["block_hours_remaining"]) - 1
            )
        else:
            entry["block_hours_remaining"] = max(0, min_hours - 1)
    else:
        entry["block_hours_remaining"] = 0
    run_state[cid] = entry


def reset_generic_flex_run_state(run_state: dict[str, dict]) -> dict[str, dict]:
    return {}

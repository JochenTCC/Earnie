"""Soll/Ist-Abweichungen entlang der Chart-Historie (Epic Soll-Ist P2)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from optimizer.deviation_eval import DeviationEvent, evaluate_entry_deviations
from optimizer.deviation_rules import load_deviation_rules
from optimizer.schedule import quarter_hour_slot_start

logger = logging.getLogger(__name__)


def resolve_deviation_rules_document(
    rules_doc: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if rules_doc is not None:
        return rules_doc
    try:
        return load_deviation_rules()
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("Abweichungsregeln nicht geladen: %s", exc)
        return None


def _slot_lookup_key(slot_start: datetime) -> datetime:
    return quarter_hour_slot_start(slot_start)


def build_slot_deviation_series(
    by_slot: dict[datetime, dict[str, Any]],
    slot_starts: tuple[datetime, ...],
    slot_qualities: tuple[str, ...],
    *,
    rules_doc: dict[str, Any] | None = None,
) -> tuple[tuple[DeviationEvent, ...], ...]:
    """Pro Slot eine Event-Tuple; nur SLOT_PRESENT mit Log-Eintrag wird ausgewertet."""
    from runtime_store.history_timeline import SLOT_PRESENT

    document = resolve_deviation_rules_document(rules_doc)
    series: list[tuple[DeviationEvent, ...]] = []
    for slot_start, quality in zip(slot_starts, slot_qualities):
        if quality != SLOT_PRESENT:
            series.append(())
            continue
        entry = by_slot.get(_slot_lookup_key(slot_start))
        if entry is None or document is None:
            series.append(())
            continue
        slot_events = evaluate_entry_deviations(
            entry,
            slot_quality=quality,
            rules_doc=document,
        )
        series.append(tuple(slot_events))
    return tuple(series)


def empty_deviation_series(length: int) -> tuple[tuple[DeviationEvent, ...], ...]:
    return tuple(() for _ in range(length))

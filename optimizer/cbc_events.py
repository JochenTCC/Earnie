"""Sammlung kritischer CBC-/MILP-Ereignisse (Strict-Fallback, langsamer Strict-Lauf)."""
from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

STRICT_SLOW_FRACTION = 0.95


@dataclass
class CbcMilpContext:
    scenario_id: str | None = None
    window_anchor: str | None = None
    slot_datetime: str | None = None
    milp_hour: int | None = None
    simulation_hour_index: int | None = None
    consumer_targets_kwh: dict[str, float] | None = None


_milp_context: ContextVar[CbcMilpContext | None] = ContextVar(
    "cbc_milp_context",
    default=None,
)
_events: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "cbc_events",
    default=None,
)


def begin_cbc_event_collection() -> None:
    _events.set([])


def take_cbc_events() -> list[dict[str, Any]]:
    collected = _events.get()
    _events.set(None)
    return list(collected) if collected else []


def set_cbc_milp_context(**fields: Any) -> None:
    current = _milp_context.get() or CbcMilpContext()
    _milp_context.set(replace(current, **fields))


def clear_cbc_milp_context() -> None:
    _milp_context.set(None)


def update_cbc_milp_context_from_row(row: dict[str, Any]) -> None:
    slot = row.get("slot_datetime")
    anchor = row.get("charging_anchor")
    fields: dict[str, Any] = {"milp_hour": row.get("hour")}
    if slot is not None:
        fields["slot_datetime"] = _iso(slot)
    if anchor is not None:
        fields["window_anchor"] = _iso(anchor)
    set_cbc_milp_context(**fields)


def record_cbc_event(event: str, **details: Any) -> dict[str, Any]:
    ctx = _milp_context.get() or CbcMilpContext()
    entry: dict[str, Any] = {
        "event": event,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **{k: v for k, v in asdict(ctx).items() if v is not None},
        **details,
    }
    collected = _events.get()
    if collected is not None:
        collected.append(entry)
        return entry
    level = logging.INFO
    if event == "strict_slow":
        level = logging.DEBUG
    logger.log(level, _format_event_log(entry))
    return entry


def _iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _format_event_log(entry: dict[str, Any]) -> str:
    parts = [
        f"CBC {entry['event']}",
        f"Szenario={entry.get('scenario_id', '?')}",
        f"Anker={entry.get('window_anchor', '?')}",
        f"Slot={entry.get('slot_datetime', '?')}",
    ]
    if entry.get("simulation_hour_index") is not None:
        parts.append(f"Stunde={entry['simulation_hour_index']}")
    if entry.get("strict_status") is not None:
        parts.append(f"strict={entry['strict_status']}")
    if entry.get("strict_elapsed_sec") is not None:
        parts.append(f"{entry['strict_elapsed_sec']:.2f}s")
    if entry.get("final_status") is not None:
        parts.append(f"final={entry['final_status']}")
    if entry.get("gap_rel") is not None:
        parts.append(f"gapRel={float(entry['gap_rel']) * 100:.1f}%")
    eauto = (entry.get("consumer_targets_kwh") or {}).get("eauto")
    if eauto is not None:
        parts.append(f"eauto={float(eauto):.3f}kWh")
    return " | ".join(parts)


def maybe_record_strict_timing(
    *,
    strict_limit_sec: float,
    strict_elapsed_sec: float,
    strict_status: str,
    gap_rel: float,
    final_status: str | None = None,
) -> None:
    if strict_limit_sec <= 0:
        return
    base = {
        "strict_limit_sec": strict_limit_sec,
        "strict_elapsed_sec": round(strict_elapsed_sec, 3),
        "strict_status": strict_status,
        "gap_rel": gap_rel,
    }
    if final_status is not None:
        base["final_status"] = final_status
    if strict_status != "Optimal":
        record_cbc_event("strict_fallback", **base)
        return
    if strict_elapsed_sec >= strict_limit_sec * STRICT_SLOW_FRACTION:
        record_cbc_event("strict_slow", **base)


def cbc_event_collection_active() -> bool:
    return _events.get() is not None


def summarize_cbc_events(events: list[dict[str, Any]]) -> str | None:
    """Kompakte INFO-Zusammenfassung für gesammelte Horizont-CBC-Ereignisse."""
    if not events:
        return None
    counts: dict[str, int] = {}
    final_statuses: dict[str, int] = {}
    for entry in events:
        name = str(entry.get("event", "?"))
        counts[name] = counts.get(name, 0) + 1
        if name == "milp_no_optimal":
            status = str(entry.get("final_status", "?"))
            final_statuses[status] = final_statuses.get(status, 0) + 1
    parts = [f"{name}={count}" for name, count in sorted(counts.items())]
    if final_statuses:
        detail = ", ".join(f"{k}:{v}" for k, v in sorted(final_statuses.items()))
        parts.append(f"final({detail})")
    return "CBC Horizont-Simulation: " + ", ".join(parts)

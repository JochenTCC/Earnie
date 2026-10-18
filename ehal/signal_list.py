"""EHAL Signal list rows (2.7.q Q7 / Binding P5b) — contract view for all backends.

Match status is derived at render time, never persisted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from ehal.flex_fields import flex_field_label
from ehal.functions import EHAL_FUNCTIONS
from ehal.profiles import role_field_labels
from ehal.push_signals import (
    REQUEST_OPTIMIZE_ID,
    REQUEST_OPTIMIZE_MEANING,
    Signal,
    heartbeat_signal,
    heartbeat_write_signal,
    request_optimize_signal,
)
from ehal.qualified_ids import field_kind, parse_qualified_id
from ehal.signal_catalog import CatalogEntry, catalog_to_signals, iter_catalog_entries

Direction = Literal["read", "write"]
MatchKind = Literal["ok", "stale", "never", "published", "awaiting_fetch", "inactive"]


@dataclass(frozen=True)
class SignalRow:
    ehal_id: str
    direction: Direction
    meaning: str
    entity_label: str
    required_by: tuple[str, ...]
    match_kind: MatchKind
    match_text: str
    group: str
    digital: bool
    is_required: bool = False
    is_activated: bool = False
    binding_key: str = ""
    component_kind: str = ""
    entity_id: str = ""
    consumer_type: str = ""


def _meaning_for(kind: str) -> str:
    if kind == REQUEST_OPTIMIZE_ID:
        return REQUEST_OPTIMIZE_MEANING
    labels = role_field_labels()
    return flex_field_label(kind) or labels.get(kind) or kind


def _functions_for_kind(kind: str) -> tuple[str, ...]:
    return tuple(fn.label for fn in EHAL_FUNCTIONS if kind in fn.required)


def _age_seconds(iso_ts: str) -> float | None:
    text = str(iso_ts or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _read_match(ehal_id: str, inbox: dict[str, dict[str, Any]]) -> tuple[MatchKind, str]:
    row = inbox.get(ehal_id) or {}
    last_ts = str(row.get("last_ts") or "").strip()
    if not last_ts:
        return "never", "nie empfangen"
    age = _age_seconds(last_ts)
    if age is None:
        return "ok", last_ts
    # Rare control receipts (request_optimize): keep OK with age — not a repeating VO.
    if ehal_id == REQUEST_OPTIMIZE_ID:
        return "ok", f"vor {int(age)} s"
    if age > 300:
        return "stale", f"vor {int(age)} s"
    return "ok", f"vor {int(age)} s"


def _write_match(
    ehal_id: str,
    published: dict[str, dict[str, Any]],
    fetched_at: str | None,
) -> tuple[MatchKind, str]:
    rec = published.get(ehal_id)
    if not rec:
        return "never", "nie veröffentlicht"
    pub_at = str(rec.get("published_at") or "").strip()
    if not fetched_at:
        return "awaiting_fetch", f"publiziert {pub_at or '—'}; MS noch nicht"
    return "published", f"MS-Abruf {fetched_at}"


def _entity_label(group: str, ehal_id: str) -> str:
    if group in ("Plant", "Heartbeat", "Status"):
        return group
    if group.startswith("Batterie_"):
        return group.replace("Batterie_", "Batterie ", 1)
    parsed = parse_qualified_id(ehal_id)
    if parsed and parsed.kennung:
        return f"{group} ({parsed.kennung})"
    return group


def _row_from_catalog(
    entry: CatalogEntry,
    *,
    inbox: dict[str, dict[str, Any]],
    published: dict[str, dict[str, Any]],
    fetched_at: str | None,
) -> SignalRow:
    kind = field_kind(entry.ehal_id)
    if not entry.is_activated:
        match_kind: MatchKind = "inactive"
        match_text = "nicht aktiviert"
    elif entry.direction == "read":
        match_kind, match_text = _read_match(entry.ehal_id, inbox)
    else:
        match_kind, match_text = _write_match(entry.ehal_id, published, fetched_at)
    return SignalRow(
        ehal_id=entry.ehal_id,
        direction=entry.direction,
        meaning=_meaning_for(kind),
        entity_label=_entity_label(entry.group, entry.ehal_id),
        required_by=_functions_for_kind(kind),
        match_kind=match_kind,
        match_text=match_text,
        group=entry.group,
        digital=entry.digital,
        is_required=entry.is_required,
        is_activated=entry.is_activated,
        binding_key=entry.binding_key,
        component_kind=entry.component_kind,
        entity_id=entry.entity_id,
        consumer_type=entry.consumer_type,
    )


def _control_row(
    sig: Signal,
    direction: Direction,
    *,
    inbox: dict[str, dict[str, Any]],
    published: dict[str, dict[str, Any]],
    fetched_at: str | None,
) -> SignalRow:
    kind = field_kind(sig.ehal_id)
    if direction == "read":
        match_kind, match_text = _read_match(sig.ehal_id, inbox)
    else:
        match_kind, match_text = _write_match(sig.ehal_id, published, fetched_at)
    return SignalRow(
        ehal_id=sig.ehal_id,
        direction=direction,
        meaning=_meaning_for(kind if kind != sig.ehal_id else sig.ehal_id),
        entity_label=_entity_label(sig.group, sig.ehal_id),
        required_by=_functions_for_kind(kind),
        match_kind=match_kind,
        match_text=match_text,
        group=sig.group,
        digital=sig.digital,
        is_required=False,
        is_activated=True,
        binding_key="",
        component_kind="",
        entity_id="",
        consumer_type="",
    )


def build_signal_rows(
    house: dict,
    components: dict,
    *,
    inbox: dict[str, dict[str, Any]] | None = None,
    published: dict[str, dict[str, Any]] | None = None,
    fetched_at: str | None = None,
    include_heartbeat: bool = True,
) -> list[SignalRow]:
    """Rows for every catalog signal (required + optional) plus heartbeats.

    ``request_optimize`` is always listed (control receipt; not a VO telemetry export).
    """
    inbox = inbox if inbox is not None else {}
    published = published if published is not None else {}
    rows: list[SignalRow] = [
        _row_from_catalog(
            entry, inbox=inbox, published=published, fetched_at=fetched_at
        )
        for entry in iter_catalog_entries(house, components)
    ]
    if include_heartbeat:
        rows.append(
            _control_row(
                heartbeat_signal(),
                "read",
                inbox=inbox,
                published=published,
                fetched_at=fetched_at,
            )
        )
        rows.append(
            _control_row(
                heartbeat_write_signal(),
                "write",
                inbox=inbox,
                published=published,
                fetched_at=fetched_at,
            )
        )
    rows.append(
        _control_row(
            request_optimize_signal(),
            "read",
            inbox=inbox,
            published=published,
            fetched_at=fetched_at,
        )
    )
    rows.sort(key=lambda r: (r.group, r.direction, r.ehal_id))
    return rows


def signals_for_export(
    house: dict,
    components: dict,
    *,
    mode: Literal["needed", "all"] = "needed",
) -> tuple[list[Signal], list[Signal]]:
    """Return (read_signals, write_signals) for VO/VI export.

    ``needed`` = activated bindings only (+ heartbeats).
    ``all`` = every catalog signal (required + optional), activated or not.
    """
    entries = iter_catalog_entries(house, components)
    reads, writes = catalog_to_signals(
        entries, activated_only=(mode == "needed")
    )
    reads.append(heartbeat_signal())
    writes.append(heartbeat_write_signal())
    return reads, writes

"""EHAL Signal list rows (2.7.q Q7) — contract view for Loxone push I/O.

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
    Signal,
    heartbeat_signal,
    heartbeat_write_signal,
    read_signals_from_docs,
    write_signals_from_docs,
)
from ehal.qualified_ids import field_kind, parse_qualified_id

Direction = Literal["read", "write"]
MatchKind = Literal["ok", "stale", "never", "published", "awaiting_fetch"]


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


def _meaning_for(kind: str) -> str:
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
    if group in ("Plant", "Heartbeat"):
        return group
    # Batterie_<id> / Verbraucher / …
    if group.startswith("Batterie_"):
        return group.replace("Batterie_", "Batterie ", 1)
    parsed = parse_qualified_id(ehal_id)
    if parsed and parsed.kennung:
        return f"{group} ({parsed.kennung})"
    return group


def build_signal_rows(
    house: dict,
    components: dict,
    *,
    inbox: dict[str, dict[str, Any]] | None = None,
    published: dict[str, dict[str, Any]] | None = None,
    fetched_at: str | None = None,
    include_heartbeat: bool = True,
) -> list[SignalRow]:
    """Rows for every activated binding (read + write) plus optional heartbeats."""
    inbox = inbox if inbox is not None else {}
    published = published if published is not None else {}
    rows: list[SignalRow] = []

    def _add(sig: Signal, direction: Direction) -> None:
        kind = field_kind(sig.ehal_id)
        if direction == "read":
            match_kind, match_text = _read_match(sig.ehal_id, inbox)
        else:
            match_kind, match_text = _write_match(sig.ehal_id, published, fetched_at)
        rows.append(
            SignalRow(
                ehal_id=sig.ehal_id,
                direction=direction,
                meaning=_meaning_for(kind),
                entity_label=_entity_label(sig.group, sig.ehal_id),
                required_by=_functions_for_kind(kind),
                match_kind=match_kind,
                match_text=match_text,
                group=sig.group,
                digital=sig.digital,
            )
        )

    for sig in read_signals_from_docs(house, components):
        _add(sig, "read")
    for sig in write_signals_from_docs(house, components):
        _add(sig, "write")
    if include_heartbeat:
        _add(heartbeat_signal(), "read")
        _add(heartbeat_write_signal(), "write")

    rows.sort(key=lambda r: (r.group, r.direction, r.ehal_id))
    return rows


def signals_for_export(
    house: dict,
    components: dict,
    *,
    mode: Literal["needed", "all"] = "needed",
) -> tuple[list[Signal], list[Signal]]:
    """Return (read_signals, write_signals) for VO/VI export.

    ``needed`` = activated bindings (+ heartbeats).
    ``all`` = same for now (role catalog expansion lands with Binding P3 polish);
    reserved so the UI toggle is stable.
    """
    reads = list(read_signals_from_docs(house, components))
    writes = list(write_signals_from_docs(house, components))
    reads.append(heartbeat_signal())
    writes.append(heartbeat_write_signal())
    _ = mode  # reserved: expand from role JSON when "all" grows
    return reads, writes

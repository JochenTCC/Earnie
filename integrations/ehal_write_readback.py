"""Per-backend read-back of written probes (split from ehal_write_test)."""
from __future__ import annotations

from integrations.ehal_write_test_ref import live

from typing import Any
from integrations.ehal_write_test_bounds import (
    LOXONE_KW_WRITE_FIELDS,
    probe_kind,
)
from integrations.loxone_adapter import EVCS_MODE_VALUES
from integrations.ehal_write_probes import (
    _publish_id_for_probe,
)


def _read_back_ha(field: str) -> Any | None:
    """HA is push-only (Binding P5e): read back from published status.json."""
    return _read_back_ha_push(field)


def _read_back_ha_push(field: str) -> Any | None:
    from integrations.ehal_write import load_published_records, published_fetched_at

    if not published_fetched_at():
        return None
    qid = _publish_id_for_probe(str(field))
    if not qid:
        return None
    rec = load_published_records().get(qid)
    if not rec:
        return None
    raw = rec.get("value")
    kind = probe_kind(field)
    if kind == "set_ess_mode":
        return _coerce_ess_mode_echo(raw)
    if kind == "set_evcs_mode":
        try:
            code = int(float(raw))
        except (TypeError, ValueError):
            return None
        for name, val in EVCS_MODE_VALUES.items():
            if int(val) == code:
                return name
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _read_back_loxone(field: str) -> Any | None:
    """Q7 callback-only: published ledger value once the Miniserver has fetched.

    No Merker HTTP echo. True VO value-echo is deferred to 2.+1.
    """
    from integrations.ehal_write import load_published_records, published_fetched_at

    if not published_fetched_at():
        return None
    qid = _publish_id_for_probe(str(field))
    if not qid:
        return None
    rec = load_published_records().get(qid)
    if not rec:
        return None
    raw = rec.get("value")
    kind = probe_kind(field)
    if kind == "set_ess_mode":
        return _coerce_ess_mode_echo(raw)
    if kind == "set_evcs_mode":
        try:
            code = int(float(raw))
        except (TypeError, ValueError):
            return None
        for name, val in EVCS_MODE_VALUES.items():
            if int(val) == code:
                return name
        return None
    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return None
    if kind in LOXONE_KW_WRITE_FIELDS:
        # Ledger stores the wire (kW) value from publish; probe compares in W.
        from ehal.field_registry import apply_loxone_read, loxone_spec

        spec = loxone_spec(kind)
        if spec is None:
            raise KeyError(f"no loxone conversion for echo field {kind!r}")
        converted = apply_loxone_read(numeric, spec)
        if converted is None:
            raise ValueError(f"loxone echo omitted for {kind} raw={numeric!r}")
        return converted
    return numeric


def _coerce_ess_mode_echo(raw: Any) -> int | None:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        text = str(raw or "").strip().lower()
        if text in ("automatik", "auto", "0"):
            return 0
        return None

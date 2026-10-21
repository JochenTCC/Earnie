"""Probe selection, clamping and write dispatch (split from ehal_write_test)."""
from __future__ import annotations

from integrations.ehal_write_test_ref import live

from datetime import datetime, timezone
from typing import Any
from ehal import EHAL_SCHEMA_VERSION, EhalWriteError
from integrations.ehal_debug_mapping import (
    PLANT_LIVE_WRITE_FIELDS,
    ha_setpoint_mapping,
    loxone_write_field_to_io,
)
from integrations.ehal_write_test_bounds import (
    FORCE_ESS_ACTIVE_POWER,
    LOXONE_KW_WRITE_FIELDS,
    SAFE_PROBE_FIELDS,
    WriteTestClampError,
    canonical_probe_field,
    clamp_probe_value,
    probe_kind,
)


def _openems_mapped_targets() -> dict[str, str]:
    adapter = live.ehal_live.get_openems_adapter()
    caps = adapter.capabilities()
    out: dict[str, str] = {}
    if caps.get("supports_ess_write"):
        for field in PLANT_LIVE_WRITE_FIELDS:
            out[field] = f"openems:{field}"
    if caps.get("supports_evcs_current"):
        out["set_evcs_max_current"] = "openems:set_evcs_max_current"
    return out


def _ha_mapped_targets() -> dict[str, str]:
    from integrations.ehal_debug_mapping import expected_live_write_fields

    adapter = live.ehal_live.get_ha_adapter()
    entities = dict(adapter.cfg.entities)
    flat = ha_setpoint_mapping(entities)
    out: dict[str, str] = dict(flat)
    for field in expected_live_write_fields(network_backend=False):
        addr = str(entities.get(field) or "").strip()
        if addr:
            out[field] = addr
    # Push transport stores activation keys only (empty values): the target is the
    # qualified EHAL ID published on ``status.json``.
    for qid in adapter.cfg.setpoint_qids.values():
        out.setdefault(qid, qid)
    return out


def _loxone_mapped_targets() -> dict[str, str]:
    raw = loxone_write_field_to_io()
    out: dict[str, str] = {}
    for field, io_name in raw.items():
        name = str(field or "").strip()
        marker = str(io_name or "").strip()
        if name and marker and name not in out:
            out[name] = marker
    return out


def allowed_probe_fields(*, force_ess_active: bool = False) -> list[str]:
    """All mapped Live-Schreiben fields (incl. ``set_ess_active_power``).

    ``force_ess_active`` is kept for callers; listing no longer hides active power —
    Schreibtest still requires Force to *send* those rows (clamp + UI).
    """
    del force_ess_active  # listing is independent of Force unlock
    from integrations.ehal_debug_mapping import expected_live_write_fields

    mapped = live.mapped_write_targets()
    network = bool(live.ehal_live.is_ehal_network_backend())
    ordered = expected_live_write_fields(network_backend=network)
    fields: list[str] = []
    seen: set[str] = set()
    for field in ordered:
        if field not in mapped or field in seen:
            continue
        seen.add(field)
        fields.append(field)
    for field in sorted(mapped):
        if field in seen:
            continue
        kind = probe_kind(field)
        if kind.startswith("set_") or kind in SAFE_PROBE_FIELDS or kind == "set_enable":
            seen.add(field)
            fields.append(field)
    return fields


def default_ev_nominal_a() -> float | None:
    """Best-effort EV nominal current (A) from first EV consumer, else None."""
    from integrations.ehal_debug_mapping import _all_live_consumers, _consumer_is_ev
    from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere

    for consumer in _all_live_consumers():
        if not _consumer_is_ev(consumer):
            continue
        try:
            voltage_v, phases = ev_nominal_power_conversion(consumer)
            nom_kw = float(consumer.get("nominal_power_kw") or 0.0)
            if nom_kw <= 0:
                continue
            return float(kw_to_ampere(nom_kw, voltage_v=voltage_v, phases=phases))
        except (TypeError, ValueError, KeyError):
            continue
    return None


def build_probe_setpoint(field: str, value: Any, *, adapter_id: str) -> dict[str, Any]:
    return build_probes_setpoint({field: value}, adapter_id=adapter_id)


def build_probes_setpoint(
    values: dict[str, Any], *, adapter_id: str
) -> dict[str, Any]:
    """Plant-flat / EV setpoint document (no entity-scoped / flex keys)."""
    from ehal.ess_fields import is_ess_entity_scoped_field
    from ehal.flex_fields import flex_field_kind

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    doc: dict[str, Any] = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter_id,
    }
    for field, value in values.items():
        name = canonical_probe_field(field)
        if is_ess_entity_scoped_field(name) or flex_field_kind(name):
            continue
        doc[probe_kind(field)] = value
    return doc


def clamp_probe_values(
    values: dict[str, Any],
    *,
    max_power_kw: float,
    ev_nominal_a: float | None = None,
    force_ess_active: bool = False,
) -> dict[str, Any]:
    """Clamp a batch of probe fields; empty input raises WriteTestClampError."""
    if not values:
        raise WriteTestClampError("Keine Sollwerte zum Schreiben ausgewählt.")
    out: dict[str, Any] = {}
    for field, value in values.items():
        key = str(field or "").strip()
        out[key] = clamp_probe_value(
            key,
            value,
            max_power_kw=max_power_kw,
            ev_nominal_a=ev_nominal_a,
            force_ess_active=force_ess_active,
        )
    return out


def _dispatch_probe_writes(clamped: dict[str, Any]) -> EhalWriteError | None:
    from ehal.ess_fields import is_ess_entity_scoped_field
    from ehal.flex_fields import flex_field_kind

    entity_scoped: dict[str, float] = {}
    flex_fields: dict[str, float] = {}
    adapter_values: dict[str, Any] = {}
    for field, value in clamped.items():
        name = canonical_probe_field(field)
        if is_ess_entity_scoped_field(name):
            entity_scoped[name] = float(value)
            continue
        if flex_field_kind(name):
            flex_fields[name] = float(value)
            continue
        adapter_values[field] = value

    error: EhalWriteError | None = None
    if adapter_values:
        adapter = live.ehal_live.get_adapter()
        setpoint = build_probes_setpoint(
            adapter_values, adapter_id=str(adapter.cfg.adapter_id)
        )
        payload = {
            k: v
            for k, v in setpoint.items()
            if k not in ("schema_version", "ts", "adapter_id")
        }
        if payload:
            error = adapter.write_setpoints(setpoint)
    if error is None and entity_scoped:
        error = _write_entity_scoped_probes(entity_scoped)
    if error is None and flex_fields:
        error = _write_flex_enable_probes(flex_fields)
    return error


def _write_entity_scoped_probes(fields: dict[str, float]) -> EhalWriteError | None:
    if live.ehal_live.is_ha_backend():
        adapter = live.ehal_live.get_ha_adapter()
        writer = getattr(adapter, "write_mapped_fields", None)
        if callable(writer):
            return writer(fields)
        return adapter.write_setpoints(
            build_probes_setpoint(fields, adapter_id=str(adapter.cfg.adapter_id))
        )
    if live.ehal_live.is_openems_backend():
        return None
    return _write_loxone_mapped_probes(fields)


def _write_flex_enable_probes(fields: dict[str, float]) -> EhalWriteError | None:
    if live.ehal_live.is_ehal_network_backend():
        return None
    return _write_loxone_mapped_probes(fields)


def _marker_for_probe_field(field: str, targets: dict[str, str]) -> str:
    direct = str(targets.get(field) or "").strip()
    if direct:
        return direct
    canon = canonical_probe_field(field)
    for key, marker in targets.items():
        if canonical_probe_field(key) == canon and str(marker or "").strip():
            return str(marker).strip()
    return ""


def _loxone_probe_wire_value(field: str, value: Any) -> float:
    from ehal.field_registry import require_loxone_write

    kind = probe_kind(field)
    if kind == FORCE_ESS_ACTIVE_POWER:
        return float(require_loxone_write("set_ess_active_power", float(value)))
    if kind in LOXONE_KW_WRITE_FIELDS:
        return float(require_loxone_write(kind, float(value)))
    return float(value)


def _publish_id_for_probe(field: str) -> str:
    """Qualified EHAL ID for a Schreibtest probe field (plant / entity-scoped / consumer)."""
    from ehal.ess_fields import parse_ess_entity_scoped
    from ehal.qualified_ids import (
        NAMESPACES,
        field_kind,
        qualified_consumer_id,
        qualified_plant_id,
    )
    from integrations.ehal_debug_mapping import (
        PLANT_LIVE_WRITE_FIELDS,
        _consumer_type_for_qualified_id,
        _all_live_consumers,
        _consumer_is_ev,
    )

    raw = str(field or "").strip()
    if not raw:
        return ""
    if parse_ess_entity_scoped(raw):
        return raw
    if raw in PLANT_LIVE_WRITE_FIELDS or field_kind(raw) in PLANT_LIVE_WRITE_FIELDS:
        return qualified_plant_id(raw)
    ns = raw.split(".", 1)[0]
    if ns in NAMESPACES and raw.count(".") >= 2:
        return raw
    if ":" not in raw:
        return canonical_probe_field(raw)
    cid, rest = raw.split(":", 1)
    cid = cid.strip()
    kind = field_kind(rest)
    consumer: dict | None = None
    for item in _all_live_consumers():
        if str(item.get("id") or "").strip() == cid:
            consumer = item
            break
    if consumer is None:
        ctype = "ev" if kind.startswith("set_evcs_") else ""
        return qualified_consumer_id(cid, ctype, kind) if cid and kind else raw
    ctype = _consumer_type_for_qualified_id(consumer)
    if _consumer_is_ev(consumer) or kind.startswith("set_evcs_"):
        ctype = "ev"
    return qualified_consumer_id(cid, ctype, kind)


def _write_loxone_mapped_probes(fields: dict[str, Any]) -> EhalWriteError | None:
    from integrations.loxone_writes import _publish_setpoint_traced

    targets = live.mapped_write_targets()
    for field, value in fields.items():
        qid = _publish_id_for_probe(str(field))
        if not qid:
            continue
        # Activation key may have an empty Merker (Q8); publish still goes out.
        marker = _marker_for_probe_field(field, targets) or qid
        wire = _loxone_probe_wire_value(field, value)
        _publish_setpoint_traced(qid, wire, io_name=marker)
    return None

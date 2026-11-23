"""Powerstation setpoint writes of the live cycle (Pattern-B ``ess.{slug}.set_*`` fields).

Split out of ``optimizer.powerstation_live`` (still re-exported there, incl. the shared
``_last_powerstation_sent`` dict).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import config

# Same logger as before the split (log filters and caplog tests key on it).
logger = logging.getLogger("optimizer.powerstation_live")


def _facade():
    """``optimizer.powerstation_live``: tests patch ``_planning_powerstations`` and
    ``_resolve_marker`` there, so the writers here look both up through it."""
    from optimizer import powerstation_live

    return powerstation_live


def _planning_powerstations() -> list[dict]:
    """Planning powerstations, looked up through ``optimizer.powerstation_live``."""
    return _facade()._planning_powerstations()


# Last written powerstation Merker values for Loxone status.json, keyed by
# Pattern-B ``ess.{slug}.{kind}`` (incl. Quellenwahl). Never a flat house limit /
# mode key — those belong to the house battery.
_last_powerstation_sent: dict[str, float] = {}


def last_powerstation_sent() -> dict[str, float]:
    return dict(_last_powerstation_sent)


def _status_key(field_key: str, kind: str) -> str:
    """Key under which a written powerstation value appears in ``status.json``."""
    from ehal.ess_fields import parse_ess_entity_scoped

    if parse_ess_entity_scoped(field_key):
        return field_key
    return kind or field_key


def _physical_powerstation_ids() -> list[str]:
    """Ids of non-virtual powerstations (charge refresh targets)."""
    from house_config.powerstation import is_virtual_powerstation

    ids: list[str] = []
    for ps in _planning_powerstations():
        if not isinstance(ps, dict) or is_virtual_powerstation(ps):
            continue
        ps_id = str(ps.get("id") or "").strip()
        if ps_id:
            ids.append(ps_id)
    return ids


def _standby_backup_physical_ids() -> list[str]:
    """Ids of physical ``standby_backup`` packs (source_select refresh targets)."""
    from house_config.powerstation import (
        BACKING_PHYSICAL,
        ROLE_STANDBY_BACKUP,
        is_powerstation,
    )

    ids: list[str] = []
    for ps in _planning_powerstations():
        if not isinstance(ps, dict) or not is_powerstation(ps):
            continue
        if str(ps.get("role") or "").strip().lower() != ROLE_STANDBY_BACKUP:
            continue
        if str(ps.get("backing") or "").strip().lower() != BACKING_PHYSICAL:
            continue
        ps_id = str(ps.get("id") or "").strip()
        if ps_id:
            ids.append(ps_id)
    return ids


def cycle_powerstation_charge_kw(
    reserve_charges: dict[str, float],
    standby_charges: dict[str, float],
) -> dict[str, float]:
    """Charge kW for every physical PS with a charge binding (idle → 0).

    Ensures sticky Loxone Merkers are refreshed every optimize cycle, not only
    when a reserve/standby plan is active.
    """
    out: dict[str, float] = {}
    for ps_id in _physical_powerstation_ids():
        if _binding_for_ps(ps_id, "set_ess_charge_power_limit"):
            out[ps_id] = 0.0
    for ps_id, kw in (reserve_charges or {}).items():
        key = str(ps_id).strip()
        if key:
            out[key] = max(0.0, float(kw))
    for ps_id, kw in (standby_charges or {}).items():
        key = str(ps_id).strip()
        if key:
            out[key] = max(0.0, float(kw))
    return out


def cycle_standby_source_selects(
    standby_sources: dict[str, int],
) -> dict[str, int]:
    """``source_select`` for standby packs with a binding (idle → grid)."""
    from optimizer.powerstation_standby import SOURCE_GRID

    out: dict[str, int] = {}
    for ps_id in _standby_backup_physical_ids():
        if _binding_for_ps(ps_id, "set_ess_source_select"):
            out[ps_id] = SOURCE_GRID
    for ps_id, select in (standby_sources or {}).items():
        key = str(ps_id).strip()
        if key:
            out[key] = 1 if int(select) >= 1 else 0
    return out


def _binding_for_ps(ps_id: str, kind: str) -> str:
    """Resolve Merker/entity or qid from planning powerstation ehal_bindings (Q8)."""
    from ehal.ess_fields import binding_address, ess_field
    from ehal.qualified_ids import qualified_battery_id

    for ps in _planning_powerstations():
        if str(ps.get("id") or "").strip() != ps_id:
            continue
        bindings = ps.get("ehal_bindings")
        if not isinstance(bindings, dict):
            return ""
        addr = binding_address(bindings, ps_id, kind)
        if addr:
            return addr
        flat = str(bindings.get(kind) or "").strip()
        if flat:
            return flat
        key = ess_field(ps_id, kind)
        if key in bindings or kind in bindings:
            return qualified_battery_id(ps_id, kind)
        break
    return ""


def _resolve_marker(field_key: str) -> tuple[str, str]:
    """Return (ehal_kind, merker_name) for a flat or Pattern-B field key."""
    from ehal.ess_fields import ess_field_kind, parse_ess_entity_scoped

    parsed = parse_ess_entity_scoped(field_key)
    if parsed:
        slug, kind = parsed
        return kind, _binding_for_ps(slug, kind)
    kind = ess_field_kind(field_key) or str(field_key).strip()
    return kind, _binding_for_ps("", kind)


def _utc_ts() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_error_kinds(field_keys: list[str]) -> list[str]:
    """Map Pattern-B / flat keys to plant-flat kinds (write_error.schema enum)."""
    from ehal.ess_fields import ess_field_kind, parse_ess_entity_scoped

    kinds: list[str] = []
    seen: set[str] = set()
    for key in field_keys:
        parsed = parse_ess_entity_scoped(key)
        kind = parsed[1] if parsed else (ess_field_kind(key) or str(key).strip())
        if kind and kind not in seen:
            seen.add(kind)
            kinds.append(kind)
    return kinds


def _persist_ps_write_error(
    *,
    adapter_id: str,
    failed_fields: list[str],
    message: str,
) -> None:
    """Persist missing-binding / write failures for powerstation setpoints."""
    kinds = _write_error_kinds(failed_fields)
    if not kinds:
        return
    from ehal import EHAL_SCHEMA_VERSION, validate_write_error
    from integrations import ehal_live

    detail = "; ".join(failed_fields)
    full_message = f"{message}: {detail}" if detail else message
    try:
        error = validate_write_error(
            {
                "schema_version": EHAL_SCHEMA_VERSION,
                "ts": _utc_ts(),
                "adapter_id": adapter_id,
                "failed_fields": kinds,
                "message": full_message,
                "retryable": True,
            }
        )
        ehal_live.persist_write_error(error)
    except Exception as exc:  # noqa: BLE001
        logger.warning("powerstation write-error persist failed: %s", exc)


def _ha_remap_powerstation_fields(
    fields: dict[str, float],
    entities: dict[str, str],
) -> tuple[dict[str, float], list[str]]:
    """Map Pattern-B keys to HA entities; no plant-flat fallback."""
    remapped: dict[str, float] = {}
    missing: list[str] = []
    for key, value in fields.items():
        if key in entities:
            remapped[key] = value
            continue
        missing.append(key)
        logger.warning(
            "no HA entity for powerstation field %s — skip (no plant-flat fallback)",
            key,
        )
    return remapped, missing

def _write_powerstation_ha(fields: dict[str, float], ehal_live: Any) -> list:
    adapter = ehal_live.get_ha_adapter()
    remapped, missing = _ha_remap_powerstation_fields(fields, adapter.cfg.entities)
    error = None
    if remapped:
        writer = getattr(adapter, "write_mapped_fields", None)
        error = writer(remapped) if callable(writer) else adapter.write_setpoints(remapped)
    if missing:
        _persist_ps_write_error(
            adapter_id=str(getattr(adapter.cfg, "adapter_id", None) or "ha"),
            failed_fields=missing,
            message=(
                "Powerstation ESS fields have no own HA binding; "
                "refusing plant-flat house-battery fallback"
            ),
        )
    elif error is not None:
        logger.warning("physical powerstation HA setpoints failed: %s", error)
        ehal_live.persist_write_error(error)
    return []


def _loxone_ps_wire_value(kind: str, value_w: float) -> float:
    """EHAL W / mode → Loxone Merker number (kW for power fields)."""
    from ehal.field_registry import require_loxone_write

    if kind in (
        "set_ess_active_power",
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
    ):
        return float(require_loxone_write(kind, float(value_w)))
    return float(value_w)


def _write_powerstation_loxone(fields: dict[str, float]) -> list:
    from integrations.loxone_comm_trace import LoxoneWriteRecord
    from integrations.ehal_live import publish_setpoint_traced

    records: list[LoxoneWriteRecord] = []
    missing: list[str] = []
    for field_key, value_w in fields.items():
        kind, marker = _facade()._resolve_marker(field_key)
        if not marker:
            logger.warning(
                "no Merker/entity for powerstation field %s — skip",
                field_key,
            )
            missing.append(field_key)
            continue
        send_val = _loxone_ps_wire_value(kind, float(value_w))
        status_key = _status_key(field_key, kind)
        _last_powerstation_sent[status_key] = send_val
        records.append(
            publish_setpoint_traced(status_key, send_val, io_name=marker)
        )
    if missing:
        _persist_ps_write_error(
            adapter_id="loxone",
            failed_fields=missing,
            message=(
                "Powerstation ESS fields have no own Merker; "
                "refusing plant-flat house-battery fallback"
            ),
        )
    return records


def _write_powerstation_fields(fields: dict[str, float]) -> list:
    """Write Pattern-B ESS fields; return Loxone write records (empty on HA/skip)."""
    if not fields:
        return []
    try:
        from integrations import ehal_live
        from runtime_store.shadow.hooks import should_invoke_setpoint_writes
    except Exception as exc:  # noqa: BLE001
        logger.warning("powerstation write skipped: %s", exc)
        return []
    if not should_invoke_setpoint_writes(silent=config.is_loxone_silent_mode()):
        return []

    if ehal_live.is_ha_backend():
        return _write_powerstation_ha(fields, ehal_live)

    if ehal_live.is_ehal_network_backend():
        return []

    return _write_powerstation_loxone(fields)


def build_cycle_powerstation_fields(
    charge_kw_by_id: dict[str, float],
    source_by_id: dict[str, int] | None = None,
) -> dict[str, float]:
    """All mapped ``ess.{slug}.set_*`` for physical packs (idle defaults).

    Charge from ``charge_kw_by_id`` (kW); discharge/active → 0 W; mode → 0;
    source_select from ``source_by_id`` (default grid). Unmapped kinds omitted.
    """
    from ehal.ess_fields import ess_field

    sources = source_by_id or {}
    ids: set[str] = set(_physical_powerstation_ids())
    ids.update(str(k).strip() for k in (charge_kw_by_id or {}) if str(k).strip())
    ids.update(str(k).strip() for k in sources if str(k).strip())

    fields: dict[str, float] = {}
    for ps_id in sorted(ids):
        charge_w = max(0.0, float(charge_kw_by_id.get(ps_id, 0.0))) * 1000.0
        if _binding_for_ps(ps_id, "set_ess_charge_power_limit"):
            fields[ess_field(ps_id, "set_ess_charge_power_limit")] = charge_w
        if _binding_for_ps(ps_id, "set_ess_discharge_power_limit"):
            fields[ess_field(ps_id, "set_ess_discharge_power_limit")] = 0.0
        if _binding_for_ps(ps_id, "set_ess_mode"):
            fields[ess_field(ps_id, "set_ess_mode")] = 0.0
        if _binding_for_ps(ps_id, "set_ess_active_power"):
            fields[ess_field(ps_id, "set_ess_active_power")] = 0.0
        if _binding_for_ps(ps_id, "set_ess_source_select"):
            sel = int(sources.get(ps_id, 0))
            fields[ess_field(ps_id, "set_ess_source_select")] = (
                1.0 if sel >= 1 else 0.0
            )
    return fields


def planned_powerstation_loxone_sent(
    charge_kw_by_id: dict[str, float],
    source_by_id: dict[str, int] | None = None,
) -> dict[str, float]:
    """Merker → wire value for Silent Live-Schreiben / ``loxone_sent`` (no publish)."""
    out: dict[str, float] = {}
    for field_key, value_w in build_cycle_powerstation_fields(
        charge_kw_by_id, source_by_id
    ).items():
        kind, marker = _facade()._resolve_marker(field_key)
        if not marker:
            continue
        out[marker] = _loxone_ps_wire_value(kind, float(value_w))
    return out


def write_cycle_powerstation_setpoints(
    charge_kw_by_id: dict[str, float],
    source_by_id: dict[str, int] | None = None,
) -> list:
    """Refresh every mapped PS ``set_*`` Merker; return Loxone write records."""
    fields = build_cycle_powerstation_fields(charge_kw_by_id, source_by_id)
    if fields:
        logger.info(
            "cycle powerstation setpoints: %s",
            {k: fields[k] for k in sorted(fields)},
        )
    return _write_powerstation_fields(fields)


def write_physical_powerstation_charges(charge_kw_by_id: dict[str, float]) -> list:
    """Compat: charge (+ discharge=0 if mapped) only — prefer cycle writer."""
    from ehal.ess_fields import ess_field

    fields: dict[str, float] = {}
    for ps_id, charge_kw in (charge_kw_by_id or {}).items():
        slug = str(ps_id).strip()
        if not slug:
            continue
        fields[ess_field(slug, "set_ess_charge_power_limit")] = (
            max(0.0, float(charge_kw)) * 1000.0
        )
        if _binding_for_ps(slug, "set_ess_discharge_power_limit"):
            fields[ess_field(slug, "set_ess_discharge_power_limit")] = 0.0
    return _write_powerstation_fields(fields)


def write_standby_source_selects(source_by_id: dict[str, int]) -> list:
    """Compat: source_select only — prefer cycle writer."""
    from ehal.ess_fields import ess_field

    fields: dict[str, float] = {}
    for ps_id, select in (source_by_id or {}).items():
        slug = str(ps_id).strip()
        if not slug:
            continue
        fields[ess_field(slug, "set_ess_source_select")] = (
            1.0 if int(select) >= 1 else 0.0
        )
    return _write_powerstation_fields(fields)

"""Live-cycle hooks for 2.7.g powerstation reserves and 2.7.h standby-backup."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import config
from house_config.powerstation import MODE_RESERVE
from optimizer.powerstation_reserve import (
    advance_reserve_after_slot,
    collect_active_reserves,
    detect_trigger_from_power,
    physical_reserves,
    prepare_battery_params_for_reserves,
    virtual_asap_charge_kwh,
)
from runtime_store.powerstation_reserves import set_trigger

logger = logging.getLogger(__name__)

# Last written powerstation Merker values for Loxone status.json, keyed by
# Pattern-B ``ess.{slug}.{kind}`` (incl. Quellenwahl). Never a flat house limit /
# mode key — those belong to the house battery.
_last_powerstation_sent: dict[str, float] = {}


def last_powerstation_sent() -> dict[str, float]:
    return dict(_last_powerstation_sent)


def _status_key(field_key: str, kind: str) -> str:
    """Key under which a written powerstation value appears in ``status.json``."""
    from ehal.ess_fields import parse_ess_pattern_b

    if parse_ess_pattern_b(field_key):
        return field_key
    return kind or field_key

def _planning_powerstations() -> list[dict]:
    try:
        resolved = config.get_resolved_runtime_settings()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(resolved, dict):
        return []
    value = resolved.get("_planning_powerstations")
    return list(value) if isinstance(value, list) else []


def _reserve_appliances() -> list[dict]:
    from house_config.powerstation import MODE_RESERVE

    try:
        appliances = config.get_appliances()
    except Exception:  # noqa: BLE001
        logger.warning("powerstation_live: get_appliances failed")
        return []
    return [
        a for a in appliances if str(a.get("mode") or "") == MODE_RESERVE
    ]


def load_active_reserves() -> list[dict[str, Any]]:
    return collect_active_reserves(
        appliances=_reserve_appliances(),
        powerstations=_planning_powerstations(),
    )


def apply_reserves_to_battery_params(
    battery_params: dict | list[dict],
    reserves: list[dict[str, Any]] | None = None,
) -> dict | list[dict]:
    active = reserves if reserves is not None else load_active_reserves()
    return prepare_battery_params_for_reserves(battery_params, active)


def _consumers_by_id() -> dict[str, dict]:
    try:
        consumers = config.get_flexible_consumers()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict] = {}
    for consumer in consumers or []:
        if not isinstance(consumer, dict):
            continue
        cid = str(consumer.get("id") or "").strip()
        if cid:
            out[cid] = consumer
    return out


def _telemetry_number(telemetry: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(telemetry, dict) or key not in telemetry:
        return None
    raw = telemetry.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _digital_active_from_consumer(consumer: dict) -> bool | None:
    """Read ``sens_consumer_active`` Merker when mapped; None if unavailable."""
    from settings.ehal_marker_resolve import marker_sens_consumer_active

    io_name = marker_sens_consumer_active(consumer)
    if not io_name:
        return None
    try:
        from integrations.loxone_client import fetch_loxone_generic_value

        raw = fetch_loxone_generic_value(io_name)
    except Exception:  # noqa: BLE001
        return None
    if raw is None:
        return None
    try:
        return float(raw) >= 0.5
    except (TypeError, ValueError):
        return None


def _live_power_kw(consumer: dict) -> float | None:
    try:
        from integrations.loxone_client import resolve_consumer_live_power_kw

        return resolve_consumer_live_power_kw(consumer)
    except Exception:  # noqa: BLE001
        return None


def _first_telemetry_number(
    telemetry: dict[str, Any] | None, *keys: str
) -> float | None:
    for key in keys:
        value = _telemetry_number(telemetry, key)
        if value is not None:
            return value
    return None


def appliance_run_signal_active(
    appliance_id: str,
    *,
    telemetry: dict[str, Any] | None,
    consumers_by_id: dict[str, dict] | None = None,
) -> bool:
    """OR trigger: digital active, power threshold, or telemetry keys (2.7.p)."""
    cid = str(appliance_id or "").strip()
    if not cid:
        return False
    # Exchange form consumer.* (2.7.n); flex.* remains an accepted storage/legacy alias.
    digital = _first_telemetry_number(
        telemetry,
        f"consumer.{cid}.sens_consumer_active",
        f"flex.{cid}.sens_consumer_active",
    )
    if digital is not None and digital >= 0.5:
        return True
    power = _first_telemetry_number(
        telemetry,
        f"consumer.{cid}.sens_power_act",
        f"flex.{cid}.sens_power_act",
    )
    if detect_trigger_from_power(power):
        return True
    consumer = (consumers_by_id or {}).get(cid)
    if consumer is None:
        return False
    live_digital = _digital_active_from_consumer(consumer)
    if live_digital is True:
        return True
    live_power = _live_power_kw(consumer)
    return detect_trigger_from_power(live_power)


def sync_triggers_from_telemetry(
    telemetry: dict[str, Any] | None,
    reserves: list[dict[str, Any]],
) -> None:
    """Release when any attached consumer runs (digital OR power OR PS out).

    Inactive while discharging does **not** clear the latch — leftover
    ``stored_kwh`` keeps draining until empty, then refill opens (2.7.p).
    """
    consumers = _consumers_by_id()
    for reserve in reserves:
        ps_id = str(reserve.get("powerstation_id") or "")
        if not ps_id:
            continue
        appliance_ids = [
            str(cid).strip()
            for cid in (reserve.get("appliance_ids") or [])
            if str(cid or "").strip()
        ]
        if not appliance_ids:
            singular = str(reserve.get("appliance_id") or "").strip()
            if singular:
                appliance_ids = [singular]
        triggered = any(
            appliance_run_signal_active(
                appliance_id, telemetry=telemetry, consumers_by_id=consumers
            )
            for appliance_id in appliance_ids
        )
        if not triggered:
            # Physical pack out power as free meter (2.7.g bonus).
            power = _telemetry_number(telemetry, f"ess.{ps_id}.sens_ess_power")
            triggered = detect_trigger_from_power(power)
        if triggered:
            set_trigger(ps_id, active=True)


def advance_virtual_reserves_from_plan(
    *,
    battery_plan_kw: float,
    dt_h: float,
    reserves: list[dict[str, Any]],
) -> None:
    """Attribute house charge/discharge to virtual carve-outs after a slot plan."""
    asap_total = virtual_asap_charge_kwh(reserves)
    charge_kw = max(0.0, float(battery_plan_kw))
    discharge_kw = max(0.0, -float(battery_plan_kw))
    charge_kwh = charge_kw * dt_h
    discharge_kwh = discharge_kw * dt_h

    virtual = [r for r in reserves if r.get("backing") == "virtual"]
    if not virtual:
        return

    # Equal-share ASAP charge attribution (priority deferred to 2.+1).
    needing = [r for r in virtual if float(r.get("asap_charge_kwh") or 0.0) > 1e-9]
    if needing and charge_kwh > 1e-9:
        share = charge_kwh / len(needing)
        for reserve in needing:
            advance_reserve_after_slot(
                powerstation_id=str(reserve["powerstation_id"]),
                charged_kwh=share,
            )

    discharging = [
        r for r in virtual if r.get("state") == "discharging" or r.get("trigger_active")
    ]
    if discharging and discharge_kwh > 1e-9:
        share = discharge_kwh / len(discharging)
        for reserve in discharging:
            advance_reserve_after_slot(
                powerstation_id=str(reserve["powerstation_id"]),
                discharged_kwh=share,
            )
    elif discharging:
        # Trigger without measured house discharge: hand off target over runtime.
        for reserve in discharging:
            target = float(reserve.get("target_kwh") or 0.0)
            runtime_h = max(0.25, target / max(0.1, float(reserve.get("target_kwh") or 0.1)))
            # Fall back: consume a slot share of target.
            step = target * min(1.0, dt_h / max(runtime_h, dt_h))
            advance_reserve_after_slot(
                powerstation_id=str(reserve["powerstation_id"]),
                discharged_kwh=step,
            )

    _ = asap_total  # documented equal-share uses needing list above


def physical_charge_setpoints_kw(
    reserves: list[dict[str, Any]],
) -> dict[str, float]:
    """per powerstation_id → charge kW (0 when standby/full or discharging)."""
    out: dict[str, float] = {}
    for reserve in physical_reserves(reserves):
        ps_id = str(reserve["powerstation_id"])
        asap = float(reserve.get("asap_charge_kwh") or 0.0)
        max_charge = float(reserve.get("max_charge_power_kw") or 0.0)
        if asap > 1e-9 and max_charge > 0.0:
            out[ps_id] = max_charge
        else:
            out[ps_id] = 0.0
    return out


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


def appliance_is_reserve_mode(appliance: dict) -> bool:
    return str(appliance.get("mode") or "") == MODE_RESERVE


def _binding_for_ps(ps_id: str, kind: str) -> str:
    """Resolve Merker/entity address from planning powerstation ehal_bindings."""
    from ehal.ess_fields import binding_address

    for ps in _planning_powerstations():
        if str(ps.get("id") or "").strip() != ps_id:
            continue
        bindings = ps.get("ehal_bindings")
        addr = binding_address(bindings if isinstance(bindings, dict) else {}, ps_id, kind)
        if addr:
            return addr
        if isinstance(bindings, dict):
            flat = str(bindings.get(kind) or "").strip()
            if flat:
                return flat
        break
    return ""


def _resolve_marker(field_key: str) -> tuple[str, str]:
    """Return (ehal_kind, merker_name) for a flat or Pattern-B field key."""
    from ehal.ess_fields import ess_field_kind, parse_ess_pattern_b

    parsed = parse_ess_pattern_b(field_key)
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
    from ehal.ess_fields import ess_field_kind, parse_ess_pattern_b

    kinds: list[str] = []
    seen: set[str] = set()
    for key in field_keys:
        parsed = parse_ess_pattern_b(key)
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
            "2.7.h: no HA entity for powerstation field %s — skip (no plant-flat fallback)",
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
    from integrations.loxone_writes import _publish_setpoint_traced

    records: list[LoxoneWriteRecord] = []
    missing: list[str] = []
    for field_key, value_w in fields.items():
        kind, marker = _resolve_marker(field_key)
        if not marker:
            logger.warning(
                "2.7.h: no Merker/entity for powerstation field %s — skip",
                field_key,
            )
            missing.append(field_key)
            continue
        send_val = _loxone_ps_wire_value(kind, float(value_w))
        status_key = _status_key(field_key, kind)
        _last_powerstation_sent[status_key] = send_val
        records.append(
            _publish_setpoint_traced(status_key, send_val, io_name=marker)
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
        from runtime_store.shadow.writes import should_invoke_setpoint_writes
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
        kind, marker = _resolve_marker(field_key)
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
            "2.7.g/h cycle powerstation setpoints: %s",
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


def load_standby_packs() -> list[dict[str, Any]]:
    from optimizer.powerstation_standby import collect_standby_packs

    try:
        appliances = config.get_appliances()
    except Exception:  # noqa: BLE001
        appliances = []
    # Also include house-profile consumers for default_power_kw lookup.
    try:
        flex = config.get_flexible_consumers(optimizer_only=False)
    except Exception:  # noqa: BLE001
        flex = []
    by_id: dict[str, dict] = {}
    for item in list(appliances or []) + list(flex or []):
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            by_id[str(item["id"]).strip()] = item
    return collect_standby_packs(
        powerstations=_planning_powerstations(),
        appliances=list(by_id.values()),
    )

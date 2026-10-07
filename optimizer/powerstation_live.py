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

# Last written powerstation Merker values for Loxone status.json (flat + Pattern-B).
_last_powerstation_sent: dict[str, float] = {}

# Plant-flat fallback allowed only for EcoFlow-bridge Quellenwahl (not charge/discharge).
_PLANT_FLAT_ALLOWED_KINDS = frozenset({"set_ess_source_select"})


def last_powerstation_sent() -> dict[str, float]:
    return dict(_last_powerstation_sent)


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


def sync_triggers_from_telemetry(
    telemetry: dict[str, Any] | None,
    reserves: list[dict[str, Any]],
) -> None:
    """Threshold crossing on flex sens_power_act or manual trigger flag."""
    if not isinstance(telemetry, dict):
        return
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
        triggered = False
        for appliance_id in appliance_ids:
            field = f"flex.{appliance_id}.sens_power_act"
            power = telemetry.get(field)
            if detect_trigger_from_power(
                float(power) if power is not None else None
            ):
                triggered = True
                break
        if not triggered:
            # Physical pack out power as free meter (2.7.g bonus).
            power = telemetry.get(f"ess.{ps_id}.sens_ess_power")
            triggered = detect_trigger_from_power(
                float(power) if power is not None else None
            )
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
    # EcoFlow bridge: plant Merker for Quellenwahl only — never charge/discharge.
    if kind not in _PLANT_FLAT_ALLOWED_KINDS:
        return ""
    try:
        from house_config.ehal_bindings import resolve_plant_binding
        from optimizer.live_export_limit import load_house_doc

        return str(resolve_plant_binding(load_house_doc(), kind) or "").strip()
    except Exception:  # noqa: BLE001
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
    """Map Pattern-B keys to HA entities; plant-flat only for source_select."""
    from ehal.ess_fields import ess_field_kind, parse_ess_pattern_b

    remapped: dict[str, float] = {}
    missing: list[str] = []
    for key, value in fields.items():
        if key in entities:
            remapped[key] = value
            continue
        parsed = parse_ess_pattern_b(key)
        kind = parsed[1] if parsed else (ess_field_kind(key) or key)
        if kind in _PLANT_FLAT_ALLOWED_KINDS and kind in entities:
            remapped[kind] = value
            continue
        missing.append(key)
        logger.warning(
            "2.7.h: no HA entity for powerstation field %s — skip (no plant-flat fallback)",
            key,
        )
    return remapped, missing


def _write_powerstation_ha(fields: dict[str, float], ehal_live: Any) -> None:
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


def _write_powerstation_loxone(fields: dict[str, float]) -> None:
    from integrations import loxone_client

    power_kinds = frozenset(
        {"set_ess_charge_power_limit", "set_ess_discharge_power_limit"}
    )
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
        # Loxone ESS markers are kW; EHAL wire values here are W for power fields.
        if kind in power_kinds:
            send_val = max(0.0, float(value_w)) / 1000.0
        else:
            send_val = float(value_w)
        _last_powerstation_sent[kind] = send_val
        loxone_client._send_loxone_value_traced(marker, send_val)
    if missing:
        _persist_ps_write_error(
            adapter_id="loxone",
            failed_fields=missing,
            message=(
                "Powerstation ESS fields have no own Merker; "
                "refusing plant-flat house-battery fallback"
            ),
        )


def _write_powerstation_fields(fields: dict[str, float]) -> None:
    """Write Pattern-B or flat ESS fields via HA mapped write or Loxone Merker."""
    if not fields:
        return
    try:
        from integrations import ehal_live
        from runtime_store.shadow.writes import should_invoke_setpoint_writes
    except Exception as exc:  # noqa: BLE001
        logger.warning("powerstation write skipped: %s", exc)
        return
    if not should_invoke_setpoint_writes(silent=config.is_loxone_silent_mode()):
        return

    if ehal_live.is_ha_backend():
        _write_powerstation_ha(fields, ehal_live)
        return

    if ehal_live.is_ehal_network_backend():
        # OpenEMS: no source_select path for portable packs.
        return

    _write_powerstation_loxone(fields)


def write_physical_powerstation_charges(charge_kw_by_id: dict[str, float]) -> None:
    """Write Pattern-B charge limit; discharge=0 only when that field is mapped.

    EcoFlow / one-way packs must not map ``set_ess_discharge_power_limit`` — do not
    invent a write (or Schreibfehler) for an intentionally absent Merker.
    """
    if not charge_kw_by_id:
        return
    from ehal.ess_fields import ess_field

    fields: dict[str, float] = {}
    for ps_id, charge_kw in charge_kw_by_id.items():
        slug = str(ps_id).strip()
        if not slug:
            continue
        charge_w = max(0.0, float(charge_kw) * 1000.0)
        fields[ess_field(slug, "set_ess_charge_power_limit")] = charge_w
        if _binding_for_ps(slug, "set_ess_discharge_power_limit"):
            fields[ess_field(slug, "set_ess_discharge_power_limit")] = 0.0
    _write_powerstation_fields(fields)


def write_standby_source_selects(source_by_id: dict[str, int]) -> None:
    """Write ``set_ess_source_select`` (0=grid / 1=battery) per standby pack."""
    if not source_by_id:
        return
    from ehal.ess_fields import ess_field

    fields: dict[str, float] = {}
    for ps_id, select in source_by_id.items():
        slug = str(ps_id).strip()
        if not slug:
            continue
        fields[ess_field(slug, "set_ess_source_select")] = (
            1.0 if int(select) >= 1 else 0.0
        )
    _write_powerstation_fields(fields)


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

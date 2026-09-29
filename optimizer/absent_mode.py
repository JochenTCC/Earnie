"""Live-only holiday / absent mode (HK OR EHAL plant sens_absent_mode)."""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

ABSENT_EHAL_FIELD = "sens_absent_mode"

EhalReadState = Literal["unbound", "unreadable", "on", "off"]


def effective_absent_mode(profile_absent: bool, ehal_live: bool | None) -> bool:
    """OR activation: HK force-on or live EHAL true."""
    return bool(profile_absent) or bool(ehal_live)


def ehal_read_state(ehal_live: bool | None, *, bound: bool) -> EhalReadState:
    if not bound:
        return "unbound"
    if ehal_live is None:
        return "unreadable"
    return "on" if ehal_live else "off"


def _split_openems_channel(binding: str) -> tuple[str, str] | None:
    """Parse ``component/ChannelId``; None if the format is invalid."""
    text = str(binding or "").strip()
    if "/" not in text:
        return None
    component, channel = text.split("/", 1)
    component = component.strip()
    channel = channel.strip()
    if not component or not channel:
        return None
    return component, channel


def _read_absent_loxone(binding: str) -> bool | None:
    from integrations import loxone_client
    from integrations.loxone_value_parse import parse_binary_value

    raw = loxone_client.fetch_loxone_generic_value(binding)
    return parse_binary_value(raw)


def _read_absent_ha(binding: str) -> bool | None:
    from integrations.ehal_live import get_ha_adapter
    from integrations.loxone_value_parse import parse_binary_value

    entity_id = str(binding or "").strip()
    try:
        adapter = get_ha_adapter()
    except Exception:
        return None
    mapped = str((adapter.cfg.entities or {}).get(ABSENT_EHAL_FIELD) or "").strip()
    if mapped:
        entity_id = mapped
    if not entity_id:
        return None
    state_doc = adapter.read_state(entity_id)
    raw = state_doc.get("state") if isinstance(state_doc, dict) else state_doc
    return parse_binary_value(raw)


def _read_absent_openems(binding: str) -> bool | None:
    from integrations.ehal_live import get_openems_adapter
    from integrations.loxone_value_parse import parse_binary_value

    parts = _split_openems_channel(binding)
    if parts is None:
        return None
    component, channel = parts
    raw = get_openems_adapter().read_channel(component, channel)
    return parse_binary_value(raw)


def read_ehal_absent_mode(house_doc: dict | None = None) -> tuple[bool | None, bool]:
    """Read plant ``sens_absent_mode`` via the active EHAL backend.

    Returns ``(value, bound)`` where ``value`` is True/False/None (read failure)
    and ``bound`` is whether a plant binding is configured.
    """
    from house_config.ehal_bindings import resolve_plant_binding
    from integrations import ehal_live

    if house_doc is None:
        from integrations.loxone_client import _default_house_profiles_doc

        house_doc = _default_house_profiles_doc()
    binding = resolve_plant_binding(house_doc, ABSENT_EHAL_FIELD)
    if not binding:
        return None, False
    if ehal_live.is_ha_backend():
        return _read_absent_ha(binding), True
    if ehal_live.is_openems_backend():
        return _read_absent_openems(binding), True
    return _read_absent_loxone(binding), True


def resolve_absent_status(
    profile: dict | None = None,
    *,
    house_doc: dict | None = None,
    read_ehal: bool = True,
) -> dict:
    """Snapshot for UI / live gate: HK, EHAL read, effective OR."""
    if profile is None:
        import config

        profile = (config.get_resolved_runtime_settings() or {}).get("_house_profile") or {}
    hk = bool((profile or {}).get("absent_mode", False))
    ehal_live: bool | None = None
    bound = False
    if read_ehal:
        try:
            ehal_live, bound = read_ehal_absent_mode(house_doc)
        except Exception as exc:  # pragma: no cover - soft fail for UI
            logger.warning("EHAL absent_mode read failed: %s", exc)
            ehal_live = None
            bound = resolve_plant_binding_safe(house_doc)
    effective = effective_absent_mode(hk, ehal_live)
    return {
        "profile_absent": hk,
        "ehal_live": ehal_live,
        "ehal_bound": bound,
        "ehal_state": ehal_read_state(ehal_live, bound=bound),
        "effective": effective,
        "source": _absent_source_label(hk, ehal_live),
    }


def resolve_plant_binding_safe(house_doc: dict | None) -> bool:
    from house_config.ehal_bindings import resolve_plant_binding

    if house_doc is None:
        from integrations.loxone_client import _default_house_profiles_doc

        house_doc = _default_house_profiles_doc()
    return bool(resolve_plant_binding(house_doc, ABSENT_EHAL_FIELD))


def _absent_source_label(hk: bool, ehal_live: bool | None) -> str:
    ehal_on = bool(ehal_live)
    if hk and ehal_on:
        return "beide"
    if hk:
        return "Earnie"
    if ehal_on:
        return "Smarthome"
    return ""


def matrix_is_live_snapshot(matrix: list | None) -> bool:
    return bool(matrix) and matrix[0].get("consumption_mode") == "live_snapshot"


def _house_consumers_by_id(house_profile: dict | None) -> dict[str, dict]:
    if not isinstance(house_profile, dict):
        return {}
    return {
        str(item.get("id") or ""): item
        for item in house_profile.get("consumers") or []
        if isinstance(item, dict) and item.get("id")
    }


def apply_thermal_absent_override(source: dict) -> dict:
    """Copy thermal_annual house consumer with reduced setpoint and persons=0."""
    out = dict(source)
    thermal = dict(source.get("thermal") or {})
    target = float(thermal.get("target_temp_c", source.get("target_temp_c", 21.5)))
    reduction = thermal.get("absent_temp_reduction_c")
    if reduction is None:
        reduction = source.get("absent_temp_reduction_c")
    if reduction is None:
        legacy = thermal.get("absent_temp_c", source.get("absent_temp_c"))
        if legacy is not None:
            reduction = max(0.0, target - float(legacy))
        else:
            reduction = 6.5
    effective = max(0.0, target - float(reduction))
    thermal["target_temp_c"] = effective
    thermal["persons"] = 0
    out["thermal"] = thermal
    out["persons"] = 0
    out["target_temp_c"] = effective
    return out


def thermal_source_with_live_absent(
    source: dict,
    *,
    live_absent_active: bool,
) -> dict:
    """Apply absent thermal override when live effective absent + consumer opt-in."""
    if not live_absent_active or not source:
        return source
    if not bool(source.get("absent_mode_enabled", False)):
        return source
    return apply_thermal_absent_override(source)


def live_absent_skip_fixed_ids(
    house_profile: dict | None,
    *,
    active: bool,
) -> set[str]:
    """Opted-in non–Haus-Wärme IDs to omit from live known/fixed baseload overlay."""
    if not active:
        return set()
    skip: set[str] = set()
    for item in (house_profile or {}).get("consumers") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "")
        if not cid:
            continue
        if not bool(item.get("absent_mode_enabled", False)):
            continue
        if str(item.get("type") or "") == "thermal_annual":
            continue
        skip.add(cid)
    return skip


def resolve_live_absent_skip_ids(house_profile: dict | None) -> set[str]:
    """Skip set for live overlay/chart when effective absent is ON."""
    status = resolve_absent_status(house_profile)
    return live_absent_skip_fixed_ids(
        house_profile,
        active=bool(status.get("effective")),
    )


def apply_absent_mode_to_live_flex(
    consumers: list[dict],
    house_profile: dict | None,
    *,
    active: bool,
) -> list[dict]:
    """Drop opted-in non–Haus-Wärme flex consumers when absent is effective."""
    if not active:
        return list(consumers)
    by_id = _house_consumers_by_id(house_profile)
    kept: list[dict] = []
    for consumer in consumers:
        cid = str(consumer.get("id") or "")
        house = by_id.get(cid)
        if house is None:
            kept.append(consumer)
            continue
        if not bool(house.get("absent_mode_enabled", False)):
            kept.append(consumer)
            continue
        if str(house.get("type") or "") == "thermal_annual":
            kept.append(consumer)
            continue
        logger.info(
            "Abwesenheitsmodus: Verbraucher '%s' von Live-Optimierung ausgeschlossen.",
            cid,
        )
    return kept

"""Cached EHAL adapter factories (OpenEMS / HA / Loxone), split from ``ehal_live``.

Late-bound through ``integrations.ehal_live`` (``live``) so patches applied to
the façade (``config``, adapters, backend checks, ...) stay effective.
"""
from __future__ import annotations

import logging

from ehal.models import canonicalize_ha_entity_keys
from integrations.ha_adapter import HaAdapter, HaConfig
from integrations.loxone_adapter import LoxoneAdapter, LoxoneConfig
from integrations.ehal_live_ref import live
from integrations.openems_adapter import OpenemsAdapter, OpenemsConfig

# Keep the historic logger name so log filters keep working after the split.
logger = logging.getLogger("integrations.ehal_live")

_openems_adapter: OpenemsAdapter | None = None
_ha_adapter: HaAdapter | None = None
_loxone_adapter: LoxoneAdapter | None = None


def get_openems_adapter() -> OpenemsAdapter:
    global _openems_adapter
    base_url = str(live.config.get("EHAL_OPENEMS_BASE_URL") or "").strip()
    if not base_url:
        raise ValueError(
            "ehal.backend=openems requires ehal.openems.base_url "
            "(EHAL_OPENEMS_BASE_URL)."
        )
    cfg = OpenemsConfig(
        base_url=base_url,
        username=str(live.config.get("EHAL_OPENEMS_USERNAME") or "x"),
        password=str(live.config.get("EHAL_OPENEMS_PASSWORD") or "admin"),
        adapter_id=str(live.config.get("EHAL_ADAPTER_ID") or "openems-lab"),
        ess_component=str(live.config.get("EHAL_OPENEMS_ESS_COMPONENT") or "ess0"),
        evcs_component=str(live.config.get("EHAL_OPENEMS_EVCS_COMPONENT") or "evcs0"),
        timeout_sec=float(live.config.get("GLOBAL_TIMEOUT") or 10),
    )
    if _openems_adapter is not None and _openems_adapter.cfg != cfg:
        _openems_adapter = None
    if _openems_adapter is None:
        _openems_adapter = OpenemsAdapter(cfg)
    return _openems_adapter


def _resolve_ha_credentials() -> tuple[str, str]:
    """HA base URL and token from config / Supervisor; raises when either is missing."""
    from integrations.ha_supervisor import resolve_ha_base_url, resolve_ha_token

    base_url = resolve_ha_base_url(str(live.config.get("EHAL_HA_BASE_URL") or ""))
    token = resolve_ha_token(str(live.config.get("EHAL_HA_TOKEN") or ""))
    if not base_url:
        raise ValueError(
            "ehal.backend=ha requires EHAL_HA_BASE_URL in config/.env "
            "(or Supervisor Core URL in the Home Assistant add-on)."
        )
    if not token:
        raise ValueError(
            "ehal.backend=ha requires EHAL_HA_TOKEN in config/.env, "
            "or SUPERVISOR_TOKEN when running as the Home Assistant add-on."
        )
    return base_url, token


def _ha_entities(house, transport: str) -> dict:
    """Aggregated HA entity map from house profiles; configured legacy map when empty."""
    from house_config.ha_ehal_bindings import aggregate_ha_entities

    aggregated = aggregate_ha_entities(house, transport=transport)
    if aggregated:
        return aggregated
    legacy = live.config.get("EHAL_HA_ENTITIES") or {}
    return legacy if isinstance(legacy, dict) else {}


def _config_dict(key: str) -> dict:
    """Config value that must be a mapping; anything else counts as empty."""
    value = live.config.get(key) or {}
    return value if isinstance(value, dict) else {}


def get_ha_adapter() -> HaAdapter:
    global _ha_adapter
    from house_config.ha_ehal_bindings import load_house_profiles_for_ha
    from runtime_store.ehal_setup import HA_TRANSPORT_PUSH, normalize_ha_transport

    base_url, token = _resolve_ha_credentials()
    house = load_house_profiles_for_ha()
    transport = normalize_ha_transport(live.config.get("EHAL_HA_TRANSPORT"))
    entities = _ha_entities(house, transport)
    from integrations.ha_push_read import (
        load_house_components_for_ha,
        push_read_qualified_ids,
        setpoint_qualified_ids,
    )

    house_doc, components_doc = load_house_components_for_ha()
    if house is not None and isinstance(house, dict):
        house_doc = house
    push_qids = push_read_qualified_ids(house_doc, components_doc)
    setpoint_qids = setpoint_qualified_ids(house_doc, components_doc)
    sign = _config_dict("EHAL_HA_SIGN")
    boolean_invert = _config_dict("EHAL_HA_BOOLEAN_INVERT")
    ha_ess_force = None
    if isinstance(house, dict):
        plant = house.get("plant")
        if isinstance(plant, dict) and plant.get("ha_ess_force"):
            ha_ess_force = plant.get("ha_ess_force")
    cfg = HaConfig(
        base_url=base_url,
        token=token,
        adapter_id=str(live.config.get("EHAL_ADAPTER_ID") or "earnie-hems"),
        entities=canonicalize_ha_entity_keys(
            {str(k): str(v) for k, v in entities.items()},
            keep_empty=transport == HA_TRANSPORT_PUSH,
        ),
        sign=canonicalize_ha_entity_keys({str(k): str(v) for k, v in sign.items()}),
        boolean_invert=canonicalize_ha_entity_keys(
            {str(k): str(v) for k, v in boolean_invert.items()}
        ),
        timeout_sec=float(live.config.get("GLOBAL_TIMEOUT") or 10),
        ha_ess_force=ha_ess_force if isinstance(ha_ess_force, dict) else None,
        transport=transport,
        push_read_qids=push_qids,
        setpoint_qids=setpoint_qids,
    )
    if _ha_adapter is not None and _ha_adapter.cfg != cfg:
        _ha_adapter = None
    if _ha_adapter is None:
        _ha_adapter = HaAdapter(cfg)
    return _ha_adapter


def _standby_source_select_merker() -> str:
    """Entity-scoped Quellenwahl Merker from the physical standby_backup battery."""
    from ehal.ess_fields import binding_address
    from house_config.powerstation import (
        BACKING_PHYSICAL,
        ROLE_STANDBY_BACKUP,
        ehal_mappable_batteries,
        is_powerstation,
    )

    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return ""
        doc = load_components_document(path)
        raw = doc.get("batteries") if isinstance(doc, dict) else []
    except Exception:  # noqa: BLE001
        return ""
    for bat in ehal_mappable_batteries(raw if isinstance(raw, list) else []):
        if not is_powerstation(bat):
            continue
        if str(bat.get("role") or "") != ROLE_STANDBY_BACKUP:
            continue
        if str(bat.get("backing") or "") != BACKING_PHYSICAL:
            continue
        bid = str(bat.get("id") or "").strip()
        if not bid:
            continue
        bindings = bat.get("ehal_bindings")
        addr = binding_address(
            bindings if isinstance(bindings, dict) else {},
            bid,
            "set_ess_source_select",
        )
        if addr:
            return addr
    return ""


def get_loxone_adapter() -> LoxoneAdapter:
    global _loxone_adapter
    from house_config.ehal_bindings import resolve_plant_binding
    from house_config.ess_bindings import resolve_primary_ess_binding
    from optimizer.live_export_limit import load_house_doc

    ev = _first_ev_loxone_bindings()
    house = load_house_doc()
    export_out = resolve_plant_binding(house, "set_grid_export_power_limit")
    # Capability / residual flat write_setpoints: entity-scoped standby Merker only.
    ess_source_select = _standby_source_select_merker()
    cfg = LoxoneConfig(
        adapter_id=str(live.config.get("EHAL_ADAPTER_ID") or "loxone-home"),
        charge_power_name=str(
            resolve_primary_ess_binding("set_ess_charge_power_limit") or ""
        ),
        discharge_power_name=str(
            resolve_primary_ess_binding("set_ess_discharge_power_limit") or ""
        ),
        active_power_name=str(
            resolve_primary_ess_binding("set_ess_active_power") or ""
        ),
        control_cmd_name=str(resolve_primary_ess_binding("set_ess_mode") or ""),
        evcs_max_current_name=str(ev.get("evcs_max_current_name") or ""),
        evcs_mode_name=str(ev.get("evcs_mode_name") or ""),
        grid_export_limit_out_name=str(export_out or ""),
        ess_source_select_name=str(ess_source_select or ""),
        timeout_sec=float(live.config.get("GLOBAL_TIMEOUT") or 10),
    )
    if _loxone_adapter is not None and _loxone_adapter.cfg != cfg:
        _loxone_adapter = None
    if _loxone_adapter is None:
        _loxone_adapter = LoxoneAdapter(cfg)
    return _loxone_adapter


def _first_ev_loxone_bindings() -> dict[str, str]:
    """EV write markers from first EV consumer ``ehal_bindings`` (entity-scoped only)."""
    from settings.ehal_marker_resolve import (
        marker_set_evcs_max_current,
        marker_set_evcs_mode,
    )

    consumer = live._first_ev_consumer()
    if consumer is None:
        return {}
    return {
        "evcs_max_current_name": marker_set_evcs_max_current(consumer),
        "evcs_mode_name": marker_set_evcs_mode(consumer),
    }


def reset_adapter_cache() -> None:
    """Test helper: drop cached adapter instances."""
    global _openems_adapter, _ha_adapter, _loxone_adapter
    _openems_adapter = None
    _ha_adapter = None
    _loxone_adapter = None

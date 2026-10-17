"""Validation and persistence of the HA entity mapping (split from ehal_ha_mapping)."""
from __future__ import annotations

from typing import Any
import streamlit as st
from house_config.ehal_bindings import ensure_migrated
from integrations.ehal_live import reset_adapter_cache
from integrations.ha_ehal_mapping import (
    binding_unit_issues,
)
from ehal.ess_fields import ess_field
from ui.ehal_loxone_mapping import (
    BATTERY_ENTITY_KIND,
    PLANT_ENTITY_ID,
    PLANT_TELEMETRY_REQUIRED,
    PV_ENTITY_KIND,
    apply_battery_bindings,
    apply_entity_bindings,
    apply_inverter_bindings,
    apply_pv_system_bindings,
    entity_kind_for_id,
    INVERTER_ENTITY_KIND,
)
from ui.house_config_io import (
    save_house_profiles,
    save_main_config,
)


def _validate_mapping_save(
    entity_id: str,
    ehal_map: dict[str, str],
    scan_rows: list[dict[str, Any]] | None = None,
    *,
    entity_kind: str = "",
) -> str | None:
    kind = str(entity_kind or "").strip()
    if entity_id == PLANT_ENTITY_ID or kind == "plant":
        missing = [name for name in PLANT_TELEMETRY_REQUIRED if name not in ehal_map]
        if missing:
            return "Pflichtfelder fehlen: " + ", ".join(missing)
    elif kind == BATTERY_ENTITY_KIND:
        soc = ess_field(entity_id, "sens_ess_soc")
        if soc not in ehal_map:
            return f"Pflichtfelder fehlen: {soc}"
    issues = binding_unit_issues(ehal_map, scan_rows or [])
    if issues:
        return "Einheit passt nicht zum Feld: " + "; ".join(issues)
    return None


def _write_ha_credentials(base_url: str, token: str) -> bool:
    """Persist URL/token to ``.env``; show the error and return False when not possible."""
    from integrations.ha_supervisor import resolve_ha_base_url, resolve_ha_token
    from runtime_store.dotenv_io import write_ha_dotenv
    from runtime_store.dotenv_loader import load_app_dotenv

    resolved_url = resolve_ha_base_url(base_url)
    if not resolved_url or not resolve_ha_token(token):
        st.error(
            "URL und Token sind erforderlich "
            "(oder SUPERVISOR_TOKEN beim Betrieb als Home-Assistant-Add-on)."
        )
        return False
    try:
        # Never persist SUPERVISOR_TOKEN — empty token stays empty in .env.
        write_ha_dotenv(resolved_url, token)
    except (OSError, PermissionError) as exc:
        st.error(f"Speichern der .env fehlgeschlagen: {exc}")
        return False
    load_app_dotenv(override=True)
    return True


def _persist_entity_bindings(
    kind: str,
    *,
    entity_id: str,
    ehal_map: dict[str, str],
    profile_id: str,
    migrated_house: dict,
) -> str:
    """Write the bindings to the document that owns the entity; return a UI detail text."""
    from ui.house_config_io import _load_components_document, _save_components_document

    if kind == BATTERY_ENTITY_KIND:
        components = apply_battery_bindings(
            _load_components_document(),
            battery_id=entity_id,
            bindings=ehal_map,
        )
        _save_components_document(components)
        return "`components.json` (`batteries[].ehal_bindings`)"
    if kind == INVERTER_ENTITY_KIND:
        components = apply_inverter_bindings(
            _load_components_document(),
            inverter_id=entity_id,
            bindings=ehal_map,
        )
        _save_components_document(components)
        return "`components.json` (`inverters[].ehal_bindings`)"
    if kind == PV_ENTITY_KIND:
        components = apply_pv_system_bindings(
            _load_components_document(),
            pv_system_id=entity_id,
            bindings=ehal_map,
        )
        _save_components_document(components)
        return "`components.json` (`pv_systems[].ehal_bindings`)"
    updated = apply_entity_bindings(
        migrated_house,
        profile_id=profile_id,
        entity_id=entity_id,
        bindings=ehal_map,
    )
    save_house_profiles(updated)
    return "`plant`/`consumers[].ehal_bindings`"


def _config_with_ha_backend(
    migrated_config: dict, *, adapter_id: str, sign: dict[str, str]
) -> dict:
    """Main config with ``ehal.backend=ha`` and the merged sign map."""
    payload = dict(migrated_config)
    ehal = dict(payload.get("ehal") or {}) if isinstance(payload.get("ehal"), dict) else {}
    ehal["backend"] = "ha"
    ehal["adapter_id"] = adapter_id
    existing_ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    existing_sign = (
        dict(existing_ha.get("sign") or {})
        if isinstance(existing_ha.get("sign"), dict)
        else {}
    )
    merged_sign = dict(existing_sign)
    merged_sign.update(sign)
    ehal["ha"] = {
        "entities": {},
        "sign": merged_sign,
    }
    payload["ehal"] = ehal
    return payload


def _save_entity_mapping(
    house: dict,
    config_doc: dict,
    *,
    profile_id: str,
    entity_id: str,
    ehal_map: dict[str, str],
    base_url: str,
    token: str,
    adapter_id: str,
    sign: dict[str, str],
    scan_rows: list[dict[str, Any]] | None = None,
    entity_kind: str = "",
) -> None:
    from runtime_store.shadow.ehal_overlay import upsert_entity_bindings
    from runtime_store.shadow.mode import is_shadow_config_readonly

    kind = str(entity_kind or "").strip() or entity_kind_for_id(
        house, profile_id, entity_id
    )
    error = _validate_mapping_save(
        entity_id, ehal_map, scan_rows, entity_kind=kind
    )
    if error:
        st.error(error)
        return
    shadow_readonly = is_shadow_config_readonly()
    if not shadow_readonly and not _write_ha_credentials(base_url, token):
        return
    migrated_house, migrated_config, _ = ensure_migrated(house, config_doc)
    if shadow_readonly:
        path = upsert_entity_bindings(
            profile_id=profile_id,
            entity_id=entity_id,
            bindings=ehal_map,
            entity_kind=kind,
        )
        reset_adapter_cache()
        st.success(
            f"HA-EHAL-Mapping für `{entity_id}` im Shadow-Overlay gespeichert "
            f"(`{path}`; Prod-Config unverändert)."
        )
        st.rerun()
        return
    detail = _persist_entity_bindings(
        kind,
        entity_id=entity_id,
        ehal_map=ehal_map,
        profile_id=profile_id,
        migrated_house=migrated_house,
    )
    save_main_config(
        _config_with_ha_backend(migrated_config, adapter_id=adapter_id, sign=sign)
    )
    reset_adapter_cache()
    st.success(
        f"HA-EHAL-Mapping für `{entity_id}` gespeichert "
        f"({detail}, `ehal.backend=ha`)."
    )
    st.rerun()


def _persist_ha_ess_force(house: dict, force: dict[str, Any] | None) -> dict:
    """Write or clear plant.ha_ess_force on the house document."""
    out = dict(house)
    plant = dict(out.get("plant") or {}) if isinstance(out.get("plant"), dict) else {}
    if force:
        plant["ha_ess_force"] = force
    else:
        plant.pop("ha_ess_force", None)
    if plant:
        out["plant"] = plant
    elif "plant" in out and not plant:
        out.pop("plant", None)
    return out

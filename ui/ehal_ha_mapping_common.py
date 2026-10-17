"""Session keys and pure helpers of the HA entity mapping UI (split from ehal_ha_mapping)."""
from __future__ import annotations

from typing import Any
import streamlit as st
from ehal.models import canonicalize_ha_entity_keys
from ehal.profiles import role_field_labels
from house_config.ehal_bindings import ensure_migrated
from ehal.field_catalog import TELEMETRY_ENERGY_OPTIONAL
from integrations.ha_adapter import (
    HaAdapter,
    HaConfig,
)
from runtime_store.ehal_setup import BACKEND_HA, default_adapter_id, resolve_adapter_id
from ehal.ess_fields import ess_field_kind
from ui.ehal_loxone_mapping import (
    BATTERY_ENTITY_KIND,
    PLANT_ENTITY_ID,
)
from ui.house_config_io import (
    load_house_profiles,
    load_main_config,
    save_house_profiles,
    save_main_config,
)


_NONE = "— nicht gemappt —"


_SESSION_SCAN = "ehal_ha_scan_entities"


_SESSION_SCAN_ERROR = "ehal_ha_scan_error"


_SESSION_PROPOSALS = "ehal_ha_proposals"


_SESSION_ENTITY = "ehal_ha_entity_id"


_SESSION_AUTO_SCAN = "ehal_ha_auto_scan_done"


_FIELD_LABELS: dict[str, str] = role_field_labels()


_PLANT_SIGN_FIELDS = ("sens_grid_power_active", "sens_ess_power")


def _clear_map_widget_keys(entity_id: str, fields: tuple[str, ...] | list[str]) -> None:
    """Drop selectbox keys so defaults re-seed from propose / saved map."""
    for field in fields:
        st.session_state.pop(f"ehal_ha_map_{entity_id}_{field}", None)


def _proposed_entity_id(proposals: dict[str, dict[str, Any]], field: str) -> str:
    if not isinstance(proposals, dict):
        return ""
    keys = [field]
    kind = ess_field_kind(field)
    if kind and kind not in keys:
        keys.append(kind)
    for key in keys:
        entry = proposals.get(key)
        if isinstance(entry, dict):
            eid = str(entry.get("entity_id") or "").strip()
            if eid:
                return eid
    return ""


def _ha_credentials(data: dict) -> dict[str, Any]:
    from runtime_store.dotenv_io import read_ha_credentials

    ehal = data.get("ehal") if isinstance(data.get("ehal"), dict) else {}
    ha = ehal.get("ha") if isinstance(ehal.get("ha"), dict) else {}
    raw_sign = dict(ha.get("sign") or {}) if isinstance(ha.get("sign"), dict) else {}
    base_url, token = read_ha_credentials()
    return {
        "backend": str(ehal.get("backend") or ""),
        "adapter_id": resolve_adapter_id(ehal.get("adapter_id"), BACKEND_HA),
        "base_url": base_url,
        "token": token,
        "sign": canonicalize_ha_entity_keys(
            {str(k): str(v) for k, v in raw_sign.items()}
        ),
    }


def _ensure_ha_migrated() -> tuple[dict, dict]:
    """One-shot migrate flat entities → entity-scoped; return (config, house)."""
    from runtime_store.shadow.mode import is_shadow_config_readonly

    config_doc = load_main_config()
    house = load_house_profiles()
    new_house, new_config, changed = ensure_migrated(house, config_doc)
    if changed:
        if is_shadow_config_readonly():
            return new_config, new_house
        save_house_profiles(new_house)
        save_main_config(new_config)
        return new_config, new_house
    return config_doc, house


def _adapter_from_form(base_url: str, token: str, entities: dict[str, str]) -> HaAdapter:
    from integrations.ha_supervisor import resolve_ha_base_url, resolve_ha_token

    resolved_url = resolve_ha_base_url(base_url)
    resolved_token = resolve_ha_token(token)
    if not resolved_url or not resolved_token:
        raise ValueError(
            "URL und Token sind erforderlich "
            "(oder SUPERVISOR_TOKEN beim Betrieb als Home-Assistant-Add-on)."
        )
    return HaAdapter(
        HaConfig(
            base_url=resolved_url,
            token=resolved_token,
            adapter_id=default_adapter_id(BACKEND_HA),
            entities=entities,
        )
    )


def _entity_options(rows: list[dict[str, Any]], current_values: list[str]) -> list[str]:
    ids = [str(row["entity_id"]) for row in rows if str(row.get("entity_id") or "").strip()]
    for value in current_values:
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    return [_NONE] + ids


def _field_select_caption(field: str, *, required: bool = False) -> str:
    from ehal.ess_fields import ess_field_kind

    kind = ess_field_kind(field)
    meaning = _FIELD_LABELS.get(kind or field, _FIELD_LABELS.get(field, field))
    suffix = " *" if required else ""
    return f"{meaning} (`{field}`){suffix}"


def _ha_entity_fields(entity: dict[str, Any]) -> tuple[str, ...]:
    """Plant gets Slot-Ist energy counters in addition to Loxone plant fields."""
    fields = tuple(entity.get("fields") or ())
    if str(entity.get("kind") or "") == BATTERY_ENTITY_KIND:
        return fields
    if str(entity.get("id") or "") != PLANT_ENTITY_ID:
        return fields
    extra = [f for f in TELEMETRY_ENERGY_OPTIONAL if f not in fields]
    return fields + tuple(extra)

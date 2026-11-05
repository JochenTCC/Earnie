"""EHAL bindings of a heating rod part, stored on its ``thermal_annual`` house consumer.

The catalog entry (``heating_systems[].parts``) describes the rod; the wiring belongs to the
installed house, so the map lives on the consumer (``docs/dev/heating-system-variants.md``). It
is a map of its own and not part of ``ehal_bindings``: every reader of a consumer's
``ehal_bindings`` treats a ``set_enable`` key as the consumer's own, and
``canonicalize_consumer_bindings`` would turn the rod's key into the heat pump's release.

Towards EHAL the rod is an entity of its own, Kennung ``<consumer_id>_heating_rod`` (D1), so
marker resolution, publishing and the signal list work on it like on any other consumer.
"""
from __future__ import annotations

from typing import Any, Iterable

from ehal.flex_fields import KIND_SENS_CONSUMER_ACTIVE, KIND_SENS_POWER_ACT, KIND_SET_ENABLE
from ehal.qualified_ids import field_kind, qualified_consumer_id
from house_config.heat_source import (
    HEATING_ROD_PART_ID,
    HEATING_ROD_PART_TYPE,
    heating_rod_part,
    part_kennung,
)

ROD_BINDINGS_KEY = "heating_rod_ehal_bindings"
ROD_KINDS: tuple[str, ...] = (KIND_SET_ENABLE, KIND_SENS_POWER_ACT, KIND_SENS_CONSUMER_ACTIVE)
ROD_LABEL = "Heizstab"


def rod_kennung(consumer_id: str) -> str:
    return part_kennung(str(consumer_id), HEATING_ROD_PART_ID)


def rod_field(consumer_id: str, kind: str) -> str:
    """Storage key ``heatpump.<consumer_id>_heating_rod.<kind>``."""
    return qualified_consumer_id(rod_kennung(consumer_id), HEATING_ROD_PART_TYPE, kind)


def normalize_rod_bindings(raw: Any, *, consumer_id: str, label: str) -> dict[str, str]:
    """Validated map (fail loud on foreign keys); an empty value is an activation flag (Q8)."""
    if not isinstance(raw, dict):
        raise ValueError(f"{label}: {ROD_BINDINGS_KEY} muss ein Objekt sein.")
    allowed = {rod_field(consumer_id, kind) for kind in ROD_KINDS}
    out: dict[str, str] = {}
    for key, value in raw.items():
        field = str(key).strip()
        if field not in allowed:
            raise ValueError(
                f"{label}: {ROD_BINDINGS_KEY} enthält unbekanntes Feld '{field}' "
                f"(erlaubt: {', '.join(sorted(allowed))})."
            )
        out[field] = str(value or "").strip()
    return out


def rod_binding_entity(consumer: dict[str, Any]) -> dict[str, Any] | None:
    """The rod as an EHAL entity when the consumer holds rod bindings, else ``None``."""
    bindings = consumer.get(ROD_BINDINGS_KEY)
    if not isinstance(bindings, dict) or not bindings:
        return None
    return {
        "id": rod_kennung(str(consumer.get("id") or "")),
        "label": ROD_LABEL,
        "type": HEATING_ROD_PART_TYPE,
        "ehal_bindings": dict(bindings),
    }


def rod_binding_entities(consumers: Iterable[Any]) -> list[dict[str, Any]]:
    entities = (rod_binding_entity(c) for c in consumers if isinstance(c, dict))
    return [entity for entity in entities if entity is not None]


def consumer_has_rod_part(consumer: dict[str, Any], components: dict | None) -> bool:
    """Rod in the reference system; reads the catalog for a raw (not yet resolved) consumer."""
    if consumer.get("type") != "thermal_annual":
        return False
    if consumer.get("parts"):
        return heating_rod_part(consumer) is not None
    from house_config.heating_systems import HEATING_SYSTEM_ID_KEY, heating_systems_by_id

    system = heating_systems_by_id(components).get(
        str(consumer.get(HEATING_SYSTEM_ID_KEY) or "").strip()
    )
    return system is not None and heating_rod_part(system) is not None


def rod_mapping_entities(
    consumers: Iterable[Any], components: dict | None
) -> list[dict[str, Any]]:
    """Rod rows of the signal mapping: bound rods and installed rods not bound yet."""
    out: list[dict[str, Any]] = []
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        entity = rod_binding_entity(consumer)
        if entity is None and consumer_has_rod_part(consumer, components):
            entity = {
                "id": rod_kennung(str(consumer.get("id") or "")),
                "label": ROD_LABEL,
                "type": HEATING_ROD_PART_TYPE,
                "ehal_bindings": {},
            }
        if entity is not None:
            out.append(entity)
    return out


def rewrite_rod_bindings_slug(bindings: Any, *, new_consumer_id: str) -> dict[str, str]:
    """Rod keys after a rename of the parent consumer (the Kennung contains its id)."""
    if not isinstance(bindings, dict):
        return {}
    return {
        rod_field(new_consumer_id, field_kind(str(key))): str(value or "").strip()
        for key, value in bindings.items()
    }


def missing_live_signals(rod: dict[str, Any], parent: dict[str, Any]) -> list[str]:
    """Signals still missing before Live may plan this rod (empty = ready).

    Earnie needs to switch the rod, to measure what it draws (its power would otherwise
    count as Grundlast) and to read the store it heats.
    """
    from settings.ehal_marker_resolve import (
        marker_flex_enable,
        marker_flex_power,
        marker_sens_consumer_active,
        marker_sens_temperature_heat_storage,
    )

    missing: list[str] = []
    if not marker_flex_enable(rod):
        missing.append(KIND_SET_ENABLE)
    if not marker_flex_power(rod) and not marker_sens_consumer_active(rod):
        missing.append(f"{KIND_SENS_POWER_ACT} oder {KIND_SENS_CONSUMER_ACTIVE}")
    if not marker_sens_temperature_heat_storage(parent):
        missing.append("sens_temperature_heat_storage")
    return missing

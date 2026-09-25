"""Helpers shared by earnie_house_sim platforms."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, INPUT_NUMBER_DOMAIN, NUMBER_DOMAIN


def ha_entity_id(fixture_entity_id: str) -> str:
    """Map fixture entity_id to the id registered in HA."""
    domain, _, object_id = fixture_entity_id.partition(".")
    if domain == INPUT_NUMBER_DOMAIN:
        return f"{NUMBER_DOMAIN}.{object_id}"
    return fixture_entity_id


def fixture_object_id(fixture_entity_id: str) -> str:
    return fixture_entity_id.partition(".")[2]


def device_info_for_entity(
    *,
    entry_id: str,
    package_devices: list[dict[str, Any]],
    fixture_entity_id: str,
) -> DeviceInfo | None:
    for device in package_devices:
        ids = list(device.get("entity_ids") or [])
        if fixture_entity_id not in ids:
            continue
        key = str(device.get("key") or "device")
        return DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}:{key}")},
            name=str(device.get("name") or key),
            manufacturer=str(device.get("manufacturer") or "earnie_house_sim"),
            model=str(device.get("model") or "sim"),
        )
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}:house")},
        name="Earnie House Sim",
        manufacturer="earnie_house_sim",
        model="house",
    )


def attrs_from_fixture(item: dict[str, Any]) -> dict[str, Any]:
    attrs = item.get("attributes")
    return dict(attrs) if isinstance(attrs, dict) else {}

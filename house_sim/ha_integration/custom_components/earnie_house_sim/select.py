"""Select platform for earnie_house_sim (vendor mode / force-state selects)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HouseSimCoordinator
from .entity_map import (
    attrs_from_fixture,
    device_info_for_entity,
    fixture_object_id,
    ha_entity_id,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HouseSimCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[HouseSimSelect] = []
    for item in coordinator.package.entities:
        eid = str(item.get("entity_id") or "")
        if not eid.startswith("select."):
            continue
        entities.append(HouseSimSelect(coordinator, entry.entry_id, item))
    async_add_entities(entities)


class HouseSimSelect(CoordinatorEntity[HouseSimCoordinator], SelectEntity):
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: HouseSimCoordinator,
        entry_id: str,
        fixture_item: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._fixture_id = str(fixture_item["entity_id"])
        self._ha_id = ha_entity_id(self._fixture_id)
        object_id = fixture_object_id(self._fixture_id)
        attrs = attrs_from_fixture(fixture_item)
        self.entity_id = self._ha_id
        self._attr_unique_id = f"{entry_id}:{self._ha_id}"
        self._attr_name = str(attrs.get("friendly_name") or object_id)
        self._attr_options = [str(o) for o in attrs.get("options") or []]
        self._attr_device_info = device_info_for_entity(
            entry_id=entry_id,
            package_devices=coordinator.package.devices,
            fixture_entity_id=self._fixture_id,
        )

    @property
    def available(self) -> bool:
        value = self.coordinator.entity_state_value(self._fixture_id)
        return value is not None and super().available

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.entity_state_value(self._fixture_id)
        if value is None:
            return None
        return str(value)

    async def async_select_option(self, option: str) -> None:
        self.coordinator.set_select(self._ha_id, option)
        await self.coordinator.async_request_refresh()

"""Sensor platform for earnie_house_sim."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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

_DEVICE_CLASS = {
    "power": SensorDeviceClass.POWER,
    "energy": SensorDeviceClass.ENERGY,
    "battery": SensorDeviceClass.BATTERY,
    "temperature": SensorDeviceClass.TEMPERATURE,
}
_STATE_CLASS = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HouseSimCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[HouseSimSensor] = []
    for item in coordinator.package.entities:
        eid = str(item.get("entity_id") or "")
        if not eid.startswith("sensor."):
            continue
        entities.append(HouseSimSensor(coordinator, entry.entry_id, item))
    async_add_entities(entities)


class HouseSimSensor(CoordinatorEntity[HouseSimCoordinator], SensorEntity):
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: HouseSimCoordinator,
        entry_id: str,
        fixture_item: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._fixture_id = str(fixture_item["entity_id"])
        object_id = fixture_object_id(self._fixture_id)
        attrs = attrs_from_fixture(fixture_item)
        self.entity_id = ha_entity_id(self._fixture_id)
        self._attr_unique_id = f"{entry_id}:{self._fixture_id}"
        self._attr_name = str(attrs.get("friendly_name") or object_id)
        self._attr_native_unit_of_measurement = attrs.get("unit_of_measurement")
        dc = attrs.get("device_class")
        if isinstance(dc, str) and dc in _DEVICE_CLASS:
            self._attr_device_class = _DEVICE_CLASS[dc]
        sc = attrs.get("state_class")
        if isinstance(sc, str) and sc in _STATE_CLASS:
            self._attr_state_class = _STATE_CLASS[sc]
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
    def native_value(self) -> float | None:
        value = self.coordinator.entity_state_value(self._fixture_id)
        if value is None:
            return None
        return float(value)

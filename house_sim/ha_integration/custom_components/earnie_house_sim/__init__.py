"""Earnie House Simulator — Home Assistant custom integration (HouseSim S4)."""
from __future__ import annotations

from dataclasses import replace

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HouseSimCoordinator
from .entity_map import ha_entity_id

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = HouseSimCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HouseSimCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_persist()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "cloud_pass")
            for service in (
                "car_arrives",
                "car_leaves",
                "load_spike",
                "set_soc",
                "set_unavailable",
                "reject_writes",
                "setpoint_lag",
                "unit_flip",
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
    return unload_ok


def _coordinator(hass: HomeAssistant) -> HouseSimCoordinator:
    entries = hass.data.get(DOMAIN) or {}
    if not entries:
        raise vol.Invalid("earnie_house_sim is not configured")
    return next(iter(entries.values()))


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "cloud_pass"):
        return

    async def cloud_pass(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        minutes = float(call.data.get("minutes", 15))
        scale = float(call.data.get("scale", 0.2))
        coord.overlay.apply_cloud_pass(minutes=minutes, scale=scale)
        await coord.async_request_refresh()

    async def car_arrives(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        power_w = float(call.data.get("power_w", 7000))
        coord.overlay.car_arrives(power_w)
        await coord.async_request_refresh()

    async def car_leaves(_call: ServiceCall) -> None:
        coord = _coordinator(hass)
        coord.overlay.car_leaves()
        await coord.async_request_refresh()

    async def load_spike(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        minutes = float(call.data.get("minutes", 15))
        extra_kw = float(call.data.get("extra_kw", 3.0))
        coord.overlay.apply_load_spike(minutes=minutes, extra_kw=extra_kw)
        await coord.async_request_refresh()

    async def set_soc(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        soc = max(0.0, min(100.0, float(call.data["soc_pct"])))
        coord.physics = replace(coord.physics, soc_pct=soc)
        await coord.async_persist()
        await coord.async_request_refresh()

    async def set_unavailable(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        entity_id = str(call.data["entity_id"])
        minutes = float(call.data.get("minutes", 5))
        until = dt_util.utcnow().timestamp() + minutes * 60.0
        coord.unavailable_until[ha_entity_id(entity_id)] = until
        await coord.async_request_refresh()

    async def reject_writes(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        coord.reject_writes = bool(call.data.get("enabled", True))

    async def setpoint_lag(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        coord.setpoint_lag_s = max(0.0, float(call.data.get("seconds", 0)))

    async def unit_flip(call: ServiceCall) -> None:
        coord = _coordinator(hass)
        coord.unit_flip = bool(call.data.get("enabled", True))
        await coord.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        "cloud_pass",
        cloud_pass,
        schema=vol.Schema(
            {
                vol.Optional("minutes", default=15): vol.Coerce(float),
                vol.Optional("scale", default=0.2): vol.Coerce(float),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "car_arrives",
        car_arrives,
        schema=vol.Schema({vol.Optional("power_w", default=7000): vol.Coerce(float)}),
    )
    hass.services.async_register(DOMAIN, "car_leaves", car_leaves, schema=vol.Schema({}))
    hass.services.async_register(
        DOMAIN,
        "load_spike",
        load_spike,
        schema=vol.Schema(
            {
                vol.Optional("minutes", default=15): vol.Coerce(float),
                vol.Optional("extra_kw", default=3.0): vol.Coerce(float),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "set_soc",
        set_soc,
        schema=vol.Schema({vol.Required("soc_pct"): vol.Coerce(float)}),
    )
    hass.services.async_register(
        DOMAIN,
        "set_unavailable",
        set_unavailable,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.string,
                vol.Optional("minutes", default=5): vol.Coerce(float),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "reject_writes",
        reject_writes,
        schema=vol.Schema({vol.Optional("enabled", default=True): cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN,
        "setpoint_lag",
        setpoint_lag,
        schema=vol.Schema({vol.Optional("seconds", default=0): vol.Coerce(float)}),
    )
    hass.services.async_register(
        DOMAIN,
        "unit_flip",
        unit_flip,
        schema=vol.Schema({vol.Optional("enabled", default=True): cv.boolean}),
    )

"""Config flow for earnie_house_sim."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import (
    CONF_ARCHETYPE,
    CONF_PV_KWP,
    CONF_PV_SOURCE,
    CONF_UPDATE_INTERVAL,
    CONF_WEATHER_ENTITY,
    DEFAULT_PV_KWP,
    DEFAULT_UPDATE_INTERVAL_S,
    DOMAIN,
    PV_SOURCE_SYNTHETIC,
    PV_SOURCE_WEATHER,
)


def _list_archetypes() -> list[str]:
    fixtures = Path(__file__).resolve().parent / "fixtures"
    if not fixtures.is_dir():
        return []
    return sorted(p.name for p in fixtures.iterdir() if p.is_dir())


def _weather_has_cloud_coverage(hass: HomeAssistant, entity_id: str) -> bool:
    state = hass.states.get(entity_id)
    if state is None:
        return False
    return state.attributes.get("cloud_coverage") is not None


class EarnieHouseSimConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow: archetype + PV source."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        archetypes = await self.hass.async_add_executor_job(_list_archetypes)
        if not archetypes:
            return self.async_abort(reason="no_archetypes")

        if user_input is not None:
            archetype = str(user_input[CONF_ARCHETYPE])
            pv_source = str(user_input[CONF_PV_SOURCE])
            await self.async_set_unique_id(f"{DOMAIN}:{archetype}")
            self._abort_if_unique_id_configured()

            data: dict[str, Any] = {
                CONF_ARCHETYPE: archetype,
                CONF_PV_SOURCE: pv_source,
                CONF_UPDATE_INTERVAL: int(
                    user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_S)
                ),
                CONF_PV_KWP: float(user_input.get(CONF_PV_KWP, DEFAULT_PV_KWP)),
            }
            if pv_source == PV_SOURCE_WEATHER:
                weather_id = str(user_input.get(CONF_WEATHER_ENTITY) or "").strip()
                if not weather_id:
                    errors["base"] = "weather_required"
                elif not _weather_has_cloud_coverage(self.hass, weather_id):
                    errors["base"] = "weather_no_cloud_coverage"
                else:
                    data[CONF_WEATHER_ENTITY] = weather_id
            if not errors:
                return self.async_create_entry(
                    title=f"House Sim ({archetype})",
                    data=data,
                )

        schema: dict[Any, Any] = {
            vol.Required(CONF_ARCHETYPE, default=archetypes[0]): vol.In(archetypes),
            vol.Required(CONF_PV_SOURCE, default=PV_SOURCE_SYNTHETIC): vol.In(
                [PV_SOURCE_SYNTHETIC, PV_SOURCE_WEATHER]
            ),
            vol.Optional(CONF_PV_KWP, default=DEFAULT_PV_KWP): vol.Coerce(float),
            vol.Optional(
                CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL_S
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

"""Constants for earnie_house_sim."""
from __future__ import annotations

DOMAIN = "earnie_house_sim"
CONF_ARCHETYPE = "archetype"
CONF_PV_SOURCE = "pv_source"
CONF_WEATHER_ENTITY = "weather_entity_id"
CONF_PV_KWP = "pv_kwp"
CONF_UPDATE_INTERVAL = "update_interval_s"

PV_SOURCE_WEATHER = "weather"
PV_SOURCE_SYNTHETIC = "synthetic"

DEFAULT_UPDATE_INTERVAL_S = 10
DEFAULT_PV_KWP = 10.0

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_physics"

# Fixture domains that must register as HA number (custom integrations
# cannot own input_number).
INPUT_NUMBER_DOMAIN = "input_number"
NUMBER_DOMAIN = "number"

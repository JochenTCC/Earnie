"""IANA-Zeitzone aus Hausprofil-Land (DACH, offline)."""
from __future__ import annotations

_LAND_TIMEZONES = {
    "AT": "Europe/Vienna",
    "DE": "Europe/Berlin",
    "CH": "Europe/Zurich",
}


def timezone_for_land(land: str) -> str:
    """Liefert IANA-Zeitzone für AT/DE/CH; unbekannte Werte → Europe/Vienna."""
    key = str(land or "").strip().upper()
    return _LAND_TIMEZONES.get(key, _LAND_TIMEZONES["AT"])

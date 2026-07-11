"""aWATTar Day-Ahead-API-URLs ab Import-Tarif-Land (1.26.0 P6)."""
from __future__ import annotations

AWATTAR_API_URL_BY_LAND: dict[str, str] = {
    "AT": "https://api.awattar.at/v1/marketdata",
    "DE": "https://api.awattar.de/v1/marketdata",
}
DEFAULT_AWATTAR_API_URL = AWATTAR_API_URL_BY_LAND["AT"]


def resolve_awattar_api_url(resolved_settings: dict | None = None) -> str:
    """Liefert die aWATTar-API-URL aus dem aufgelösten Import-Tarif (land)."""
    spec = (resolved_settings or {}).get("_import_tariff_spec") or {}
    land = str(spec.get("land", "AT") or "AT").strip().upper()
    return AWATTAR_API_URL_BY_LAND.get(land, DEFAULT_AWATTAR_API_URL)

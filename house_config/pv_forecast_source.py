"""Plant-wide primary PV forecast source (``plant.pv_forecast_source``).

The planner asks the primary source first and the other one only when the primary
delivers nothing usable for a PV system (``data.pv_forecast._forecast_one_system``).
An absent key means forecast.solar first: the order every install had before the key
existed, so packs need no migration.
"""
from __future__ import annotations

PV_FORECAST_SOURCE_KEY = "pv_forecast_source"
PV_SOURCE_FORECAST_SOLAR = "forecast_solar"
PV_SOURCE_OPEN_METEO = "open_meteo"
PV_FORECAST_SOURCES = (PV_SOURCE_FORECAST_SOLAR, PV_SOURCE_OPEN_METEO)
DEFAULT_PV_FORECAST_SOURCE = PV_SOURCE_FORECAST_SOLAR

PV_FORECAST_SOURCE_LABELS = {
    PV_SOURCE_FORECAST_SOLAR: "forecast.solar",
    PV_SOURCE_OPEN_METEO: "Open-Meteo (best_match)",
}


def normalize_pv_forecast_source(raw: object) -> str | None:
    """Validated source, or None when the key is absent (stays absent on save)."""
    if raw is None:
        return None
    value = str(raw).strip()
    if value not in PV_FORECAST_SOURCES:
        raise ValueError(
            f"plant.{PV_FORECAST_SOURCE_KEY} muss {' oder '.join(PV_FORECAST_SOURCES)} "
            f"sein (ist {raw!r})."
        )
    return value


def plant_pv_forecast_source(house_doc: dict | None) -> str:
    """Primary source of a normalized house document; absent key → forecast.solar."""
    plant = (house_doc or {}).get("plant")
    if isinstance(plant, dict) and plant.get(PV_FORECAST_SOURCE_KEY):
        return str(plant[PV_FORECAST_SOURCE_KEY])
    return DEFAULT_PV_FORECAST_SOURCE


def substitute_source(primary: str) -> str:
    """The source asked when *primary* delivers nothing."""
    if primary == PV_SOURCE_OPEN_METEO:
        return PV_SOURCE_FORECAST_SOLAR
    return PV_SOURCE_OPEN_METEO

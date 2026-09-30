"""Hourly temperature overlays for HK Stündlicher Verlauf (Thermals P2 viz)."""
from __future__ import annotations

from data.consumption_profiles import (
    MODELED_PROFILE_HOURS_PER_YEAR,
    _modeled_hour_index,
    _parse_profile_timestamp,
)
from data.heating_need import heating_params_from_thermal

TEMP_AMBIENT = "ambient_c"
TEMP_HOUSE_SETPOINT = "house_setpoint_c"
TEMP_HOUSE = "house_c"
TEMP_HEAT_STORAGE = "heat_storage_c"

TEMP_LABELS = {
    TEMP_AMBIENT: "Außentemperatur",
    TEMP_HOUSE_SETPOINT: "Haus-Solltemperatur",
    TEMP_HOUSE: "Haus-Isttemperatur",
    TEMP_HEAT_STORAGE: "Wärmespeicher",
}

HC_HEAT_STORAGE = "heat_storage_q_kwh"
HC_LABELS = {
    HC_HEAT_STORAGE: "Wärmespeicher Wärmeinhalt (Modell)",
}


def _pad_or_trim(values: list[float], hours: int) -> list[float]:
    if len(values) >= hours:
        return values[:hours]
    pad = values[-1] if values else 0.0
    return values + [pad] * (hours - len(values))


def _series_from_year(
    year_values: list[float],
    timestamps: list[str],
) -> list[float]:
    if not year_values:
        return []
    out: list[float] = []
    for ts_raw in timestamps:
        index = _modeled_hour_index(_parse_profile_timestamp(ts_raw))
        if index < len(year_values):
            out.append(year_values[index])
        else:
            out.append(year_values[-1])
    return out


def _first_thermal_annual(profile: dict) -> dict | None:
    for consumer in profile.get("consumers", []):
        if not isinstance(consumer, dict):
            continue
        if consumer.get("type") == "thermal_annual":
            return consumer
    return None


def _thermal_rc_consumers(profile: dict) -> list[dict]:
    return [
        consumer
        for consumer in profile.get("consumers", [])
        if isinstance(consumer, dict) and consumer.get("type") == "thermal_rc"
    ]


def _location_and_timezone(profile: dict) -> tuple[float, float, str] | None:
    import config as cfg

    for consumer in profile.get("consumers", []):
        if not isinstance(consumer, dict):
            continue
        ctype = consumer.get("type")
        if ctype == "thermal_annual":
            thermal = consumer.get("thermal") or consumer
            lat, lon = thermal.get("latitude"), thermal.get("longitude")
            if lat is not None and lon is not None:
                tz = str(
                    thermal.get("timezone_name")
                    or (
                        cfg.get_planning_timezone()
                        if getattr(cfg, "CONFIG", None) is not None
                        else "Europe/Vienna"
                    )
                )
                return float(lat), float(lon), tz
        if ctype == "thermal_rc":
            rc = consumer.get("thermal_rc") or consumer
            lat, lon = rc.get("latitude"), rc.get("longitude")
            if lat is not None and lon is not None:
                tz = str(
                    rc.get("timezone_name")
                    or (
                        cfg.get_planning_timezone()
                        if getattr(cfg, "CONFIG", None) is not None
                        else "Europe/Vienna"
                    )
                )
                return float(lat), float(lon), tz
    return None


def _collector_surfaces_for_thermal(
    profile: dict,
    thermal_annual: dict | None,
) -> tuple[list, object | None, float]:
    """Return (surfaces, collector_or_None, area_m2) for Open-Meteo climate fetch."""
    if thermal_annual is None:
        return [], None, 0.0
    thermal = thermal_annual.get("thermal") or thermal_annual
    area_m2 = float(thermal.get("solar_thermal_area_m2", 0.0) or 0.0)
    if area_m2 <= 0.0:
        return [], None, 0.0
    from data.modeled_climate import collector_surface_from_thermal

    collector = collector_surface_from_thermal(thermal, profile)
    return [collector], collector, area_m2


def _climate_for_temperature_chart(
    profile: dict,
    thermal_annual: dict | None,
    lat: float,
    lon: float,
    timezone: str,
    *,
    hours: int,
) -> tuple[list[float] | None, object | None, object | None]:
    """Ambient list, hourly temp Series, optional collector wm2 Series."""
    import config as cfg

    if getattr(cfg, "CONFIG", None) is None:
        return None, None, None
    import pandas as pd

    from data.open_meteo_solar_archive import (
        build_open_meteo_climate_bundle_for_year,
        last_full_archive_year,
    )

    surfaces, collector, area_m2 = _collector_surfaces_for_thermal(
        profile, thermal_annual
    )
    year = last_full_archive_year()
    bundle = build_open_meteo_climate_bundle_for_year(
        year,
        lat=lat,
        lon=lon,
        timezone=timezone,
        surfaces=surfaces,
    )
    ambient = _pad_or_trim(
        [float(v) for v in bundle.temperature_c.tolist()], hours
    )
    idx = pd.date_range(f"{year}-01-01", periods=len(ambient), freq="h")
    hourly_temp = pd.Series(ambient, index=idx)
    hourly_wm2 = None
    if area_m2 > 0.0 and collector is not None:
        hourly_wm2 = bundle.collector_surface_series(collector)
    return ambient, hourly_temp, hourly_wm2


def _house_year_temps(
    consumer: dict,
    *,
    hours: int,
    hourly_temperature_c,
    hourly_collector_wm2=None,
) -> tuple[list[float] | None, list[float] | None]:
    """Return (house_temps, store_temps); store None when heat_storage disabled."""
    thermal = consumer.get("thermal") or consumer
    if float(thermal.get("living_area_m2", 0.0) or 0.0) <= 0.0:
        return None, None
    params = heating_params_from_thermal(thermal)
    if "hp_electric_kw" not in params:
        params["hp_electric_kw"] = float(consumer.get("nominal_power_kw", 3.0) or 3.0)
    from optimizer.thermal_house import house_year_result

    result = house_year_result(
        **params,
        hourly_temperature_c=hourly_temperature_c,
        hourly_collector_wm2=hourly_collector_wm2,
    )
    house = _pad_or_trim(result.hourly_house_temp_c, hours)
    store = (
        _pad_or_trim(result.hourly_store_temp_c, hours)
        if result.hourly_store_temp_c
        else None
    )
    return house, store


def _pool_temps(
    consumer: dict,
    ambient: list[float],
    *,
    hours: int,
) -> list[float] | None:
    from house_config.thermal_rc_profile import thermal_rc_hourly_kw_and_temp_from_ambient

    try:
        _kw, temps = thermal_rc_hourly_kw_and_temp_from_ambient(consumer, ambient)
    except (ValueError, KeyError, TypeError):
        return None
    return _pad_or_trim(temps, hours)


def _consumer_label(consumer: dict, fallback: str) -> str:
    label = str(consumer.get("label") or consumer.get("name") or "").strip()
    return label or fallback


def build_modeled_temperature_series(
    profile: dict,
    *,
    hours: int = MODELED_PROFILE_HOURS_PER_YEAR,
) -> tuple[dict[str, list[float]], dict[str, str]]:
    """Hour-of-year temperature series for HK charts; empty when no thermal data."""
    series: dict[str, list[float]] = {}
    labels: dict[str, str] = {}

    thermal_annual = _first_thermal_annual(profile)
    if thermal_annual is not None:
        thermal = thermal_annual.get("thermal") or thermal_annual
        setpoint = float(thermal.get("target_temp_c", 21.5))
        series[TEMP_HOUSE_SETPOINT] = [setpoint] * hours
        labels[TEMP_HOUSE_SETPOINT] = TEMP_LABELS[TEMP_HOUSE_SETPOINT]

    location = _location_and_timezone(profile)
    ambient: list[float] | None = None
    hourly_temp_series = None
    hourly_collector_wm2 = None
    if location is not None:
        lat, lon, timezone = location
        ambient, hourly_temp_series, hourly_collector_wm2 = (
            _climate_for_temperature_chart(
                profile,
                thermal_annual,
                lat,
                lon,
                timezone,
                hours=hours,
            )
        )
        if ambient:
            series[TEMP_AMBIENT] = ambient
            labels[TEMP_AMBIENT] = TEMP_LABELS[TEMP_AMBIENT]

    if thermal_annual is not None and hourly_temp_series is not None:
        house_ist, store = _house_year_temps(
            thermal_annual,
            hours=hours,
            hourly_temperature_c=hourly_temp_series,
            hourly_collector_wm2=hourly_collector_wm2,
        )
        if house_ist:
            series[TEMP_HOUSE] = house_ist
            labels[TEMP_HOUSE] = TEMP_LABELS[TEMP_HOUSE]
        if store:
            series[TEMP_HEAT_STORAGE] = store
            labels[TEMP_HEAT_STORAGE] = TEMP_LABELS[TEMP_HEAT_STORAGE]

    if ambient:
        for index, consumer in enumerate(_thermal_rc_consumers(profile)):
            pool = _pool_temps(consumer, ambient, hours=hours)
            if not pool:
                continue
            cid = str(consumer.get("id") or f"pool_{index}")
            key = f"pool_{cid}"
            series[key] = pool
            labels[key] = _consumer_label(consumer, "Pool")

    return series, labels


def temperature_series_for_timestamps(
    profile: dict,
    timestamps: list[str],
) -> tuple[dict[str, list[float]], dict[str, str]]:
    """Align year temperature series to arbitrary chart timestamps."""
    if not timestamps:
        return {}, {}
    year_series, labels = build_modeled_temperature_series(profile)
    if not year_series:
        return {}, {}
    aligned = {
        key: _series_from_year(values, timestamps)
        for key, values in year_series.items()
    }
    return aligned, labels


def _heat_storage_capacity_kwh_per_k(profile: dict) -> float | None:
    from optimizer.thermal_coupled import normalize_heat_storage
    from optimizer.thermal_model import capacity_kwh_per_k_from_volume

    thermal_annual = _first_thermal_annual(profile)
    if thermal_annual is None:
        return None
    thermal = thermal_annual.get("thermal") or thermal_annual
    storage = normalize_heat_storage(thermal.get("heat_storage"))
    if storage is None:
        return None
    return capacity_kwh_per_k_from_volume(storage["volume_liters"])


def _pool_capacity_kwh_per_k(consumer: dict) -> float | None:
    from optimizer.thermal_model import capacity_kwh_per_k_from_volume

    rc = consumer.get("thermal_rc") or consumer
    try:
        volume = float(rc.get("water_volume_liters", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    if volume <= 0.0:
        return None
    return capacity_kwh_per_k_from_volume(volume)


def heat_content_from_temperature_series(
    profile: dict,
    temp_series: dict[str, list[float]],
) -> tuple[dict[str, list[float]], dict[str, str]]:
    """Derive Q_sim = C × T (ref 0 °C) for heat storage and pools from temp overlays."""
    from optimizer.thermal_model import heat_content_kwh

    series: dict[str, list[float]] = {}
    labels: dict[str, str] = {}

    store_temps = temp_series.get(TEMP_HEAT_STORAGE) or []
    store_c = _heat_storage_capacity_kwh_per_k(profile)
    if store_temps and store_c is not None:
        series[HC_HEAT_STORAGE] = [
            heat_content_kwh(temp_c, store_c) for temp_c in store_temps
        ]
        labels[HC_HEAT_STORAGE] = HC_LABELS[HC_HEAT_STORAGE]

    for index, consumer in enumerate(_thermal_rc_consumers(profile)):
        cid = str(consumer.get("id") or f"pool_{index}")
        temp_key = f"pool_{cid}"
        pool_temps = temp_series.get(temp_key) or []
        pool_c = _pool_capacity_kwh_per_k(consumer)
        if not pool_temps or pool_c is None:
            continue
        hc_key = f"pool_q_{cid}"
        series[hc_key] = [
            heat_content_kwh(temp_c, pool_c) for temp_c in pool_temps
        ]
        labels[hc_key] = (
            f"{_consumer_label(consumer, 'Pool')} Wärmeinhalt (Modell)"
        )

    return series, labels


def heat_content_series_for_timestamps(
    profile: dict,
    timestamps: list[str],
) -> tuple[dict[str, list[float]], dict[str, str]]:
    """Align year heat-content series to chart timestamps (via temperature HOY)."""
    temps, _ = temperature_series_for_timestamps(profile, timestamps)
    if not temps:
        return {}, {}
    return heat_content_from_temperature_series(profile, temps)

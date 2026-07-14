"""RC-Modell Jahresprofil für thermal_rc-Verbraucher (z. B. SwimSpa)."""
from __future__ import annotations

from optimizer.thermal_model import (
    ThermalBand,
    capacity_kwh_per_k_from_volume,
    simulate_next_temp_c,
)


def thermal_rc_params(consumer: dict) -> dict:
    nested = consumer.get("thermal_rc")
    if isinstance(nested, dict):
        return nested
    return consumer


def _needs_heat(next_temp_c: float, band: ThermalBand) -> bool:
    return next_temp_c < band.min_c - 1e-9


def thermal_rc_hourly_kw_from_ambient(
    consumer: dict,
    ambient_c: list[float],
    *,
    start_temp_c: float | None = None,
) -> list[float]:
    """Stündliches Heizprofil (kW) aus RC-Modell und Außentemperatur-Reihe."""
    rc = thermal_rc_params(consumer)
    band = ThermalBand(
        setpoint_c=float(rc["setpoint_c"]),
        tolerance_c=float(rc["tolerance_c"]),
    )
    capacity = capacity_kwh_per_k_from_volume(float(rc["water_volume_liters"]))
    heat_loss = float(rc["heat_loss_kw_per_k"])
    efficiency = float(rc["heating_efficiency"])
    heat_paths = rc.get("heat_paths")
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    if nominal <= 0.0:
        raise ValueError("thermal_rc nominal_power_kw muss > 0 sein.")

    temp = float(start_temp_c if start_temp_c is not None else band.setpoint_c)
    hourly: list[float] = []
    for ambient in ambient_c:
        next_no_heat = simulate_next_temp_c(
            temp,
            float(ambient),
            0.0,
            capacity_kwh_per_k=capacity,
            heat_loss_kw_per_k=heat_loss,
            heating_efficiency=efficiency,
            extra_heat_paths=heat_paths if isinstance(heat_paths, list) else None,
        )
        if _needs_heat(next_no_heat, band):
            hourly.append(nominal)
            temp = simulate_next_temp_c(
                temp,
                float(ambient),
                nominal,
                capacity_kwh_per_k=capacity,
                heat_loss_kw_per_k=heat_loss,
                heating_efficiency=efficiency,
                extra_heat_paths=heat_paths if isinstance(heat_paths, list) else None,
            )
        else:
            hourly.append(0.0)
            temp = next_no_heat
    return hourly


def _planning_timezone_for_rc(rc: dict) -> str:
    tz = rc.get("timezone_name")
    if tz:
        return str(tz)
    import config

    return str(config.get_planning_timezone())


def estimate_thermal_rc_annual_kwh(
    consumer: dict,
    *,
    reference_year: int | None = None,
) -> tuple[float, int]:
    """
    Jahresenergie (kWh/a) aus RC-Simulation am Standort (Open-Meteo-Archiv).

    Returns (annual_kwh, reference_year).
    """
    from data.open_meteo_solar_archive import (
        build_open_meteo_climate_bundle_for_year,
        last_full_archive_year,
    )

    rc = thermal_rc_params(consumer)
    lat = rc.get("latitude")
    lon = rc.get("longitude")
    if lat is None or lon is None:
        raise ValueError(
            "thermal_rc Jahresverbrauch erfordert latitude/longitude "
            "(vom Hausprofil beim Laden gesetzt)."
        )
    year = reference_year if reference_year is not None else last_full_archive_year()
    bundle = build_open_meteo_climate_bundle_for_year(
        year,
        lat=float(lat),
        lon=float(lon),
        timezone=_planning_timezone_for_rc(rc),
        surfaces=[],
    )
    hourly = thermal_rc_hourly_kw_from_ambient(consumer, bundle.temperature_c)
    return round(sum(hourly), 3), year

"""Thermisches RC-Modell für temperaturgeführte Verbraucher."""
from __future__ import annotations

from dataclasses import dataclass


def capacity_kwh_per_k_from_volume(volume_liters: float) -> float:
    """Wärmekapazität C in kWh/K aus Wasservolumen (Liter)."""
    volume_liters = float(volume_liters)
    if volume_liters <= 0:
        raise ValueError("water_volume_liters muss > 0 sein")
    return (volume_liters / 1000.0) * 1.163


def simulate_next_temp_c(
    temp_c: float,
    ambient_c: float,
    heat_kw: float,
    *,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    heating_efficiency: float,
) -> float:
    """Einfaches Euler-Schritt für eine Stunde."""
    if capacity_kwh_per_k <= 0:
        raise ValueError("capacity_kwh_per_k muss > 0 sein")
    if heat_loss_kw_per_k < 0:
        raise ValueError("heat_loss_kw_per_k muss >= 0 sein")
    if not 0.0 < heating_efficiency <= 1.0:
        raise ValueError("heating_efficiency muss zwischen 0 (exkl.) und 1 liegen")
    loss_kw = heat_loss_kw_per_k * (float(temp_c) - float(ambient_c))
    net_kw = float(heat_kw) * heating_efficiency - loss_kw
    return float(temp_c) + net_kw / capacity_kwh_per_k


@dataclass(frozen=True)
class ThermalBand:
    setpoint_c: float
    tolerance_c: float

    @property
    def min_c(self) -> float:
        return self.setpoint_c - self.tolerance_c

    @property
    def max_c(self) -> float:
        return self.setpoint_c + self.tolerance_c


@dataclass(frozen=True)
class ThermalPlanResult:
    required_kwh: float
    heating_hours: int
    band: ThermalBand
    ambient_source: str
    heat_loss_kw_per_k: float
    capacity_kwh_per_k: float
    start_temp_c: float
    forecast_temp_c: list[float]
    forecast_temp_no_heat_c: list[float]
    heating_schedule: list[int]


def _needs_heat(next_temp_c: float, band: ThermalBand) -> bool:
    return next_temp_c < band.min_c - 1e-9


def plan_minimum_heating(
    *,
    start_temp_c: float,
    ambient_forecast_c: list[float],
    band: ThermalBand,
    heat_power_kw: float,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    heating_efficiency: float,
) -> ThermalPlanResult:
    """Mindest-Heizenergie (kWh), damit die simulierte Ist-Temp. im Band bleibt."""
    if heat_power_kw <= 0:
        raise ValueError("heat_power_kw muss > 0 sein")
    horizon = len(ambient_forecast_c)
    if horizon < 1:
        raise ValueError("ambient_forecast_c darf nicht leer sein")

    temp = float(start_temp_c)
    no_heat: list[float] = []
    with_heat: list[float] = []
    heating_hours: list[int] = []

    for hour, ambient_c in enumerate(ambient_forecast_c):
        next_no_heat = simulate_next_temp_c(
            temp,
            ambient_c,
            0.0,
            capacity_kwh_per_k=capacity_kwh_per_k,
            heat_loss_kw_per_k=heat_loss_kw_per_k,
            heating_efficiency=heating_efficiency,
        )
        no_heat.append(round(next_no_heat, 3))

        if _needs_heat(next_no_heat, band):
            temp = simulate_next_temp_c(
                temp,
                ambient_c,
                heat_power_kw,
                capacity_kwh_per_k=capacity_kwh_per_k,
                heat_loss_kw_per_k=heat_loss_kw_per_k,
                heating_efficiency=heating_efficiency,
            )
            heating_hours.append(hour)
        else:
            temp = next_no_heat
        with_heat.append(round(temp, 3))

    required_kwh = round(len(heating_hours) * float(heat_power_kw), 3)
    return ThermalPlanResult(
        required_kwh=required_kwh,
        heating_hours=len(heating_hours),
        band=band,
        ambient_source="",
        heat_loss_kw_per_k=heat_loss_kw_per_k,
        capacity_kwh_per_k=capacity_kwh_per_k,
        start_temp_c=round(float(start_temp_c), 3),
        forecast_temp_c=with_heat,
        forecast_temp_no_heat_c=no_heat,
        heating_schedule=heating_hours,
    )

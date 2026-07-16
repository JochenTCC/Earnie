"""Open-Meteo-Klimakontext für modellierte Verbraucher und Backtesting-PV."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd

import config
from data.heating_need import (
    daily_electric_kwh,
    heating_params_from_thermal,
    hourly_profile_for_year,
    thermal_daily_pwm_hourly_profile,
    weekly_electric_kwh,
)
from data.open_meteo_solar_archive import (
    OpenMeteoClimateBundle,
    TiltedSurface,
    build_open_meteo_climate_bundle,
    build_open_meteo_climate_bundle_for_year,
    last_full_archive_year,
)


def collector_surface_from_thermal(thermal: dict, profile: dict) -> TiltedSurface:
    tilt = float(
        thermal.get(
            "solar_thermal_tilt_deg",
            profile.get("default_pv_tilt", 18.0),
        )
    )
    azimuth = float(
        thermal.get(
            "solar_thermal_azimuth_deg",
            profile.get("default_pv_azimuth", 0.0),
        )
    )
    return TiltedSurface(tilt_deg=tilt, azimuth_deg=azimuth)


def pv_surface_from_profile(
    profile: dict | None,
    *,
    pv_tilt: float | None = None,
    pv_azimuth: float | None = None,
) -> TiltedSurface:
    if pv_tilt is None:
        if profile:
            pv_tilt = float(profile.get("default_pv_tilt", 18.0))
        else:
            pv_tilt = float(config.get("PV_TILT", cast=float))
    if pv_azimuth is None:
        if profile:
            pv_azimuth = float(profile.get("default_pv_azimuth", 0.0))
        else:
            pv_azimuth = float(config.get("PV_AZIMUTH", cast=float))
    return TiltedSurface(tilt_deg=float(pv_tilt), azimuth_deg=float(pv_azimuth))


def _surfaces_for_profile(
    profile: dict | None,
    pv_surfaces: list[TiltedSurface],
) -> list[TiltedSurface]:
    surfaces = list(pv_surfaces)
    seen = {
        (round(surface.tilt_deg, 3), round(surface.azimuth_deg, 3))
        for surface in surfaces
    }
    if not profile:
        return surfaces
    for consumer in profile.get("consumers", []):
        if consumer.get("type") != "thermal_annual":
            continue
        thermal = consumer.get("thermal") or consumer
        area_m2 = float(thermal.get("solar_thermal_area_m2", 0.0) or 0.0)
        if area_m2 <= 0.0:
            continue
        surface = collector_surface_from_thermal(thermal, profile)
        key = (round(surface.tilt_deg, 3), round(surface.azimuth_deg, 3))
        if key in seen:
            continue
        seen.add(key)
        surfaces.append(surface)
    return surfaces


@dataclass(frozen=True)
class ModeledPvSystem:
    """One PV array (surface + kWp) for modeled production."""

    id: str
    label: str
    surface: TiltedSurface
    kwp: float


def _planning_systems_from_scenario(scenario_params: dict) -> list[ModeledPvSystem]:
    planning = scenario_params.get("_planning_pv_systems")
    if isinstance(planning, list) and planning:
        systems: list[ModeledPvSystem] = []
        for index, item in enumerate(planning):
            if not isinstance(item, dict):
                continue
            pv_id = str(item.get("id") or f"pv_{index}").strip() or f"pv_{index}"
            label = str(item.get("label") or pv_id).strip() or pv_id
            systems.append(
                ModeledPvSystem(
                    id=pv_id,
                    label=label,
                    surface=TiltedSurface(
                        tilt_deg=float(item.get("pv_tilt", 0.0) or 0.0),
                        azimuth_deg=float(item.get("pv_azimuth", 0.0) or 0.0),
                    ),
                    kwp=float(item.get("pv_kwp", 0.0) or 0.0),
                )
            )
        if systems:
            return systems

    profile = scenario_params.get("_house_profile")
    if not isinstance(profile, dict):
        profile = None
    kwp = float(scenario_params.get("pv_kwp", 0.0) or 0.0)
    surface = pv_surface_from_profile(
        profile,
        pv_tilt=(
            float(scenario_params["pv_tilt"])
            if "pv_tilt" in scenario_params
            else None
        ),
        pv_azimuth=(
            float(scenario_params["pv_azimuth"])
            if "pv_azimuth" in scenario_params
            else None
        ),
    )
    if kwp <= 0.0 and "pv_tilt" not in scenario_params and "pv_azimuth" not in scenario_params:
        return []
    return [
        ModeledPvSystem(
            id="pv",
            label="PV",
            surface=surface,
            kwp=kwp,
        )
    ]


def _single_system(
    *,
    profile: dict | None,
    kwp: float,
    pv_tilt: float | None = None,
    pv_azimuth: float | None = None,
    system_id: str = "pv",
    label: str = "PV",
) -> list[ModeledPvSystem]:
    if float(kwp) <= 0.0:
        return []
    return [
        ModeledPvSystem(
            id=system_id,
            label=label,
            surface=pv_surface_from_profile(
                profile,
                pv_tilt=pv_tilt,
                pv_azimuth=pv_azimuth,
            ),
            kwp=float(kwp),
        )
    ]


def _slot_hour_index_in_year(slot_dt: datetime) -> int:
    year_start = datetime(slot_dt.year, 1, 1)
    naive = slot_dt.replace(tzinfo=None) if slot_dt.tzinfo else slot_dt
    index = int((naive - year_start).total_seconds() // 3600)
    return max(0, min(index, 8759))


@dataclass
class ModeledClimateContext:
    """Gemeinsame Open-Meteo-Quelle für PV und Solar-Kollektor."""

    lat: float
    lon: float
    timezone: str
    pv_systems: list[ModeledPvSystem] = field(default_factory=list)
    house_profile: dict | None = None
    _range_bundles: dict[tuple[date, date], OpenMeteoClimateBundle] = field(
        default_factory=dict,
        repr=False,
    )
    _year_bundles: dict[int, OpenMeteoClimateBundle] = field(
        default_factory=dict,
        repr=False,
    )
    _thermal_year_profiles: dict[tuple[str, int], list[float]] = field(
        default_factory=dict,
        repr=False,
    )
    _thermal_rc_year_profiles: dict[tuple[str, int], list[float]] = field(
        default_factory=dict,
        repr=False,
    )

    @property
    def pv_kwp(self) -> float:
        return sum(float(system.kwp) for system in self.pv_systems)

    @property
    def pv_surface(self) -> TiltedSurface:
        if self.pv_systems:
            return self.pv_systems[0].surface
        return pv_surface_from_profile(self.house_profile)

    def _pv_surfaces(self) -> list[TiltedSurface]:
        if self.pv_systems:
            return [system.surface for system in self.pv_systems]
        return [self.pv_surface]

    @classmethod
    def for_house_profile(cls, profile: dict, *, kwp: float) -> ModeledClimateContext:
        lat = float(profile["latitude"])
        lon = float(profile["longitude"])
        timezone = str(profile.get("timezone_name") or config.get_planning_timezone())
        return cls(
            lat=lat,
            lon=lon,
            timezone=timezone,
            pv_systems=_single_system(profile=profile, kwp=kwp),
            house_profile=profile,
        )

    @classmethod
    def from_config(cls, *, kwp: float | None = None) -> ModeledClimateContext:
        lat = float(config.get("LATITUDE", cast=float))
        lon = float(config.get("LONGITUDE", cast=float))
        timezone = str(config.get_planning_timezone())
        resolved_kwp = float(kwp if kwp is not None else config.get("PV_KWP", cast=float))
        return cls(
            lat=lat,
            lon=lon,
            timezone=timezone,
            pv_systems=_single_system(profile=None, kwp=resolved_kwp),
            house_profile=None,
        )

    @classmethod
    def from_scenario(cls, scenario_params: dict) -> ModeledClimateContext:
        profile = scenario_params.get("_house_profile")
        if not isinstance(profile, dict):
            profile = None
        systems = _planning_systems_from_scenario(scenario_params)
        if profile is not None:
            lat = float(profile["latitude"])
            lon = float(profile["longitude"])
            timezone = str(profile.get("timezone_name") or config.get_planning_timezone())
        else:
            lat = float(config.get("LATITUDE", cast=float))
            lon = float(config.get("LONGITUDE", cast=float))
            timezone = str(config.get_planning_timezone())
        ctx = cls(
            lat=lat,
            lon=lon,
            timezone=timezone,
            pv_systems=systems,
            house_profile=profile,
        )
        if "latitude" in scenario_params:
            ctx.lat = float(scenario_params["latitude"])
        if "longitude" in scenario_params:
            ctx.lon = float(scenario_params["longitude"])
        if scenario_params.get("timezone_name"):
            ctx.timezone = str(scenario_params["timezone_name"])
        return ctx

    def _bundle_for_calendar_year(self, year: int) -> OpenMeteoClimateBundle:
        if year not in self._year_bundles:
            self._year_bundles[year] = build_open_meteo_climate_bundle_for_year(
                year,
                lat=self.lat,
                lon=self.lon,
                timezone=self.timezone,
                surfaces=_surfaces_for_profile(self.house_profile, self._pv_surfaces()),
            )
        return self._year_bundles[year]

    def bundle_for_range(self, start: date, end: date) -> OpenMeteoClimateBundle:
        key = (start, end)
        if key not in self._range_bundles:
            self._range_bundles[key] = build_open_meteo_climate_bundle(
                start,
                end,
                lat=self.lat,
                lon=self.lon,
                timezone=self.timezone,
                surfaces=_surfaces_for_profile(self.house_profile, self._pv_surfaces()),
            )
        return self._range_bundles[key]

    def pv_kw_at(self, slot_dt: datetime) -> float:
        bundle = self._bundle_for_calendar_year(slot_dt.year)
        total = 0.0
        for system in self.pv_systems:
            total += bundle.pv_kw_at(system.surface, system.kwp, slot_dt)
        return total

    def pv_kw_for_slots(self, slot_datetimes: list[datetime]) -> list[float]:
        return [self.pv_kw_at(slot_dt) for slot_dt in slot_datetimes]

    def pv_kw_by_system_for_slots(
        self,
        slot_datetimes: list[datetime],
    ) -> dict[str, list[float]]:
        """Per-system kW series keyed by PV system id (for weekly charts)."""
        if not self.pv_systems:
            return {}
        by_year: dict[int, OpenMeteoClimateBundle] = {}
        result: dict[str, list[float]] = {
            system.id: [] for system in self.pv_systems
        }
        for slot_dt in slot_datetimes:
            year = slot_dt.year
            if year not in by_year:
                by_year[year] = self._bundle_for_calendar_year(year)
            bundle = by_year[year]
            for system in self.pv_systems:
                result[system.id].append(
                    bundle.pv_kw_at(system.surface, system.kwp, slot_dt)
                )
        return result

    def pv_system_labels(self) -> dict[str, str]:
        return {system.id: system.label for system in self.pv_systems}

    def _thermal_hourly_profile_for_year(self, consumer: dict, year: int) -> list[float]:
        consumer_id = str(consumer.get("id") or consumer.get("label") or "thermal")
        key = (consumer_id, year)
        if key in self._thermal_year_profiles:
            return self._thermal_year_profiles[key]

        bundle = self._bundle_for_calendar_year(year)
        thermal = consumer.get("thermal") or consumer
        params = heating_params_from_thermal(thermal)
        area_m2 = float(params.get("solar_thermal_area_m2", 0.0) or 0.0)
        hourly_wm2 = None
        if area_m2 > 0.0:
            surface = collector_surface_from_thermal(
                thermal,
                self.house_profile or {},
            )
            hourly_wm2 = bundle.collector_surface_series(surface)

        daily = daily_electric_kwh(
            **params,
            hourly_temperature_c=bundle.temperature_c,
            hourly_collector_wm2=hourly_wm2,
        )
        nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
        if nominal > 0.0:
            profile = thermal_daily_pwm_hourly_profile(
                daily,
                nominal_power_kw=nominal,
                hours_per_year=8760,
            )
        else:
            weekly = weekly_electric_kwh(
                **params,
                hourly_temperature_c=bundle.temperature_c,
                hourly_collector_wm2=hourly_wm2,
            )
            profile = hourly_profile_for_year(weekly, hours_per_year=8760)
        self._thermal_year_profiles[key] = profile
        return profile

    def thermal_consumer_kw_at(self, consumer: dict, slot_dt: datetime) -> float:
        profile = self._thermal_hourly_profile_for_year(consumer, slot_dt.year)
        return float(profile[_slot_hour_index_in_year(slot_dt)])

    def _thermal_rc_archive_year(self, year: int) -> int:
        from data.open_meteo_solar_archive import archive_latest_complete_date

        if date(year, 12, 31) <= archive_latest_complete_date():
            return year
        return last_full_archive_year(reference=date(year, 1, 1))

    def _thermal_rc_hourly_profile_for_year(self, consumer: dict, year: int) -> list[float]:
        from house_config.thermal_rc_profile import thermal_rc_hourly_kw_from_ambient

        consumer_id = str(consumer.get("id") or consumer.get("label") or "thermal_rc")
        key = (consumer_id, year)
        if key in self._thermal_rc_year_profiles:
            return self._thermal_rc_year_profiles[key]

        archive_year = self._thermal_rc_archive_year(year)
        bundle = self._bundle_for_calendar_year(archive_year)
        profile = thermal_rc_hourly_kw_from_ambient(consumer, bundle.temperature_c)
        if len(profile) < 8760:
            pad = profile[-1] if profile else 0.0
            profile = profile + [pad] * (8760 - len(profile))
        self._thermal_rc_year_profiles[key] = profile
        return profile

    def thermal_rc_consumer_kw_at(self, consumer: dict, slot_dt: datetime) -> float:
        profile = self._thermal_rc_hourly_profile_for_year(consumer, slot_dt.year)
        return float(profile[_slot_hour_index_in_year(slot_dt)])

    def seed_year_bundle(self, year: int, bundle: OpenMeteoClimateBundle) -> None:
        """Test-Hilfe: vorgefertigtes Bundle für ein Kalenderjahr."""
        self._year_bundles[year] = bundle

    def seed_range_bundle(
        self,
        start: date,
        end: date,
        bundle: OpenMeteoClimateBundle,
    ) -> None:
        """Test-Hilfe: vorgefertigtes Bundle für einen Datumsbereich."""
        self._range_bundles[(start, end)] = bundle


def pv_kw_for_slots(
    slot_datetimes: list[datetime],
    scenario_params: dict,
) -> list[float]:
    climate = ModeledClimateContext.from_scenario(scenario_params)
    return climate.pv_kw_for_slots(slot_datetimes)


def _planning_timezone_for_thermal(thermal: dict, profile: dict) -> str:
    tz = thermal.get("timezone_name") or profile.get("timezone_name")
    if tz:
        return str(tz)
    getter = getattr(config, "get_planning_timezone", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            pass
    return "Europe/Berlin"


def thermal_annual_kwh_from_archive(
    thermal: dict,
    *,
    house_profile: dict | None = None,
    reference_year: int | None = None,
) -> tuple[float, int]:
    """
    WP-Jahresbedarf (kWh/a) aus Open-Meteo-Archiv am Standort.

    Returns (annual_kwh, reference_year).
    """
    year = reference_year if reference_year is not None else last_full_archive_year()
    lat = float(thermal["latitude"])
    lon = float(thermal["longitude"])
    profile = house_profile or {}
    timezone = _planning_timezone_for_thermal(thermal, profile)
    profile_stub = {
        **profile,
        "latitude": lat,
        "longitude": lon,
    }
    collector = collector_surface_from_thermal(thermal, profile_stub)
    bundle = build_open_meteo_climate_bundle_for_year(
        year,
        lat=lat,
        lon=lon,
        timezone=timezone,
        surfaces=[collector],
    )
    params = heating_params_from_thermal(thermal)
    area_m2 = float(params.get("solar_thermal_area_m2", 0.0) or 0.0)
    hourly_wm2 = bundle.collector_surface_series(collector) if area_m2 > 0.0 else None
    daily = daily_electric_kwh(
        **params,
        hourly_temperature_c=bundle.temperature_c,
        hourly_collector_wm2=hourly_wm2,
    )
    return round(sum(daily), 3), year

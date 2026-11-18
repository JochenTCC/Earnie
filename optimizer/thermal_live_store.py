"""Live open-loop heat-storage floor + opportunistic headroom (Thermals P2 / 2.7.b).

No MILP store-T SoC: physics stay outside the solver; callers get forced hours and
scalar kWh bounds only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any

from ehal.heat_fields import KIND_STORE_MAX
from optimizer.thermal_coupled import (
    heat_storage_enabled,
    normalize_heat_storage,
)
from optimizer.thermal_live_band import (  # noqa: F401  (re-exported)
    BAND_SOURCE_BACKEND,
    BAND_SOURCE_CONFIG,
    BAND_SOURCE_CONFIG_NO_VALUE,
    resolve_live_store_band,
)
from optimizer.thermal_model import ThermalBand, capacity_kwh_per_k_from_volume, heat_content_kwh
from optimizer.thermal_live_cop import (
    EFFICIENCY_JAZ_NO_SOURCE_VALUE,
    LiveEfficiency,
    efficiency_observability,
    resolve_live_efficiency,
    segment_cops,
    segment_edges_c,
)
from optimizer.thermal_store_model import StoreLevelModel, StoreSegment
from optimizer.thermal_live_solar import (  # noqa: F401  (re-exported)
    SOLAR_SOURCE_ARCHIVE_FALLBACK,
    SOLAR_SOURCE_FORECAST,
    SOLAR_SOURCE_NONE,
    _archive_year_collector_solar_kw,
    _profile_with_geo,
    resolve_live_collector_solar_kw,
)
from optimizer.thermal_live_floor import (  # noqa: F401  (re-exported)
    _HouseLiveParams,
    _MAX_HOUSE_CLIMB_K_PER_H,
    _apply_t_low_near_term_force,
    _resolve_house_live_params,
    _simulate_store_floor_hours,
    _space_heat_demand_kw,
    _ww_kw,
)
from optimizer.thermal_live_house import (  # noqa: F401  (re-exported)
    LiveHousePlan,
    _plan_live_legacy_ww,
    _thermal_with_nominal,
    plan_live_house_horizon,
)

logger = logging.getLogger(__name__)

EQ_SOURCE_MEASURED = "measured"
EQ_SOURCE_SETPOINT_NO_VALUE = "setpoint_no_value"
"""Observability ``eq_source``: T_eq had no value, the store plan started at the setpoint."""


@dataclass(frozen=True)
class HeatStorageReadings:
    temp_eq_c: float
    temp_low_c: float | None
    used_measured_eq: bool
    used_measured_low: bool


@dataclass(frozen=True)
class LiveStorePlan:
    forced_hour_flags: list[bool]
    floor_electric_kwh: float
    opp_cap_electric_kwh: float
    start_temp_c: float
    temp_low_c: float | None
    used_measured_eq: bool
    used_measured_low: bool
    band: ThermalBand
    electric_by_hour: list[float]
    store_temp_c: list[float] = field(default_factory=list)
    q_sim_kwh: list[float] = field(default_factory=list)
    # Collector heat input: SOLAR_SOURCE_* (ThermalHorizon P3); "provided" when passed in.
    solar_source: str = "provided"
    # Where ``band`` comes from: BAND_SOURCE_* (HeatControl P1).
    band_source: str = BAND_SOURCE_CONFIG
    # Mapped level 3 feedback reads of this cycle (kind → value, None = no value).
    feedback: dict[str, float | None] = field(default_factory=dict)
    # Fixed boost (K) above the setpoint that an Earnie charge reaches (HeatControl P2).
    boost_k: float = 0.0
    # Highest store temperature the controller reports (get_temperature_heat_storage_max).
    store_max_c: float | None = None
    # Inputs of the charge target (HeatControl P3): model and net draw per hour [kW].
    capacity_kwh_per_k: float = 0.0
    heat_loss_kw_per_k: float = 0.0
    jaz: float = 0.0
    ambient_c: list[float] = field(default_factory=list)
    draw_kw_by_hour: list[float] = field(default_factory=list)
    # Forecast collector heat into the store per hour [kW] (already part of the net draw).
    collector_kw_by_hour: list[float] = field(default_factory=list)
    # HeatControl P5: JAZ, or the COP curve with its source temperature.
    efficiency: LiveEfficiency = field(default_factory=LiveEfficiency)
    # The store target signal (level 2) is mapped: Earnie doses the charge itself.
    target_mapped: bool = False

    @property
    def charge_max_c(self) -> float:
        """Upper end of an Earnie charge.

        Levels 0 and 1: setpoint + boost, capped by the reported maximum. With the COP curve
        and the store target mapped (HeatControl P5) the band reaches the reported maximum;
        without a reported maximum it stays at setpoint + boost. COP points whose source
        signal sent no value: the setpoint, the cost above it is unknown in this cycle.
        """
        setpoint = float(self.band.setpoint_c)
        if self.efficiency.source == EFFICIENCY_JAZ_NO_SOURCE_VALUE:
            return setpoint
        if self.band_released:
            return max(float(self.store_max_c), setpoint)
        upper = setpoint + self.boost_k
        if self.store_max_c is not None:
            upper = min(upper, float(self.store_max_c))
        return max(upper, setpoint)

    @property
    def band_released(self) -> bool:
        """The band above the setpoint reaches ``get_temperature_heat_storage_max`` (P5)."""
        return (
            self.efficiency.by_temperature and self.target_mapped and self.store_max_c is not None
        )

    def hourly_draw_at_min_kw(self) -> list[float]:
        """Net draw per hour [kW] plus the store's loss at the band minimum (store level model)."""
        if len(self.ambient_c) < len(self.draw_kw_by_hour):
            raise ValueError("Speicherplan: Außentemperatur kürzer als die Wärmeentnahme.")
        t_min = float(self.band.min_c)
        return [
            float(draw) + self.heat_loss_kw_per_k * (t_min - float(self.ambient_c[hour]))
            for hour, draw in enumerate(self.draw_kw_by_hour)
        ]

    @property
    def charge_room_heat_kwh(self) -> float:
        """Heat [kWh] the store can take over the horizon: room up to the charge maximum plus
        the net draw and loss at the band minimum (HeatControl P4; gates whether Live plans)."""
        return self.charge_room_heat_kwh_within(float(len(self.draw_kw_by_hour)))

    def charge_room_heat_kwh_within(self, hours: float) -> float:
        """``charge_room_heat_kwh`` over the first ``hours`` of the horizon only.

        A fractional last hour counts with its share. Beside a fuel source this is what a
        heating rod may add on the first day: the room plus the heat the boiler would
        otherwise deliver in that time (the rod displaces it).
        """
        if hours < 0.0:
            raise ValueError(f"Speicherplan: Stunden dürfen nicht negativ sein (ist {hours:g}).")
        room = self.capacity_kwh_per_k * (self.charge_max_c - float(self.start_temp_c))
        draw = 0.0
        for hour, kw in enumerate(self.hourly_draw_at_min_kw()):
            share = min(1.0, hours - hour)
            if share <= 0.0:
                break
            draw += float(kw) * share
        return max(0.0, room + draw)

    @property
    def charge_room_electric_kwh(self) -> float:
        return self.charge_room_heat_kwh / self.jaz if self.jaz > 0 else 0.0


def resolve_heat_storage_setpoint_band(heat_storage: dict) -> ThermalBand:
    storage = normalize_heat_storage(heat_storage)
    if storage is None:
        raise ValueError("heat_storage ist nicht aktiv (volume_liters <= 0)")
    return ThermalBand(storage["setpoint_c"], storage["tolerance_c"])


def resolve_heat_storage_readings(
    consumer: dict,
    *,
    house_doc: dict | None = None,
    heat_storage: dict | None = None,
) -> HeatStorageReadings:
    """Read T_eq / T_low.

    A missing T_eq starts the plan at the store setpoint: a documented, visible default
    (warning per cycle, ``used_measured_eq`` False → observability ``eq_source``
    ``"setpoint_no_value"``; decided 2026-11-18 like the band's ``config_no_value``), so one
    missing reading does not stop the whole Live cycle.
    """
    from integrations.ehal_live import fetch_heat_storage_temps

    storage = normalize_heat_storage(
        heat_storage
        if heat_storage is not None
        else (consumer.get("thermal") or {}).get("heat_storage")
        or consumer.get("heat_storage")
    )
    if storage is None:
        raise ValueError("heat_storage ist nicht aktiv")
    band = ThermalBand(storage["setpoint_c"], storage["tolerance_c"])
    measured = fetch_heat_storage_temps(consumer, house_doc=house_doc)
    eq = measured.get("temp_eq_c")
    low = measured.get("temp_low_c")
    used_eq = eq is not None
    if not used_eq:
        logger.warning(
            "Wärmespeicher '%s': T_eq (sens_temperature_heat_storage) liefert keinen Wert – "
            "Speicherplan startet bei der Solltemperatur %.1f °C.",
            consumer.get("id") or "?",
            float(band.setpoint_c),
        )
    return HeatStorageReadings(
        temp_eq_c=float(eq) if used_eq else float(band.setpoint_c),
        temp_low_c=float(low) if low is not None else None,
        used_measured_eq=used_eq,
        used_measured_low=low is not None,
    )
















def plan_live_store_horizon(
    *,
    start_temp_c: float,
    ambient_forecast_c: list[float],
    band: ThermalBand,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    wp_electric_kw: float,
    jaz: float,
    temp_low_c: float | None = None,
    solar_forecast_kw: list[float] | None = None,
    living_area_m2: float = 0.0,
    building_mass: str | None = None,
    target_temp_c: float = 21.5,
    house_tolerance_c: float | None = None,
    house_heat_loss_kw_per_k: float | None = None,
    heating_limit_c: float = 15.0,
    persons: int = 2,
    start_house_temp_c: float | None = None,
    used_measured_eq: bool = False,
    used_measured_low: bool = False,
    gain_kw_by_hour: list[float] | None = None,
    boost_k: float = 0.0,
    store_max_c: float | None = None,
) -> LiveStorePlan:
    """Bang-bang floor on T_eq plus optional T_low near-term force; opp headroom.

    The floor simulates normal operation (charge ends at the setpoint). The opportunistic
    headroom reaches setpoint + ``boost_k``: an Earnie charge (enable 1 / SG-Ready state 3)
    ends there on levels 0 and 1 (HeatControl P2).
    """
    horizon = len(ambient_forecast_c)
    if horizon < 1:
        raise ValueError("ambient_forecast_c darf nicht leer sein")
    wp_kw = max(0.1, float(wp_electric_kw))
    jaz_f = max(1e-9, float(jaz))
    solar = list(solar_forecast_kw or [0.0] * horizon)
    if len(solar) < horizon:
        solar = solar + [0.0] * (horizon - len(solar))
    house = _resolve_house_live_params(
        living_area_m2=living_area_m2,
        building_mass=building_mass,
        target_temp_c=target_temp_c,
        house_tolerance_c=house_tolerance_c,
        house_heat_loss_kw_per_k=house_heat_loss_kw_per_k,
        heating_limit_c=heating_limit_c,
        start_house_temp_c=start_house_temp_c,
        max_heat=wp_kw * jaz_f,
    )
    forced, electric_by_hour, floor_electric, store_temps, draw_kw = _simulate_store_floor_hours(
        start_temp_c=start_temp_c,
        ambient_forecast_c=ambient_forecast_c,
        solar=solar,
        band=band,
        capacity_kwh_per_k=capacity_kwh_per_k,
        heat_loss_kw_per_k=heat_loss_kw_per_k,
        wp_kw=wp_kw,
        jaz_f=jaz_f,
        ww=_ww_kw(persons),
        house=house,
        gain_kw_by_hour=gain_kw_by_hour,
    )
    forced, electric_by_hour, floor_electric, low_forced = _apply_t_low_near_term_force(
        forced,
        electric_by_hour,
        floor_electric,
        temp_low_c=temp_low_c,
        band=band,
        wp_kw=wp_kw,
    )
    if boost_k < 0.0:
        raise ValueError(f"boost_k darf nicht negativ sein (ist {boost_k:g} K).")
    charge_max = band.setpoint_c + float(boost_k)
    if store_max_c is not None:
        charge_max = max(band.setpoint_c, min(charge_max, float(store_max_c)))
    fill_thermal = max(0.0, (charge_max - float(start_temp_c)) * capacity_kwh_per_k)
    opp_cap = max(0.0, fill_thermal / jaz_f - floor_electric)
    q_sim = [
        heat_content_kwh(temp_c, capacity_kwh_per_k) for temp_c in store_temps
    ]
    return LiveStorePlan(
        forced_hour_flags=forced,
        floor_electric_kwh=round(floor_electric, 3),
        opp_cap_electric_kwh=round(opp_cap, 3),
        start_temp_c=round(float(start_temp_c), 3),
        temp_low_c=None if temp_low_c is None else round(float(temp_low_c), 3),
        used_measured_eq=bool(used_measured_eq),
        used_measured_low=bool(used_measured_low) or low_forced,
        band=band,
        electric_by_hour=electric_by_hour,
        store_temp_c=store_temps,
        q_sim_kwh=q_sim,
        boost_k=float(boost_k),
        store_max_c=None if store_max_c is None else float(store_max_c),
        capacity_kwh_per_k=float(capacity_kwh_per_k),
        heat_loss_kw_per_k=float(heat_loss_kw_per_k),
        jaz=jaz_f,
        ambient_c=[float(v) for v in ambient_forecast_c],
        draw_kw_by_hour=draw_kw,
        collector_kw_by_hour=[float(v) for v in solar[:horizon]],
    )










def plan_live_store_for_thermal_consumer(
    consumer: dict,
    *,
    house_profile: dict,
    ambient_forecast_c: list[float],
    solar_forecast_kw: list[float] | None = None,
    house_doc: dict | None = None,
    baseload_kw_by_hour: list[float] | None = None,
) -> LiveStorePlan | None:
    """Build Live store plan from a thermal_annual house consumer; None if no store.

    House gains (SUSI P2): Grundlast from ``baseload_kw_by_hour`` (matrix forecast) or, without
    it, the flat Grundlast of the year model; windows from the forecast.
    """
    from house_config.heat_source import consumer_heat_source, heat_source_efficiency

    thermal = consumer.get("thermal") or consumer
    storage_raw = thermal.get("heat_storage")
    if not heat_storage_enabled(storage_raw):
        return None
    storage = normalize_heat_storage(storage_raw)
    if storage is None:
        return None
    resolved_solar = solar_forecast_kw
    solar_source = "provided"
    if resolved_solar is None:
        resolved_solar, solar_source = resolve_live_collector_solar_kw(
            thermal, house_profile, len(ambient_forecast_c)
        )
    from integrations.ehal_live import fetch_heat_feedback

    # The backend owns the band where it reports it; read every cycle, held over the horizon.
    live_band = resolve_live_store_band(
        consumer, ThermalBand(storage["setpoint_c"], storage["tolerance_c"])
    )
    band = live_band.band
    readings = resolve_heat_storage_readings(
        consumer,
        house_doc=house_doc,
        heat_storage={**storage, "setpoint_c": band.setpoint_c, "tolerance_c": band.tolerance_c},
    )
    # Read in the planning path so the cycle recorder stores them like the store temperatures.
    feedback = fetch_heat_feedback(consumer)
    capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
    # Derived input power of the heating system; missing fails loud (no 3 kW default).
    wp_kw = float(_thermal_with_nominal(thermal, consumer)["nominal_power_kw"])
    living = float(thermal.get("living_area_m2", 0.0) or 0.0)
    house_h = None
    gains: list[float] | None = None
    if living > 0.0:
        from optimizer.thermal_live_gains import live_gain_kw_by_hour
        from optimizer.thermal_parameters import house_thermal_parameters
        from runtime_store.planning_clock import planning_now

        house_h = house_thermal_parameters(
            _thermal_with_nominal(thermal, consumer), house_profile=house_profile
        ).house_heat_loss_kw_per_k
        gains, _gain_source = live_gain_kw_by_hour(
            consumer,
            house_profile,
            start=planning_now(),
            horizon=len(ambient_forecast_c),
            baseload_kw_by_hour=baseload_kw_by_hour,
        )
    plan = plan_live_store_horizon(
        start_temp_c=readings.temp_eq_c,
        ambient_forecast_c=ambient_forecast_c,
        band=band,
        capacity_kwh_per_k=capacity,
        heat_loss_kw_per_k=float(storage["heat_loss_kw_per_k"]),
        wp_electric_kw=wp_kw,
        jaz=heat_source_efficiency(consumer_heat_source(consumer)),
        temp_low_c=readings.temp_low_c,
        solar_forecast_kw=resolved_solar,
        living_area_m2=living,
        building_mass=thermal.get("building_mass"),
        target_temp_c=float(thermal.get("target_temp_c", 21.5) or 21.5),
        house_tolerance_c=thermal.get("house_tolerance_c"),
        house_heat_loss_kw_per_k=house_h,
        heating_limit_c=float(thermal.get("heating_limit_c", 15.0) or 15.0),
        persons=int(thermal.get("persons", 2) or 2),
        used_measured_eq=readings.used_measured_eq,
        used_measured_low=readings.used_measured_low,
        gain_kw_by_hour=gains,
        boost_k=float(storage["boost_k"]),
        store_max_c=feedback.get(KIND_STORE_MAX),
    )
    from settings.ehal_marker_resolve import marker_set_store_target

    return replace(
        plan,
        solar_source=solar_source,
        band_source=live_band.source,
        feedback=feedback,
        efficiency=resolve_live_efficiency(consumer, feedback),
        target_mapped=bool(marker_set_store_target(consumer)),
    )




def live_store_plan_for_matrix(
    source: dict,
    house_profile: dict,
    matrix: list,
) -> LiveStorePlan | None:
    """Live store plan over the matrix horizon; built once per Live cycle.

    Flex contexts, horizon targets and both MILP runs of a cycle share one plan
    (one set of readings + forecast) via ``optimizer.live_cycle_scope``.
    """
    thermal = source.get("thermal") or source
    if not heat_storage_enabled(thermal.get("heat_storage")) or not matrix:
        return None
    from optimizer.charging_context import matrix_slot_datetime
    from optimizer.live_cycle_scope import cycle_memo
    from optimizer.thermal_targets import thermal_horizon_hours_from_slots
    from optimizer.thermal_year_cache import fingerprint_json

    horizon_h = thermal_horizon_hours_from_slots(len(matrix))
    key = (
        "live_store_plan",
        fingerprint_json(source),
        horizon_h,
        matrix_slot_datetime(matrix, 0).isoformat(),
    )
    from optimizer.thermal_live_gains import matrix_hourly_kw

    baseload = matrix_hourly_kw(matrix, "expected_p_act", horizon_h)
    return cycle_memo(
        key, lambda: _build_live_store_plan(source, house_profile, horizon_h, baseload)
    )


def _read_live_outdoor_temp_c(house_doc: dict | None) -> float | None:
    """Live outdoor temperature (plant ``sens_temperature_outside``); None when unmapped/empty."""
    from integrations.ehal_live import read_optional_temp_c
    from settings.ehal_marker_resolve import marker_sens_temperature_outside

    return read_optional_temp_c(marker_sens_temperature_outside(house_doc=house_doc))


def _live_ambient_forecast(horizon_h: int, *, house_doc: dict | None = None) -> list[float]:
    """Outdoor forecast for the Live horizon; constant live reading if Open-Meteo fails.

    Without both there is no outdoor temperature and the plan fails loud (no invented value).
    """
    from data.outdoor_forecast import get_outdoor_forecast_or_live_reading

    ambient_forecast, _src = get_outdoor_forecast_or_live_reading(
        horizon=horizon_h,
        read_live_ambient_c=lambda: _read_live_outdoor_temp_c(house_doc),
    )
    return ambient_forecast


def _build_live_store_plan(
    source: dict,
    house_profile: dict,
    horizon_h: int,
    baseload_kw_by_hour: list[float],
) -> LiveStorePlan | None:
    return plan_live_store_for_thermal_consumer(
        source,
        house_profile=house_profile,
        ambient_forecast_c=_live_ambient_forecast(horizon_h),
        house_doc=None,
        baseload_kw_by_hour=baseload_kw_by_hour,
    )


def hourly_electric_to_slot_energy_kwh(
    matrix: list, electric_by_hour: list[float]
) -> list[float]:
    """WP electric kWh per matrix slot from hourly electric (wall-clock hour from horizon start)."""
    from optimizer.charging_context import matrix_slot_datetime
    from optimizer.slot_duration import energy_kwh_from_kw

    if not matrix:
        return []
    start = matrix_slot_datetime(matrix, 0)
    energies: list[float] = []
    for index in range(len(matrix)):
        hour_offset = int((matrix_slot_datetime(matrix, index) - start).total_seconds() // 3600)
        if 0 <= hour_offset < len(electric_by_hour):
            # electric_by_hour is kWh per hour == mean kW over that hour.
            energies.append(float(energy_kwh_from_kw([electric_by_hour[hour_offset]])))
        else:
            energies.append(0.0)
    return energies


TERMINAL_WINDOW_H = 24.0
"""The terminal level is the mean level of normal operation over the last day of the book, so it
does not depend on where in a charge cycle the simulation happens to end (design § 8.6 D2)."""


def _slot_hours(matrix: list, n_hours: int) -> list[int]:
    """Wall-clock hour of the plan for every matrix slot (offset from the start's full hour).

    Plan hour 0 is the full hour of the first slot, as for the baseload and gains
    (``matrix_hourly_kw``). The plan has ``floor(slots × Δt)`` hours
    (``thermal_horizon_hours_from_slots``), and the recorded forecasts of the regression cases have
    exactly as many. A matrix that starts inside an hour (Live at :15/:30/:45) and ends with a
    partial hour spans up to two wall-clock hours more; those slots use the last hour of the
    plan. This is the only hold, a slot further out fails loud.
    """
    from optimizer.charging_context import matrix_slot_datetime

    if n_hours < 1:
        raise ValueError("Speicherplan ohne Stunden.")
    start = matrix_slot_datetime(matrix, 0)
    hours: list[int] = []
    for index in range(len(matrix)):
        hour = int((matrix_slot_datetime(matrix, index) - start).total_seconds() // 3600)
        if n_hours <= hour <= n_hours + 1:
            hour = n_hours - 1  # partial first and last hour of the matrix
        if not 0 <= hour < n_hours:
            raise ValueError(
                f"Speicherplan reicht nur {n_hours} h, Matrix-Slot {index} liegt in Stunde {hour}."
            )
        hours.append(hour)
    return hours


def live_store_level_model(matrix: list, plan: LiveStorePlan, dt_h: float) -> StoreLevelModel:
    """Store level of the Live MILP (HeatControl P4): kWh above the band minimum.

    Capacity up to ``charge_max_c``; start from the measured ``T_eq``; drain = net draw plus the
    loss at the band minimum; collector surplus may be spilled; leak ``Δt · H / C``.
    """
    if plan.capacity_kwh_per_k <= 0 or plan.jaz <= 0:
        raise ValueError("Speicherplan ohne Kapazität oder Wirkungsgrad: kein Speicherstand möglich.")
    if dt_h <= 0:
        raise ValueError("dt_h must be > 0")
    c = float(plan.capacity_kwh_per_k)
    t_min = float(plan.band.min_c)
    draw = plan.hourly_draw_at_min_kw()
    hours = _slot_hours(matrix, len(draw))
    capacity = c * (plan.charge_max_c - t_min)
    drain = [draw[hour] * dt_h for hour in hours]
    return StoreLevelModel(
        capacity_kwh=capacity,
        start_kwh=c * (float(plan.start_temp_c) - t_min),
        efficiency=float(plan.jaz),
        drain_kwh=drain,
        leak_per_slot=dt_h * float(plan.heat_loss_kw_per_k) / c,
        leak_ref_kwh=0.0,
        spill_max_kwh=[max(0.0, -float(plan.draw_kw_by_hour[hour])) * dt_h for hour in hours],
        segments=_live_store_segments(plan, hours, capacity),
        charge_limit_kwh=_collector_charge_limits(plan, drain, dt_h, capacity),
    )


COLLECTOR_LOOKAHEAD_H = 24.0
"""The generator leaves the room above the setpoint free for the collector surplus forecast for
this time ahead (design § 4: no boost ahead of forecast collector heat)."""


def _live_store_segments(
    plan: LiveStorePlan, hours: list[int], capacity_kwh: float
) -> tuple[StoreSegment, ...]:
    """Sink segments of the band with their COP per slot (HeatControl P5); none with the JAZ."""
    if not plan.efficiency.by_temperature or capacity_kwh <= 0:
        return ()
    c = float(plan.capacity_kwh_per_k)
    edges = segment_edges_c(float(plan.band.min_c), float(plan.band.setpoint_c), plan.charge_max_c)
    held = plan.efficiency.source_temp_c
    source = [float(plan.ambient_c[hour]) if held is None else float(held) for hour in hours]
    cops = segment_cops(plan.efficiency, edges, source)
    return tuple(
        StoreSegment(capacity_kwh=c * (edges[index + 1] - edges[index]), cop=cops[index])
        for index in range(len(edges) - 1)
    )


def _collector_charge_limits(
    plan: LiveStorePlan, drain_kwh: list[float], dt_h: float, capacity_kwh: float
) -> list[float]:
    """Level per slot up to which the generator may charge: the capacity minus the room the
    collector surplus of the following ``COLLECTOR_LOOKAHEAD_H`` needs, never below the setpoint.

    The surplus is the collector heat the draw does not use up. From a slot on, the net heat
    into the store (``−drain``) adds up slot by slot; the largest sum is the room that must be
    free at the end of the slot so that the store takes it all. Collector heat that the house
    draws before or while it arrives needs no room: a charge that is used up before the
    collector heat comes stays allowed.

    Empty without a band above the setpoint, without forecast collector heat, or when no slot
    gets a limit below the capacity.
    """
    normal = float(plan.capacity_kwh_per_k) * (float(plan.band.setpoint_c) - float(plan.band.min_c))
    collector = plan.collector_kw_by_hour
    if capacity_kwh <= normal + 1e-9 or not any(kw > 1e-9 for kw in collector):
        return []
    if len(collector) < len(plan.draw_kw_by_hour):
        raise ValueError("Speicherplan: Kollektorprognose kürzer als die Wärmeentnahme.")
    window = int(round(COLLECTOR_LOOKAHEAD_H / dt_h))
    limits: list[float] = []
    for slot in range(len(drain_kwh)):
        surplus = room = 0.0
        for drain in drain_kwh[slot + 1 : slot + 1 + window]:
            surplus -= drain
            room = max(room, surplus)
        limits.append(max(normal, capacity_kwh - room))
    if not any(limit < capacity_kwh - 1e-9 for limit in limits):
        return []
    return limits


def live_store_terminal_kwh(matrix: list, plan: LiveStorePlan, last_slot: int, dt_h: float) -> float:
    """Mean level of normal operation over the last ``TERMINAL_WINDOW_H`` up to ``last_slot``."""
    if not plan.store_temp_c:
        raise ValueError("Speicherplan ohne Temperaturverlauf: kein Endstand möglich.")
    c = float(plan.capacity_kwh_per_k)
    t_min = float(plan.band.min_c)
    cap = c * (plan.charge_max_c - t_min)
    hours = _slot_hours(matrix, len(plan.store_temp_c))
    first = max(0, last_slot + 1 - int(round(TERMINAL_WINDOW_H / dt_h)))
    levels = [
        min(cap, max(0.0, c * (float(plan.store_temp_c[hours[slot]]) - t_min)))
        for slot in range(first, last_slot + 1)
    ]
    return sum(levels) / len(levels)


def live_house_plan_for_matrix(
    source: dict,
    house_profile: dict,
    matrix: list,
) -> LiveHousePlan | None:
    """Horizon plan without heat storage; None when a store is configured. Once per cycle."""
    thermal = source.get("thermal") or source
    if heat_storage_enabled(thermal.get("heat_storage")) or not matrix:
        return None
    from optimizer.charging_context import matrix_slot_datetime
    from optimizer.live_cycle_scope import cycle_memo
    from optimizer.thermal_targets import thermal_horizon_hours_from_slots
    from optimizer.thermal_year_cache import fingerprint_json

    horizon_h = thermal_horizon_hours_from_slots(len(matrix))
    key = (
        "live_house_plan",
        fingerprint_json(source),
        horizon_h,
        matrix_slot_datetime(matrix, 0).isoformat(),
    )
    return cycle_memo(
        key,
        lambda: _build_live_house_plan(source, house_profile, matrix, horizon_h),
    )


def _build_live_house_plan(
    source: dict, house_profile: dict, matrix: list, horizon_h: int
) -> LiveHousePlan:
    from optimizer.charging_context import matrix_slot_datetime
    from optimizer.thermal_live_gains import live_gain_kw_by_hour, matrix_hourly_kw

    start = matrix_slot_datetime(matrix, 0)
    thermal = source.get("thermal") or source
    gains: list[float] | None = None
    source_label = SOLAR_SOURCE_NONE
    if float(thermal.get("living_area_m2", 0.0) or 0.0) > 0.0:
        gains, source_label = live_gain_kw_by_hour(
            source,
            house_profile,
            start=start,
            horizon=horizon_h,
            baseload_kw_by_hour=matrix_hourly_kw(matrix, "expected_p_act", horizon_h),
        )
    return plan_live_house_horizon(
        source,
        house_profile=house_profile,
        ambient_forecast_c=_live_ambient_forecast(horizon_h),
        gain_kw_by_hour=gains,
        gain_source=source_label,
    )






def map_forced_hours_to_slot_indices(
    matrix: list,
    forced_hour_flags: list[bool],
    *,
    eligible_indices: list[int] | None = None,
) -> list[int]:
    """Map hour flags onto matrix QH indices (wall-clock hour match from horizon start)."""
    from optimizer.charging_context import matrix_slot_datetime

    if not matrix or not forced_hour_flags:
        return []
    eligible = set(eligible_indices) if eligible_indices is not None else None
    start = matrix_slot_datetime(matrix, 0)
    forced_slots: list[int] = []
    for index, _row in enumerate(matrix):
        if eligible is not None and index not in eligible:
            continue
        slot_dt = matrix_slot_datetime(matrix, index)
        hour_offset = int((slot_dt - start).total_seconds() // 3600)
        if hour_offset < 0 or hour_offset >= len(forced_hour_flags):
            continue
        if forced_hour_flags[hour_offset]:
            forced_slots.append(index)
    return forced_slots


def build_heat_storage_observability(
    consumer: dict,
    *,
    house_profile: dict,
    ambient_forecast_c: list[float],
    house_doc: dict | None = None,
    solar_forecast_kw: list[float] | None = None,
) -> dict[str, Any] | None:
    """Snapshot for optimization_history: T_eq/T_low + Q_meas/Q_sim."""
    plan = plan_live_store_for_thermal_consumer(
        consumer,
        house_profile=house_profile,
        ambient_forecast_c=ambient_forecast_c,
        solar_forecast_kw=solar_forecast_kw,
        house_doc=house_doc,
    )
    if plan is None:
        return None
    thermal = consumer.get("thermal") or consumer
    storage = normalize_heat_storage(thermal.get("heat_storage"))
    if storage is None:
        return None
    capacity = capacity_kwh_per_k_from_volume(storage["volume_liters"])
    q_meas = heat_content_kwh(plan.start_temp_c, capacity)
    q_sim = (
        float(plan.q_sim_kwh[0])
        if plan.q_sim_kwh
        else heat_content_kwh(plan.start_temp_c, capacity)
    )
    return {
        "consumer_id": consumer.get("id"),
        "kind": "heat_storage",
        "readings_c": {
            "temp_eq": plan.start_temp_c,
            "temp_low": plan.temp_low_c,
            "setpoint": plan.band.setpoint_c,
            "tolerance": plan.band.tolerance_c,
            "band_min": plan.band.min_c,
            "band_max": plan.band.max_c,
            # HeatControl P2: an Earnie charge ends at setpoint + boost.
            "boost": plan.boost_k,
            "charge_max": plan.charge_max_c,
        },
        # "backend": Live planned with the band the backend reports, not the configured one.
        "band_source": plan.band_source,
        "feedback": dict(plan.feedback),
        # HeatControl P5: JAZ or COP curve, and where the source temperature comes from.
        "efficiency": efficiency_observability(plan.efficiency, plan.jaz),
        "heat_content_kwh": {
            "q_meas": round(q_meas, 3),
            "q_sim": round(q_sim, 3),
        },
        "model": {
            "capacity_kwh_per_k": round(capacity, 4),
            "volume_liters": float(storage["volume_liters"]),
            "heat_loss_kw_per_k": float(storage["heat_loss_kw_per_k"]),
        },
        "used_measured_eq": plan.used_measured_eq,
        # Start of the store plan: the measured T_eq, or the setpoint when T_eq has no value.
        "eq_source": EQ_SOURCE_MEASURED if plan.used_measured_eq else EQ_SOURCE_SETPOINT_NO_VALUE,
        "used_measured_low": plan.used_measured_low,
        "collector_solar_source": plan.solar_source,
        "horizon_q_sim_kwh": [round(v, 3) for v in plan.q_sim_kwh],
    }


def collect_heat_storage_observability(
    consumers: list[dict],
    *,
    house_profile: dict,
    horizon: int = 24,
    house_doc: dict | None = None,
) -> list[dict[str, Any]]:
    """Observability for thermal_annual consumers with active heat_storage."""
    results: list[dict[str, Any]] = []
    ambient_forecast: list[float] | None = None
    for consumer in consumers:
        if not isinstance(consumer, dict):
            continue
        if consumer.get("type") != "thermal_annual":
            continue
        thermal = consumer.get("thermal") or consumer
        if not heat_storage_enabled(thermal.get("heat_storage")):
            continue
        cid = consumer.get("id") or "?"
        try:
            # Only with a store; a missing outdoor temperature is this item's error.
            if ambient_forecast is None:
                ambient_forecast = _live_ambient_forecast(
                    max(1, int(horizon)), house_doc=house_doc
                )
            item = build_heat_storage_observability(
                consumer,
                house_profile=house_profile,
                ambient_forecast_c=ambient_forecast,
                house_doc=house_doc,
            )
            if item is not None:
                results.append(item)
        except Exception as exc:
            results.append(
                {
                    "consumer_id": cid,
                    "kind": "heat_storage",
                    "error": str(exc),
                }
            )
    return results

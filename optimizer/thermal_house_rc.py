"""House RC primitives: capacity, envelope H calibration, hour step (split from thermal_house)."""
from __future__ import annotations

from dataclasses import dataclass, field

from house_config.profile_schema_defaults import house_thermal_default

BUILDING_MASS_C_WH_PER_M2K: dict[str, float] = {
    "leicht": 50.0,
    "mittel": 90.0,
    "schwer": 130.0,
}

DEFAULT_BUILDING_MASS = str(house_thermal_default("building_mass"))
DEFAULT_HOUSE_TOLERANCE_C = float(house_thermal_default("house_tolerance_c"))

# SUSI P2 [assumption]: gains above target + this margin are vented (windows, shading); the
# house never cools below the outdoor air that way. Without it a sunny house would overheat
# without bound and carry the heat into the next heating period.
VENT_MARGIN_K = 3.0
# H calibration with gains (SUSI P2): the ideal-heater space heat (no power limit, so H stays a
# building property) matches HWB × BGF within this share; the Grundlast ↔ heating-electric
# fixed point within CALIBRATION_ENERGY_TOL_KWH.
CALIBRATION_REL_TOL = 0.005
CALIBRATION_ENERGY_TOL_KWH = 1.0
CALIBRATION_MAX_ITER = 25


def normalize_building_mass(raw: object | None) -> str:
    """Return leicht|mittel|schwer; unknown → mittel."""
    key = str(raw or DEFAULT_BUILDING_MASS).strip().lower()
    if key not in BUILDING_MASS_C_WH_PER_M2K:
        return DEFAULT_BUILDING_MASS
    return key


def house_capacity_kwh_per_k(living_area_m2: float, building_mass: str | None) -> float:
    """Effective house heat capacity C [kWh/K] from Wohnfläche × Bauweise."""
    area = max(0.0, float(living_area_m2))
    mass = normalize_building_mass(building_mass)
    return area * BUILDING_MASS_C_WH_PER_M2K[mass] / 1000.0


def calibrate_house_heat_loss_kw_per_k(
    annual_heat_kwh: float,
    ambient_c: list[float],
    *,
    target_temp_c: float,
    heating_limit_c: float,
) -> float:
    """Envelope H [kW/K] so annual heat ≈ HWB·area under HDD-like ambient."""
    denom = 0.0
    target = float(target_temp_c)
    limit = float(heating_limit_c)
    for ambient in ambient_c:
        t_out = float(ambient)
        if t_out < limit:
            denom += max(0.0, target - t_out)
    if denom <= 1e-9:
        return 0.0
    return max(0.0, float(annual_heat_kwh) / denom)


def resolve_house_heat_loss_kw_per_k(
    *,
    override_kw_per_k: float | None,
    annual_heat_kwh: float,
    ambient_c: list[float],
    target_temp_c: float,
    heating_limit_c: float,
) -> float:
    if override_kw_per_k is not None and float(override_kw_per_k) > 0.0:
        return float(override_kw_per_k)
    return calibrate_house_heat_loss_kw_per_k(
        annual_heat_kwh,
        ambient_c,
        target_temp_c=target_temp_c,
        heating_limit_c=heating_limit_c,
    )


def step_house_hour(
    temp_c: float,
    ambient_c: float,
    *,
    heat_in_kw: float,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    gain_kw: float = 0.0,
) -> float:
    """One Euler hour for indoor air / shallow mass (heating plus solar / internal gains)."""
    if capacity_kwh_per_k <= 0:
        raise ValueError("capacity_kwh_per_k muss > 0 sein")
    loss = float(heat_loss_kw_per_k) * (float(temp_c) - float(ambient_c))
    net = float(heat_in_kw) + float(gain_kw) - loss
    return float(temp_c) + net / capacity_kwh_per_k


def vent_house_temp(temp_c: float, ambient_c: float, target_temp_c: float) -> float:
    """Cap the indoor temperature at target + ``VENT_MARGIN_K`` (not below the outdoor air)."""
    cap = max(float(target_temp_c) + VENT_MARGIN_K, float(ambient_c))
    return min(float(temp_c), cap)


def cool_house_temp(
    temp_c: float,
    *,
    setpoint_c: float,
    cooling_power_kw: float,
    capacity_kwh_per_k: float,
) -> tuple[float, float]:
    """Air conditioning for one hour: (indoor temp, cold kWh) after cooling down to the setpoint.

    The device removes the heat above ``setpoint_c`` up to its capacity (ideal thermostat; an
    undersized device leaves the house warmer).
    """
    excess = (float(temp_c) - float(setpoint_c)) * float(capacity_kwh_per_k)
    if excess <= 0.0:
        return float(temp_c), 0.0
    cold = min(excess, float(cooling_power_kw))
    return float(temp_c) - cold / float(capacity_kwh_per_k), cold


def house_requests_heat(
    temp_c: float,
    ambient_c: float,
    *,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    band_min_c: float,
    gain_kw: float = 0.0,
) -> bool:
    """True when projected next temp without heating (gains included) would fall below band min."""
    next_off = step_house_hour(
        temp_c,
        ambient_c,
        heat_in_kw=0.0,
        capacity_kwh_per_k=capacity_kwh_per_k,
        heat_loss_kw_per_k=heat_loss_kw_per_k,
        gain_kw=gain_kw,
    )
    return next_off < band_min_c - 1e-9


@dataclass(frozen=True)
class HouseYearResult:
    """Daily heat-source input energy plus hourly house (and optional store) temperatures.

    Input energy = delivered heat / efficiency; it is electric for a heat pump or
    ``electric_direct`` and fuel (final energy, kWh) for every other heat source.
    ``house_heat_loss_kw_per_k`` is the envelope H the run used (calibrated with gains, or the
    override); ``annual_space_heat_kwh`` the space heat delivered into the house (no warm water).
    With air conditioning, ``hourly_cooling_electric_kw`` is its electricity per hour (never in
    ``daily_electric_kwh``, which stays the heat source's input) and ``annual_cooling_kwh`` the
    cold it removed. Heating not booked (switch „Heizung betrachten“ off, cooling-only run):
    the heat source still holds the house temperature, but its input energy is 0.
    """

    daily_electric_kwh: list[float]
    hourly_house_temp_c: list[float]
    hourly_store_temp_c: list[float]
    daily_fuel_kwh: list[float] = field(default_factory=list)
    house_heat_loss_kw_per_k: float | None = None
    annual_space_heat_kwh: float = 0.0
    hourly_cooling_electric_kw: list[float] = field(default_factory=list)
    annual_cooling_kwh: float = 0.0


def ideal_space_heat_kwh(
    house_h: float,
    ambient_c: list[float],
    gain_kw: list[float],
    *,
    capacity_kwh_per_k: float,
    target_temp_c: float,
) -> float:
    """Annual space heat of an ideal heater holding ``target_temp_c`` (no power limit).

    Gains above the need warm the mass (vented above target + ``VENT_MARGIN_K``) and are used
    in later hours; this is the building-only demand H is calibrated on.
    """
    temp = float(target_temp_c)
    target = float(target_temp_c)
    heat = 0.0
    c = float(capacity_kwh_per_k)
    for amb, gain in zip(ambient_c, gain_kw):
        free = temp + (gain - house_h * (temp - amb)) / c
        if free < target:
            heat += (target - free) * c
            temp = target
        else:
            temp = vent_house_temp(free, amb, target)
    return heat


def calibrate_house_heat_loss_with_gains(
    annual_heat_kwh: float,
    ambient_c: list[float],
    gain_kw: list[float],
    *,
    capacity_kwh_per_k: float,
    target_temp_c: float,
    start_h: float,
) -> float:
    """H [kW/K] whose ideal-heater space heat (after gains) equals ``annual_heat_kwh``.

    The heat grows monotonically with H: bracket from ``start_h`` (HDD estimate), then
    bisection with a secant step. Fails loud when no H reaches the target.
    """
    target = float(annual_heat_kwh)
    if target <= 0.0:
        return 0.0

    def heat_at(h: float) -> float:
        return ideal_space_heat_kwh(
            h,
            ambient_c,
            gain_kw,
            capacity_kwh_per_k=capacity_kwh_per_k,
            target_temp_c=target_temp_c,
        )

    lo_h, hi_h = 0.0, max(float(start_h), 1e-3)
    lo_q, hi_q = heat_at(lo_h), heat_at(hi_h)
    expansions = 0
    while hi_q < target:
        lo_h, lo_q = hi_h, hi_q
        hi_h *= 2.0
        hi_q = heat_at(hi_h)
        expansions += 1
        if expansions > 40:
            raise RuntimeError(
                f"Hausmodell: kein Verlustkoeffizient H erreicht {target:.0f} kWh Heizwärme "
                "(Klima zu warm für den HWB?)."
            )
    for _ in range(60):
        if abs(hi_q - target) <= CALIBRATION_REL_TOL * target * 0.2:
            return hi_h
        if abs(lo_q - target) <= CALIBRATION_REL_TOL * target * 0.2 and lo_h > 0.0:
            return lo_h
        span = hi_q - lo_q
        guess = lo_h + (target - lo_q) * (hi_h - lo_h) / span if span > 1e-9 else 0.0
        mid = 0.5 * (lo_h + hi_h)
        # Secant inside the inner 80 % of the bracket, else bisection.
        width = hi_h - lo_h
        h = guess if lo_h + 0.1 * width < guess < hi_h - 0.1 * width else mid
        q = heat_at(h)
        if q < target:
            lo_h, lo_q = h, q
        else:
            hi_h, hi_q = h, q
    return 0.5 * (lo_h + hi_h)

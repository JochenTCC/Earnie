"""Thermal PWM / on-off hourly profiles (split from heating_need)."""
from __future__ import annotations

import math


_THERMAL_PWM_MIN_ON_H = 1


_THERMAL_PWM_MAX_ON_H = 4


def _pwm_pulse_durations(
    on_hours_total: float,
    *,
    min_on_h: int = _THERMAL_PWM_MIN_ON_H,
    max_on_h: int = _THERMAL_PWM_MAX_ON_H,
) -> list[float]:
    """Teilt benötigte Laufzeit in Pulse à 1–4 h (letzter Puls ggf. kürzer)."""
    if on_hours_total <= 0.0:
        return []
    pulses: list[float] = []
    remaining = on_hours_total
    while remaining > 1e-6:
        if remaining <= max_on_h:
            pulses.append(remaining)
            break
        pulses.append(float(max_on_h))
        remaining -= max_on_h
    return pulses


def _pwm_pulse_start_hours(
    day_index: int,
    pulse_lengths: list[int],
) -> list[int]:
    """Startstunden für Pulse — gleichmäßig über den Tag verteilt."""
    pulse_count = len(pulse_lengths)
    if pulse_count == 0:
        return []
    total_on = sum(pulse_lengths)
    free_slots = max(0, 24 - total_on)
    if pulse_count == 1:
        max_start = max(0, 24 - pulse_lengths[0])
        return [day_index % (max_start + 1)]
    gap = free_slots // (pulse_count + 1)
    gap = max(1, gap)
    offset = day_index % gap
    starts: list[int] = []
    cursor = gap + offset
    for length in pulse_lengths:
        starts.append(min(cursor, 24 - length))
        cursor += length + gap
    return starts


def _apply_pwm_pulse(
    day_hours: list[float],
    start_hour: int,
    duration_h: float,
    nominal: float,
) -> None:
    remaining_kwh = duration_h * nominal
    hour = start_hour
    while remaining_kwh > 1e-6 and hour < 24:
        slot_kw = min(nominal, remaining_kwh)
        day_hours[hour] = round(slot_kw, 6)
        remaining_kwh -= slot_kw
        hour += 1


def _thermal_pwm_day_hourly(
    day_index: int,
    day_kwh: float,
    nominal: float,
    *,
    min_on_h: int = _THERMAL_PWM_MIN_ON_H,
    max_on_h: int = _THERMAL_PWM_MAX_ON_H,
) -> list[float]:
    """Tägliches PWM-Profil: volle Nennleistung oder 0 kW, Pulse 1–4 h."""
    day_hours = [0.0] * 24
    if day_kwh <= 0.0 or nominal <= 0.0:
        return day_hours
    pulse_durations = _pwm_pulse_durations(
        day_kwh / nominal,
        min_on_h=min_on_h,
        max_on_h=max_on_h,
    )
    pulse_lengths = [
        max(1, int(math.ceil(duration)))
        if duration >= min_on_h
        else 1
        for duration in pulse_durations
    ]
    start_hours = _pwm_pulse_start_hours(day_index, pulse_lengths)
    for start, duration in zip(start_hours, pulse_durations):
        _apply_pwm_pulse(day_hours, start, duration, nominal)
    return day_hours


def thermal_daily_pwm_hourly_profile(
    daily_kwh: list[float],
    *,
    nominal_power_kw: float,
    hours_per_year: int = 8760,
    min_on_h: int = _THERMAL_PWM_MIN_ON_H,
    max_on_h: int = _THERMAL_PWM_MAX_ON_H,
) -> list[float]:
    """
    Thermisches Profil: tägliches PWM mit 1–4 h Einschaltzyklen bei Nennleistung.
    Tages-kWh werden auf mehrere Pulse pro Tag verteilt (nicht wöchentlich gebündelt).
    """
    if not daily_kwh:
        raise ValueError("daily_kwh darf nicht leer sein.")
    nominal = float(nominal_power_kw)
    if nominal <= 0.0:
        hours_per_day = 24
        flat_kw = sum(daily_kwh) / max(1, len(daily_kwh) * hours_per_day)
        return [round(flat_kw, 6)] * hours_per_year
    profile: list[float] = []
    for day_index, day_kwh in enumerate(daily_kwh):
        profile.extend(
            _thermal_pwm_day_hourly(
                day_index,
                float(day_kwh),
                nominal,
                min_on_h=min_on_h,
                max_on_h=max_on_h,
            )
        )
    while len(profile) < hours_per_year:
        profile.append(0.0)
    return profile[:hours_per_year]


def thermal_on_off_hourly_profile(
    weekly_kwh: list[float],
    *,
    nominal_power_kw: float,
    hours_per_year: int = 8760,
) -> list[float]:
    """
    Thermisches Profil: volle Nennleistung oder 0 kW (kein flacher Wochenmittelwert).
    Wochen-kWh werden in volle und ggf. eine partielle Stunde aufgeteilt.
    """
    if len(weekly_kwh) != 52:
        raise ValueError("weekly_kwh muss 52 Einträge haben.")
    nominal = float(nominal_power_kw)
    if nominal <= 0.0:
        return hourly_profile_for_year(weekly_kwh, hours_per_year=hours_per_year)
    hours_per_week = hours_per_year // 52
    profile: list[float] = []
    for week_kwh in weekly_kwh:
        remaining = float(week_kwh)
        week_hours: list[float] = []
        for _ in range(hours_per_week):
            if remaining >= nominal:
                week_hours.append(round(nominal, 6))
                remaining -= nominal
            elif remaining > 0.0:
                week_hours.append(round(remaining, 6))
                remaining = 0.0
            else:
                week_hours.append(0.0)
        profile.extend(week_hours)
    while len(profile) < hours_per_year:
        profile.append(0.0)
    return profile[:hours_per_year]


def hourly_profile_for_year(
    weekly_kwh: list[float],
    *,
    hours_per_year: int = 8760,
) -> list[float]:
    """Verteilt Wochenwerte gleichmäßig auf Stunden (8760)."""
    if len(weekly_kwh) != 52:
        raise ValueError("weekly_kwh muss 52 Einträge haben.")
    hours_per_week = hours_per_year // 52
    profile: list[float] = []
    for week_kwh in weekly_kwh:
        kw = week_kwh / max(1, hours_per_week)
        profile.extend([round(kw, 6)] * hours_per_week)
    while len(profile) < hours_per_year:
        profile.append(profile[-1] if profile else 0.0)
    return profile[:hours_per_year]

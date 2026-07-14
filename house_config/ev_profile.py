"""E-Auto-Planungsprofile für Backtesting (ohne Loxone)."""
from __future__ import annotations

from datetime import date, timedelta

from optimizer.charging_context import hour_in_charging_window
from settings.ev_power import merge_ev_power_conversion_fields
from settings.flexible_consumers import normalize_day_schedule, target_kwh_from_rest_soc

_REFERENCE_YEAR_DAYS = 365
_REFERENCE_YEAR_START = date(2023, 1, 1)


def normalize_ev_charging_schedule(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("ev-Verbraucher erfordert charging_schedule.")
    efficiency_raw = raw.get("charging_efficiency")
    if efficiency_raw is None:
        efficiency = 0.95
    else:
        efficiency = float(efficiency_raw)
        if efficiency <= 0.0 or efficiency > 1.0:
            raise ValueError(
                "charging_schedule.charging_efficiency muss zwischen 0 (exklusiv) und 1 liegen."
            )
    weekday = normalize_day_schedule(raw.get("weekday"))
    weekend = normalize_day_schedule(raw.get("weekend"))
    if not weekday and not weekend:
        raise ValueError("charging_schedule erfordert weekday und/oder weekend.")
    return merge_ev_power_conversion_fields(
        {
            "target_soc_percent": float(raw.get("target_soc_percent", 100.0) or 100.0),
            "charging_efficiency": efficiency,
            "forecast_when_absent": bool(raw.get("forecast_when_absent", True)),
            "weekday": weekday,
            "weekend": weekend,
        },
        raw,
    )


def _day_schedule(consumer: dict, day: date) -> dict:
    sched = consumer.get("charging_schedule") or {}
    key = "weekend" if day.weekday() >= 5 else "weekday"
    return dict(sched.get(key) or {})


def ev_daily_kwh(consumer: dict, day: date) -> float:
    """Tägliche Ladeenergie (Netz-kWh) aus daily_rest_soc und Akkuparametern."""
    day_sched = _day_schedule(consumer, day)
    rest_soc = day_sched.get("daily_rest_soc")
    if rest_soc is None:
        return 0.0
    capacity = float(consumer.get("battery_capacity_kwh", 0.0) or 0.0)
    pseudo = {
        "charging_schedule": {
            **(consumer.get("charging_schedule") or {}),
            "enabled": True,
        }
    }
    return target_kwh_from_rest_soc(pseudo, float(rest_soc), capacity_kwh=capacity) or 0.0


def estimate_ev_annual_kwh(consumer: dict) -> float:
    """Jahresenergie als Summe der täglichen Ladeziele über ein Referenzjahr."""
    total = 0.0
    for offset in range(_REFERENCE_YEAR_DAYS):
        day = _REFERENCE_YEAR_START + timedelta(days=offset)
        total += ev_daily_kwh(consumer, day)
    return round(total, 3)


def _charging_hours_from_arrival(from_h: int, ready_h: int) -> list[int]:
    """Ladestunden ab car_available_from_hour (Ankunft) vorwärts bis vor ready_by_hour."""
    from_h %= 24
    ready_h %= 24
    ordered: list[int] = []
    hour = from_h
    while True:
        if hour_in_charging_window(hour, from_h, ready_h):
            ordered.append(hour)
        if hour == (ready_h - 1) % 24:
            break
        hour = (hour + 1) % 24
    return ordered


def _distribute_daily_kwh(daily_kwh: float, hours: list[int], nominal_kw: float) -> dict[int, float]:
    """Baseline: PMax ab Ankunftsstunde vorwärts bis das Tagesziel erreicht ist."""
    if not hours or daily_kwh <= 0:
        return {hour: 0.0 for hour in range(24)}
    result = {hour: 0.0 for hour in range(24)}
    remaining = daily_kwh
    for hour in hours:
        if remaining <= 0:
            break
        kw = min(nominal_kw, remaining)
        result[hour] = kw
        remaining -= kw
    return result


def ev_hourly_kw_from_schedule(
    *,
    from_h: int,
    ready_h: int,
    daily_kwh: float,
    nominal_kw: float,
) -> dict[int, float]:
    """Stündliches kW-Dict aus Ladezeitfenster und Tagesziel (Baseline / cons_data)."""
    hours = _charging_hours_from_arrival(from_h, ready_h)
    return _distribute_daily_kwh(daily_kwh, hours, nominal_kw)


def ev_hourly_kw_for_day(consumer: dict, day: date) -> list[float]:
    """Stündliches kW-Profil für einen Tag — Last nur im Ladezeitfenster."""
    daily_kwh = ev_daily_kwh(consumer, day)
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    day_sched = _day_schedule(consumer, day)
    from_h = int(day_sched.get("car_available_from_hour", 19)) % 24
    ready_h = int(day_sched.get("ready_by_hour", 7)) % 24
    by_hour = ev_hourly_kw_from_schedule(
        from_h=from_h,
        ready_h=ready_h,
        daily_kwh=daily_kwh,
        nominal_kw=nominal,
    )
    return [by_hour[hour] for hour in range(24)]

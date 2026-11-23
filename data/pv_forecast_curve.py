"""PV forecast helpers: forecast.solar curve mapping, rate-limit header parsing, coverage check.

Split from ``data.pv_forecast`` (KPI refactor); that module re-exports these names. Pure helpers:
no module state, no network calls (those stay in ``data.pv_forecast``, where tests patch them).
"""
from datetime import datetime
from typing import Optional

import requests

import config


def _as_naive_local(value: datetime) -> datetime:
    """Normalize aware API timestamps for comparison with ``datetime.now()``."""
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _parse_retry_at(response: requests.Response) -> Optional[datetime]:
    """Liest Retry-At aus Header oder JSON-Body einer 429-Antwort."""
    header_value = response.headers.get("X-Ratelimit-Retry-At")
    if header_value:
        try:
            return _as_naive_local(datetime.fromisoformat(header_value.strip()))
        except ValueError:
            pass

    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    message = payload.get("message") or {}
    ratelimit = message.get("ratelimit") or {}
    retry_at = ratelimit.get("retry-at")
    if not retry_at:
        return None
    try:
        return _as_naive_local(datetime.fromisoformat(str(retry_at).strip()))
    except ValueError:
        return None


def _safe_body(response) -> object:
    try:
        return response.json()
    except ValueError:
        return getattr(response, "text", None)


def _forecast_solar_curve(hourly_watts: dict) -> list[tuple[datetime, float]]:
    """forecast.solar ``watts`` as (local time, W) points, sorted by time."""
    return sorted(
        (datetime.strptime(key, "%Y-%m-%d %H:%M:%S"), float(watts))
        for key, watts in hourly_watts.items()
    )


def _curve_mean_kw(
    curve: list[tuple[datetime, float]], start: datetime, end: datetime
) -> float:
    """Mean kW over [start, end) of the piecewise linear curve (0 outside its points)."""
    area_wh = 0.0
    for (t0, w0), (t1, w1) in zip(curve, curve[1:]):
        lo, hi = max(t0, start), min(t1, end)
        if hi <= lo:
            continue
        span_s = (t1 - t0).total_seconds()
        w_lo = w0 + (w1 - w0) * (lo - t0).total_seconds() / span_s
        w_hi = w0 + (w1 - w0) * (hi - t0).total_seconds() / span_s
        area_wh += (w_lo + w_hi) / 2.0 * (hi - lo).total_seconds() / 3600.0
    return area_wh / ((end - start).total_seconds() / 3600.0) / 1000.0


def _map_hourly_data_to_vector(hourly_watts: dict, target_hours: list) -> tuple[list, bool]:
    """Mean kW per target slot from forecast.solar ``watts``.

    ``watts`` is the power **at** each timestamp (hours plus sunrise / sunset points);
    forecast.solar's ``watt_hours_period`` is the trapezoid of these points. A slot gets
    the trapezoid mean over its own interval, so hourly slots match the period energy
    and QH slots follow the curve. Slots outside the points (night, beyond the data) get 0.
    """
    from optimizer.slot_duration import slot_step

    curve = _forecast_solar_curve(hourly_watts)
    first, last = curve[0][0], curve[-1][0]
    starts = [dt.replace(tzinfo=None) for dt in target_hours]
    pv_vector = [0.0] * len(starts)
    success_count = 0

    for idx, start in enumerate(starts):
        if idx + 1 < len(starts):
            end = starts[idx + 1]
        elif idx > 0:
            end = start + (start - starts[idx - 1])
        else:
            end = start + slot_step()
        if end <= first or start >= last:
            continue
        pv_vector[idx] = round(_curve_mean_kw(curve, start, end), 3)
        success_count += 1

    if success_count > 0:
        print(
            f"[OK] PV-Ertragsprognose erfolgreich bereitgestellt "
            f"({success_count}/{len(target_hours)} Slots gemappt. Max: {max(pv_vector)} kW)."
        )
        return pv_vector, True

    return pv_vector, False


def _uncovered_daylight_days(
    hourly_watts: dict,
    target_hours: list,
    *,
    lat: float,
    lon: float,
) -> list:
    """Days with daylight slots in *target_hours* that the forecast.solar data has no point on.

    Such slots would map to 0 kW like the night; the system then takes Open-Meteo instead.
    """
    from data.planning_window import official_sun_times

    tz_name = config.get_planning_timezone()
    covered = {stamp.date() for stamp, _ in _forecast_solar_curve(hourly_watts)}
    uncovered = []
    for day in sorted({dt.date() for dt in target_hours}):
        if day in covered:
            continue
        sunrise, sunset = official_sun_times(day, lat, lon, tz_name)
        sunrise, sunset = sunrise.replace(tzinfo=None), sunset.replace(tzinfo=None)
        if any(
            dt.date() == day and sunrise < _as_planning_naive(dt, tz_name) < sunset
            for dt in target_hours
        ):
            uncovered.append(day)
    return uncovered


def _as_planning_naive(value: datetime, tz_name: str) -> datetime:
    if value.tzinfo is None:
        return value
    from zoneinfo import ZoneInfo

    return value.astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)

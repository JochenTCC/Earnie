"""Open-Meteo archive and forecast (https://open-meteo.com/, data CC BY 4.0).

Every request asks for UTC timestamps: with a zone name Open-Meteo applies ONE fixed UTC offset to
the whole response (the offset valid on the request day), so hours on the other side of a clock
change would be 1 h off. Converting to local time is the caller's job.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from opendata.http import Session

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS = 16
# The archive fills the most recent days from forecast models and replaces them with
# reanalysis data (ERA5) about five days later.
ARCHIVE_SETTLE_DAYS = 7


def _hourly(variables: str | Sequence[str]) -> str:
    return variables if isinstance(variables, str) else ",".join(variables)


def utc_forecast_params(forecast_days: int) -> dict[str, Any]:
    """Forecast window in UTC: one past day and one extra forecast day.

    The first local hours of a day belong to the previous UTC day and the last ones may fall
    behind the UTC-day count.
    """
    return {
        "timezone": "UTC",
        "past_days": 1,
        "forecast_days": min(MAX_FORECAST_DAYS, forecast_days + 1),
    }


def archive(
    session: Session,
    *,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    hourly: str | Sequence[str],
    extra_params: dict[str, Any] | None = None,
    cached: bool = False,
) -> dict[str, Any]:
    """Archive payload for the UTC days ``start_date`` … ``end_date`` (both inclusive).

    ``cached``: serve settled days from the session's disk cache.
    """
    params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": _hourly(hourly),
        "timezone": "UTC",
        **(extra_params or {}),
    }
    if cached:
        return session.get_json_cached(
            ARCHIVE_URL, params, last_day=end_date, settle_days=ARCHIVE_SETTLE_DAYS
        )
    return session.get_json(ARCHIVE_URL, params)


def forecast(
    session: Session,
    *,
    latitude: float | Sequence[float],
    longitude: float | Sequence[float],
    forecast_days: int,
    hourly: str | Sequence[str],
    extra_params: dict[str, Any] | None = None,
) -> Any:
    """Forecast payload; ``forecast_days`` counts from the real today (see :func:`utc_forecast_params`).

    With sequences of coordinates Open-Meteo answers one list entry per location.
    """
    params: dict[str, Any] = {
        "latitude": latitude if isinstance(latitude, (int, float)) else ",".join(str(v) for v in latitude),
        "longitude": longitude if isinstance(longitude, (int, float)) else ",".join(str(v) for v in longitude),
        "hourly": _hourly(hourly),
        **utc_forecast_params(forecast_days),
        **(extra_params or {}),
    }
    return session.get_json(FORECAST_URL, params)

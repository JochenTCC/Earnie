"""Offline-Mock für Open-Meteo-Klimabundle in Tests."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd

from data.open_meteo_solar_archive import HOURLY_TEMP_VAR, HOURLY_VAR


def _hourly_index(start: date, end: date) -> pd.DatetimeIndex:
    return pd.date_range(
        datetime.combine(start, time(0)),
        datetime.combine(end, time(23)),
        freq="h",
    )


def _fake_fetch_hourly_archive_chunk(
    *,
    lat: float,
    lon: float,
    timezone: str,
    start: date,
    end: date,
    hourly_vars: str,
    extra_params: dict | None = None,
) -> dict[str, pd.Series]:
    del lat, lon, timezone, extra_params
    chunk_end = end - timedelta(days=1)
    if chunk_end < start:
        chunk_end = start
    index = _hourly_index(start, chunk_end)
    result: dict[str, pd.Series] = {}
    for var_name in [name.strip() for name in hourly_vars.split(",")]:
        if var_name == HOURLY_TEMP_VAR:
            result[var_name] = pd.Series(-2.0, index=index, dtype=float)
        elif var_name == HOURLY_VAR:
            wm2 = pd.Series(200.0, index=index, dtype=float)
            wm2.loc[index.month.isin([6, 7, 8])] = 500.0
            result[var_name] = wm2
        else:
            result[var_name] = pd.Series(0.0, index=index, dtype=float)
    return result


def install_open_meteo_climate_mock(monkeypatch) -> None:
    from data import open_meteo_solar_archive as archive

    monkeypatch.setattr(
        archive,
        "_fetch_hourly_archive_chunk",
        _fake_fetch_hourly_archive_chunk,
    )

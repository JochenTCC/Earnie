# tests/test_pv_forecast_multi.py
"""Multi-PV forecast.solar aggregation."""
from __future__ import annotations

from datetime import datetime

import data.pv_forecast as pv_forecast


def test_get_hourly_pv_forecast_sums_systems(monkeypatch):
    hours = [datetime(2024, 7, 13, 12, 0), datetime(2024, 7, 13, 13, 0)]

    monkeypatch.setattr(
        "data.pv_forecast.config.get",
        lambda name, default=None, cast=None: {
            "LATITUDE": 48.0,
            "LONGITUDE": 10.0,
            "PV_KWP": 0.0,
            "PV_TILT": 0.0,
            "PV_AZIMUTH": 0.0,
        }.get(name, default),
    )
    monkeypatch.setattr(
        "data.pv_forecast.config.get_planning_pv_systems",
        lambda: [
            {"id": "a", "label": "A", "pv_kwp": 4.0, "pv_tilt": 20.0, "pv_azimuth": 0.0},
            {"id": "b", "label": "B", "pv_kwp": 6.0, "pv_tilt": 30.0, "pv_azimuth": -90.0},
        ],
    )

    calls: list[str] = []

    def fake_forecast_one(*, lat, lon, tilt, azimuth, kwp, target_hours):
        calls.append((float(tilt), float(azimuth), float(kwp)))
        return [float(kwp), float(kwp) * 0.5], True

    monkeypatch.setattr(pv_forecast, "_forecast_one_system", fake_forecast_one)

    result = pv_forecast.get_hourly_pv_forecast_for_hours(hours)
    assert result == [10.0, 5.0]
    assert calls == [(20.0, 0.0, 4.0), (30.0, -90.0, 6.0)]

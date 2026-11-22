"""Selectable primary PV forecast source (``plant.pv_forecast_source``).

forecast.solar first was hard-wired; the plant can now plan with Open-Meteo first and keep
forecast.solar as the substitute. Absent key = forecast.solar first (behaviour until now).
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from data import pv_forecast as pf
from house_config import pv_forecast_source as src
from house_config.profiles_store import normalize_house_profiles_document

HOURS = [datetime(2026, 7, 15, 10), datetime(2026, 7, 15, 11), datetime(2026, 7, 15, 12)]
WATTS = {
    "2026-07-15 10:00:00": 1000,
    "2026-07-15 11:00:00": 1000,
    "2026-07-15 12:00:00": 1000,
    "2026-07-15 13:00:00": 1000,
}
SYSTEM = {"lat": 47.4, "lon": 9.7, "tilt": 18.0, "azimuth": 26.0, "kwp": 5.7}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    pf._SOURCE_BY_SYSTEM = {}
    pf._LAST_FETCH_SOURCE = "api"


def _one(primary: str):
    return pf._forecast_one_system(
        **SYSTEM, target_hours=HOURS, shading=None, primary=primary
    )


# --- plant setting -----------------------------------------------------------------


def test_plant_setting_is_validated_and_kept():
    doc = normalize_house_profiles_document(
        {"profiles": [], "plant": {"pv_forecast_source": "open_meteo"}}
    )
    assert doc["plant"]["pv_forecast_source"] == "open_meteo"
    assert src.plant_pv_forecast_source(doc) == src.PV_SOURCE_OPEN_METEO


def test_plant_without_setting_plans_with_forecast_solar_first():
    doc = normalize_house_profiles_document({"profiles": []})
    assert "pv_forecast_source" not in doc.get("plant", {})
    assert src.plant_pv_forecast_source(doc) == src.PV_SOURCE_FORECAST_SOLAR


def test_unknown_source_fails_loud():
    with pytest.raises(ValueError, match="pv_forecast_source"):
        normalize_house_profiles_document(
            {"profiles": [], "plant": {"pv_forecast_source": "solcast"}}
        )


# --- order per system --------------------------------------------------------------


def test_open_meteo_first_does_not_ask_forecast_solar():
    with patch.object(pf, "_check_and_fetch_api_data") as fs_mock, patch.object(
        pf, "_open_meteo_pv_vector", return_value=[0.3, 0.3, 0.3]
    ):
        vector, source = _one(src.PV_SOURCE_OPEN_METEO)
    assert (vector, source) == ([0.3, 0.3, 0.3], pf.SOURCE_OPEN_METEO)
    fs_mock.assert_not_called()


def test_open_meteo_first_falls_back_to_forecast_solar():
    with patch.object(pf, "_check_and_fetch_api_data", return_value=WATTS), patch.object(
        pf, "_open_meteo_pv_vector", side_effect=RuntimeError("offline")
    ):
        vector, source = _one(src.PV_SOURCE_OPEN_METEO)
    assert (vector, source) == ([1.0, 1.0, 1.0], pf.SOURCE_FORECAST_SOLAR)


def test_open_meteo_first_without_both_sources_raises():
    with patch.object(pf, "_check_and_fetch_api_data", return_value=None), patch.object(
        pf, "_open_meteo_pv_vector", side_effect=RuntimeError("offline")
    ):
        with pytest.raises(pf.PvForecastUnavailableError, match="offline"):
            _one(src.PV_SOURCE_OPEN_METEO)


def test_forecast_solar_first_keeps_the_old_order():
    with patch.object(pf, "_check_and_fetch_api_data", return_value=WATTS), patch.object(
        pf, "_open_meteo_pv_vector"
    ) as om_mock:
        vector, source = _one(src.PV_SOURCE_FORECAST_SOLAR)
    assert (vector, source) == ([1.0, 1.0, 1.0], pf.SOURCE_FORECAST_SOLAR)
    om_mock.assert_not_called()


# --- status: substitutes are the systems off the chosen source ---------------------


def test_status_names_the_primary_and_only_real_substitutes(monkeypatch):
    monkeypatch.setattr(pf, "_primary_pv_source", lambda: src.PV_SOURCE_OPEN_METEO)
    monkeypatch.setattr(pf, "_live_profile_horizon", lambda: None)
    monkeypatch.setattr(
        pf.config,
        "get",
        lambda name, default=None, cast=None: {"LATITUDE": 47.4, "LONGITUDE": 9.7}.get(
            name, default
        ),
    )
    monkeypatch.setattr(
        pf.config,
        "get_planning_pv_systems",
        lambda: [
            {"id": "sued", "pv_kwp": 5.7, "pv_tilt": 18.0, "pv_azimuth": 26.0},
            {"id": "nord", "pv_kwp": 6.8, "pv_tilt": 18.0, "pv_azimuth": -154.0},
        ],
    )

    def fake_om(**kwargs):
        if kwargs["azimuth"] == -154.0:
            raise RuntimeError("offline")
        return [0.3, 0.3, 0.3]

    with patch.object(pf, "_check_and_fetch_api_data", return_value=WATTS), patch.object(
        pf, "_open_meteo_pv_vector", side_effect=fake_om
    ):
        pf.get_hourly_pv_forecast_by_system_for_hours(HOURS)

    status = pf.get_api_status()
    assert status["primary_source"] == src.PV_SOURCE_OPEN_METEO
    assert status["source_by_system"] == {
        "sued": pf.SOURCE_OPEN_METEO,
        "nord": pf.SOURCE_FORECAST_SOLAR,
    }
    assert status["substituted_systems"] == ["nord"]


# --- cockpit notice ----------------------------------------------------------------


def _notice(monkeypatch, state: dict) -> list[str]:
    from ui import live_mode

    shown: list[str] = []
    monkeypatch.setattr(live_mode.st, "warning", lambda text: shown.append(text))
    live_mode._render_pv_source_notice(state)
    return shown


def test_notice_with_open_meteo_first_names_forecast_solar_substitutes(monkeypatch):
    shown = _notice(
        monkeypatch,
        {
            "pv_forecast_primary": "open_meteo",
            "pv_forecast_sources": {"sued": "open_meteo", "nord": "forecast_solar"},
        },
    )
    assert len(shown) == 1
    assert "**nord**" in shown[0] and "forecast.solar geplant" in shown[0]


def test_notice_stays_quiet_when_every_system_used_the_primary(monkeypatch):
    shown = _notice(
        monkeypatch,
        {
            "pv_forecast_primary": "open_meteo",
            "pv_forecast_sources": {"sued": "open_meteo", "nord": "open_meteo"},
        },
    )
    assert shown == []


def test_notice_of_a_run_without_primary_reads_forecast_solar_first(monkeypatch):
    shown = _notice(monkeypatch, {"pv_forecast_sources": {"pv": "open_meteo"}})
    assert len(shown) == 1 and "ohne forecast.solar" in shown[0]

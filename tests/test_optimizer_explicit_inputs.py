"""Missing optimizer inputs fail loud or take a visible, documented default (no silent fallback)."""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from data import outdoor_forecast as of
from optimizer import thermal_live_store as tls

_STORE = {
    "volume_liters": 500.0,
    "heat_loss_kw_per_k": 0.02,
    "setpoint_c": 45.0,
    "tolerance_c": 5.0,
}


def _consumer(**extra) -> dict:
    return {
        "id": "wp_heating",
        "type": "thermal_annual",
        "heat_source": {"type": "heat_pump", "heat_pump_type": "luft"},
        "thermal": {"living_area_m2": 0.0, "heat_storage": dict(_STORE)},
        **extra,
    }


# --- Outdoor temperature: no assumed 10 °C -------------------------------------------------


def test_outdoor_forecast_without_forecast_and_sensor_fails_loud():
    with patch.object(of, "get_hourly_outdoor_forecast_c", side_effect=RuntimeError("offline")):
        with pytest.raises(ValueError, match="sens_temperature_outside"):
            of.get_outdoor_forecast_or_live_reading(horizon=3, read_live_ambient_c=lambda: None)


def test_outdoor_forecast_falls_back_to_the_live_reading_only():
    with patch.object(of, "get_hourly_outdoor_forecast_c", side_effect=RuntimeError("offline")):
        series, source = of.get_outdoor_forecast_or_live_reading(
            horizon=3, read_live_ambient_c=lambda: 4.2
        )
    assert series == [4.2, 4.2, 4.2]
    assert source == "fallback_constant"


def test_outdoor_sensor_is_not_read_while_the_forecast_works():
    def _no_read():
        raise AssertionError("sensor read although the forecast worked")

    with patch.object(of, "get_hourly_outdoor_forecast_c", return_value=[1.0, 2.0]):
        series, source = of.get_outdoor_forecast_or_live_reading(
            horizon=2, read_live_ambient_c=_no_read
        )
    assert (series, source) == ([1.0, 2.0], "open_meteo")


def test_live_ambient_forecast_without_sources_fails_loud(monkeypatch):
    monkeypatch.setattr(tls, "_read_live_outdoor_temp_c", lambda _house_doc: None)
    with patch.object(of, "get_hourly_outdoor_forecast_c", side_effect=RuntimeError("offline")):
        with pytest.raises(ValueError, match="Außentemperatur fehlt"):
            tls._live_ambient_forecast(4)


# --- Store T_eq: visible setpoint default --------------------------------------------------


def test_missing_teq_starts_at_setpoint_with_warning(caplog):
    with patch(
        "integrations.ehal_live.fetch_heat_storage_temps",
        return_value={"temp_eq_c": None, "temp_low_c": 40.0},
    ):
        with caplog.at_level(logging.WARNING, logger=tls.__name__):
            readings = tls.resolve_heat_storage_readings(_consumer())
    assert readings.temp_eq_c == 45.0
    assert readings.used_measured_eq is False
    assert "T_eq" in caplog.text


@patch("optimizer.thermal_live_store.resolve_heat_storage_readings")
def test_observability_names_the_setpoint_start(mock_readings):
    mock_readings.return_value = tls.HeatStorageReadings(
        temp_eq_c=45.0, temp_low_c=None, used_measured_eq=False, used_measured_low=False
    )
    consumer = _consumer(nominal_power_kw=3.0)
    item = tls.build_heat_storage_observability(
        consumer, house_profile={"consumers": [consumer]}, ambient_forecast_c=[10.0] * 4
    )
    assert item is not None
    assert item["eq_source"] == tls.EQ_SOURCE_SETPOINT_NO_VALUE


# --- Heat pump power: no 3 kW default ------------------------------------------------------


@patch("optimizer.thermal_live_store.resolve_heat_storage_readings")
def test_missing_heat_pump_power_fails_loud(mock_readings):
    mock_readings.return_value = tls.HeatStorageReadings(
        temp_eq_c=44.0, temp_low_c=None, used_measured_eq=True, used_measured_low=False
    )
    consumer = _consumer()
    with pytest.raises(ValueError, match="Leistung des Wärmeerzeugers fehlt"):
        tls.build_heat_storage_observability(
            consumer, house_profile={"consumers": [consumer]}, ambient_forecast_c=[10.0] * 4
        )


# --- Observability: only a store needs the outdoor temperature ------------------------------


def test_observability_without_store_needs_no_outdoor_temperature(monkeypatch):
    def _no_forecast(*_a, **_k):
        raise AssertionError("outdoor forecast read without a heat store")

    monkeypatch.setattr(tls, "_live_ambient_forecast", _no_forecast)
    consumer = {"id": "wp", "type": "thermal_annual", "thermal": {}}
    assert tls.collect_heat_storage_observability([consumer], house_profile={}) == []


def test_observability_reports_missing_outdoor_temperature_per_store(monkeypatch):
    def _missing(*_a, **_k):
        raise ValueError("Außentemperatur fehlt")

    monkeypatch.setattr(tls, "_live_ambient_forecast", _missing)
    items = tls.collect_heat_storage_observability([_consumer()], house_profile={})
    assert items == [
        {"consumer_id": "wp_heating", "kind": "heat_storage", "error": "Außentemperatur fehlt"}
    ]

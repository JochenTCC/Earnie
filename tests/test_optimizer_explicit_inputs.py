"""Missing optimizer inputs fail loud or take a visible, documented default (no silent fallback)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pulp
import pytest

from data import outdoor_forecast as of
from optimizer import thermal_live_store as tls
from optimizer.milp_horizon_extras import _add_virtual_reserve_deadline_charge

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


# --- Virtual reserve deadline ---------------------------------------------------------------

_START = datetime(2026, 11, 18, 0, tzinfo=timezone.utc)


def _reserve_model(horizon: int = 6):
    prob = pulp.LpProblem("reserve", pulp.LpMinimize)
    p_charge = [pulp.LpVariable(f"c{t}", lowBound=0) for t in range(horizon)]
    model = SimpleNamespace(prob=prob, horizon=horizon, p_charge=p_charge, dt_h=1.0)
    matrix = [{"slot_datetime": _START + timedelta(hours=t)} for t in range(horizon)]
    return model, matrix


def _constrained_slots(model) -> list[int]:
    constraint = model.prob.constraints["virtual_reserve_deadline_charge"]
    return sorted(int(var.name[1:]) for var in constraint.keys())


def _add(model, matrix, deadline, refill_kwh=3.0):
    _add_virtual_reserve_deadline_charge(
        model,
        matrix=matrix,
        refill_kwh=refill_kwh,
        max_charge_kw=2.0,
        efficiency=1.0,
        deadline=deadline,
    )


def test_reserve_deadline_limits_the_window():
    model, matrix = _reserve_model()
    _add(model, matrix, _START + timedelta(hours=4))
    assert _constrained_slots(model) == [0, 1, 2, 3]


def test_overdue_reserve_deadline_charges_as_soon_as_possible(caplog):
    model, matrix = _reserve_model()
    with caplog.at_level(logging.WARNING):
        _add(model, matrix, _START - timedelta(hours=1))
    # 3 kWh at 2 kW → the first two slots, not the whole horizon.
    assert _constrained_slots(model) == [0, 1]
    assert "abgelaufen" in caplog.text


def test_missing_reserve_deadline_fails_loud():
    model, matrix = _reserve_model()
    with pytest.raises(ValueError, match="Deadline"):
        _add(model, matrix, None)


def test_unparsable_reserve_deadline_fails_loud():
    from optimizer.milp import _add_virtual_reserve_refill

    model, matrix = _reserve_model()
    primary = {
        "_virtual_reserve_refill_kwh": 1.0,
        "_virtual_reserve_refill_deadline_utc": "not-a-time",
        "max_charge_power_kw": 2.0,
    }
    with pytest.raises(ValueError, match="ISO"):
        _add_virtual_reserve_refill(model, matrix, primary)


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

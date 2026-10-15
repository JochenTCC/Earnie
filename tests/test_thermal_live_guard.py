"""ThermalHorizon P5 — a Live cycle runs no thermal year simulation except parameter derivation."""
from __future__ import annotations

import contextvars
from datetime import date, datetime, time, timedelta

import pytest

import house_config.thermal_rc_profile as rc_profile
import optimizer.thermal_house as thermal_house
import optimizer.thermal_parameters as thermal_parameters
from optimizer import thermal_live_store as tls
from optimizer.live_cycle_scope import is_live_thermal_planning, live_cycle_scope
from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

_DAY = date(2026, 1, 15)
_GEO = {"latitude": 47.4, "longitude": 9.7, "timezone_name": "Europe/Vienna"}
_STORE = {
    "volume_liters": 887.0,
    "heat_loss_kw_per_k": 0.01,
    "setpoint_c": 47.0,
    "tolerance_c": 5.0,
}


def _thermal_annual(cid: str, **thermal) -> dict:
    return {
        "id": cid,
        "label": cid,
        "type": "thermal_annual",
        "nominal_power_kw": 1.9,
        "daily_target_source": "thermal_annual",
        "thermal": {
            **_GEO,
            "living_area_m2": 157.0,
            "building_class": 2,
            "heat_pump_type": "erde",
            "persons": 2,
            "target_temp_c": 21.5,
            "heating_limit_c": 15.0,
            **thermal,
        },
    }


def _pool() -> dict:
    return {
        "id": "pool",
        "type": "thermal_rc",
        "nominal_power_kw": 3.0,
        "thermal_rc": {
            **_GEO,
            "setpoint_c": 36.0,
            "tolerance_c": 1.0,
            "water_volume_liters": 1500.0,
            "heat_loss_kw_per_k": 0.05,
            "heating_efficiency": 1.0,
        },
    }


def _profile() -> dict:
    return {
        "id": "guard_home",
        **_GEO,
        "absent_mode": False,
        "consumers": [
            _thermal_annual("wp_store", heat_storage=_STORE, solar_thermal_area_m2=10.3),
            _thermal_annual("wp_house"),
            _thermal_annual("wp_legacy", living_area_m2=0.0, solar_thermal_area_m2=6.0),
            _pool(),
        ],
    }


def _matrix(mode: str, hours: int = 6) -> list[dict]:
    start = datetime.combine(_DAY, time(22))
    rows = []
    for index in range(hours * 4):
        slot = start + timedelta(minutes=15 * index)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "consumption_mode": mode,
            }
        )
    # Live snapshot marker only on the current slot, like apply_live_snapshot_to_matrix.
    rows[0]["consumption_mode"] = mode
    return rows


@pytest.fixture
def year_sim_spy(monkeypatch):
    """Counts year-model calls; calls inside parameter derivation are allowed."""
    install_open_meteo_climate_mock(monkeypatch)
    in_derivation = contextvars.ContextVar("in_derivation", default=False)
    counts = {"outside": [], "derivations": 0}

    def _spy(name, fn):
        def inner(*args, **kwargs):
            if not in_derivation.get():
                counts["outside"].append(name)
            return fn(*args, **kwargs)

        return inner

    def _allowed(fn):
        def inner(*args, **kwargs):
            counts["derivations"] += 1
            token = in_derivation.set(True)
            try:
                return fn(*args, **kwargs)
            finally:
                in_derivation.reset(token)

        return inner

    monkeypatch.setattr(
        thermal_house, "house_year_result", _spy("house_year_result", thermal_house.house_year_result)
    )
    monkeypatch.setattr(
        rc_profile,
        "thermal_rc_hourly_kw_and_temp_from_ambient",
        _spy("thermal_rc_year", rc_profile.thermal_rc_hourly_kw_and_temp_from_ambient),
    )
    monkeypatch.setattr(
        thermal_parameters,
        "_derive_house_parameters",
        _allowed(thermal_parameters._derive_house_parameters),
    )
    monkeypatch.setattr(
        thermal_parameters,
        "_derive_thermal_rc_parameters",
        _allowed(thermal_parameters._derive_thermal_rc_parameters),
    )
    # Live inputs: measured store, forecasts.
    monkeypatch.setattr(
        tls,
        "resolve_heat_storage_readings",
        lambda *_a, **_k: tls.HeatStorageReadings(48.0, 45.0, True, True),
    )
    monkeypatch.setattr(tls, "_live_ambient_forecast", lambda horizon_h: [2.0] * horizon_h)
    monkeypatch.setattr(
        "data.outdoor_forecast.get_hourly_tilted_irradiance_forecast_wm2",
        lambda **kwargs: [150.0] * kwargs["horizon"],
    )
    monkeypatch.setattr(
        "optimizer.absent_mode.resolve_absent_status", lambda _p: {"effective": False}
    )
    profile = _profile()
    monkeypatch.setattr(
        "config.get_resolved_runtime_settings", lambda: {"_house_profile": profile}
    )
    return counts, profile


def _run_live_thermal_cycle(profile: dict, matrix: list[dict]) -> None:
    from house_config.baseload import consumer_annual_kwh
    from house_config.planning_flex_bridge import planning_thermal_to_milp
    from optimizer.targets import resolve_thermal_annual_horizon_kwh
    from optimizer.thermal_flex_context import resolve_thermal_flex_contexts

    with live_cycle_scope():
        for consumer in profile["consumers"]:
            consumer_annual_kwh(consumer)  # baseload split (profile load)
        thermal = [c for c in profile["consumers"] if c["type"] == "thermal_annual"]
        milp_consumers = [planning_thermal_to_milp(c) for c in thermal]
        contexts = resolve_thermal_flex_contexts(matrix, milp_consumers, profile)
        assert set(contexts) == {c["id"] for c in milp_consumers}
        for consumer in milp_consumers:
            resolve_thermal_annual_horizon_kwh(consumer, matrix)


@pytest.mark.parametrize("first_row_mode", ["live_snapshot", "forecast"])
def test_live_cycle_runs_no_year_simulation(year_sim_spy, first_row_mode):
    """Also when telemetry was rejected and the first row stays ``forecast``."""
    counts, profile = year_sim_spy

    _run_live_thermal_cycle(profile, _matrix(first_row_mode))
    first_cycle_derivations = counts["derivations"]
    _run_live_thermal_cycle(profile, _matrix(first_row_mode))

    assert counts["outside"] == []
    # Exactly one parameter derivation per thermal consumer (baseload and Live share
    # it), none in the next cycle (memo).
    assert first_cycle_derivations == len(profile["consumers"])
    assert counts["derivations"] == first_cycle_derivations


def test_live_thermal_planning_follows_cycle_scope():
    forecast = _matrix("forecast")
    assert not is_live_thermal_planning(forecast)
    assert is_live_thermal_planning(_matrix("live_snapshot"))
    with live_cycle_scope():
        assert is_live_thermal_planning(forecast)
        assert not is_live_thermal_planning(_matrix("profile_spec"))
        assert not is_live_thermal_planning([])

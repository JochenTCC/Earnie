"""Optional Earnie-Points consumer keys: ``bidirectional`` (ev), ``appliance_kind``."""
from __future__ import annotations

import pytest

from house_config.profiles_store import _normalize_consumer, _serialize_consumer


def _ev(**extra) -> dict:
    return {
        "id": "wallbox",
        "label": "Wallbox",
        "type": "ev",
        "nominal_power_kw": 11.0,
        "battery_capacity_kwh": 60.0,
        "charging_schedule": {
            "weekday": {
                "car_available_from_hour": 18,
                "ready_by_hour": 7,
                "daily_rest_soc": 40.0,
            },
        },
        **extra,
    }


def _generic(**extra) -> dict:
    return {"id": "klima", "label": "Klima", "type": "generic", "nominal_power_kw": 2.0, **extra}


def _rc(**extra) -> dict:
    return {
        "id": "boiler",
        "label": "Boiler",
        "type": "thermal_rc",
        "nominal_power_kw": 3.0,
        "water_volume_liters": 300.0,
        "heating_efficiency": 0.95,
        "heat_loss_kw_per_k": 0.002,
        "setpoint_c": 55.0,
        "tolerance_c": 5.0,
        **extra,
    }


def test_absent_keys_stay_absent():
    for raw in (_ev(), _generic(), _rc()):
        spec = _normalize_consumer(raw, 0, "home")
        assert "bidirectional" not in spec
        assert "appliance_kind" not in spec
        out = _serialize_consumer(spec)
        assert "bidirectional" not in out
        assert "appliance_kind" not in out


@pytest.mark.parametrize("value", [True, False])
def test_bidirectional_roundtrip(value):
    spec = _normalize_consumer(_ev(bidirectional=value), 0, "home")
    assert spec["bidirectional"] is value
    assert _serialize_consumer(spec)["bidirectional"] is value


@pytest.mark.parametrize("raw", [_generic(), _rc()])
def test_appliance_kind_roundtrip(raw):
    raw["appliance_kind"] = "Air_Conditioner"
    spec = _normalize_consumer(raw, 0, "home")
    assert spec["appliance_kind"] == "air_conditioner"
    assert _serialize_consumer(spec)["appliance_kind"] == "air_conditioner"


@pytest.mark.parametrize("bad", ["yes", 1, None])
def test_bidirectional_must_be_bool(bad):
    with pytest.raises(ValueError, match="bidirectional muss true oder false sein"):
        _normalize_consumer(_ev(bidirectional=bad), 0, "home")


def test_bidirectional_rejected_on_non_ev():
    with pytest.raises(ValueError, match="bidirectional ist nur für type=ev"):
        _normalize_consumer(_generic(bidirectional=True), 0, "home")


def test_appliance_kind_unknown_value_rejected():
    with pytest.raises(ValueError, match="appliance_kind 'dryer' unbekannt"):
        _normalize_consumer(_generic(appliance_kind="dryer"), 0, "home")


def test_appliance_kind_rejected_on_ev():
    with pytest.raises(ValueError, match="appliance_kind ist nur für type=generic oder thermal_rc"):
        _normalize_consumer(_ev(appliance_kind="air_conditioner"), 0, "home")

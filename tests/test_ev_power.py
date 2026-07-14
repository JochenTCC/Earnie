import pytest

from settings import ev_power as ep


def test_ampere_to_kw_single_phase_default_voltage():
    assert ep.ampere_to_kw(16.0, voltage_v=230.0, phases=1) == pytest.approx(3.68)


def test_ampere_to_kw_three_phase():
    assert ep.ampere_to_kw(16.0, voltage_v=230.0, phases=3) == pytest.approx(11.04)


def test_ev_nominal_power_conversion_defaults():
    voltage_v, phases = ep.ev_nominal_power_conversion({"charging_schedule": {}})
    assert voltage_v == pytest.approx(230.0)
    assert phases == 1


def test_ev_nominal_power_conversion_schedule_level():
    consumer = {
        "charging_schedule": {
            "nominal_power_voltage_v": 400.0,
            "nominal_power_phases": 3,
        }
    }
    voltage_v, phases = ep.ev_nominal_power_conversion(consumer)
    assert voltage_v == pytest.approx(400.0)
    assert phases == 3


def test_ev_nominal_power_conversion_loxone_fallback():
    consumer = {
        "charging_schedule": {
            "loxone": {
                "nominal_power_voltage_v": 230.0,
                "nominal_power_phases": 3,
            }
        }
    }
    voltage_v, phases = ep.ev_nominal_power_conversion(consumer)
    assert voltage_v == pytest.approx(230.0)
    assert phases == 3


def test_ev_nominal_power_conversion_schedule_overrides_loxone():
    consumer = {
        "charging_schedule": {
            "nominal_power_voltage_v": 400.0,
            "nominal_power_phases": 1,
            "loxone": {
                "nominal_power_voltage_v": 230.0,
                "nominal_power_phases": 3,
            },
        }
    }
    voltage_v, phases = ep.ev_nominal_power_conversion(consumer)
    assert voltage_v == pytest.approx(400.0)
    assert phases == 1


def test_kw_from_nominal_reading_ampere():
    consumer = {
        "charging_schedule": {
            "nominal_power_voltage_v": 230.0,
            "nominal_power_phases": 3,
        }
    }
    assert ep.kw_from_nominal_reading(16.0, "a", consumer) == pytest.approx(11.04)


def test_kw_from_nominal_reading_kw_passthrough():
    consumer = {"charging_schedule": {}}
    assert ep.kw_from_nominal_reading(3.5, "kw", consumer) == pytest.approx(3.5)


def test_merge_ev_power_conversion_fields_only_explicit():
    merged = ep.merge_ev_power_conversion_fields({"enabled": True}, {"nominal_power_phases": 3})
    assert "nominal_power_voltage_v" not in merged
    assert merged["nominal_power_phases"] == 3

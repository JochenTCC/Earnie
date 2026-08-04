"""Unit tests for thermal Merker dual-read via ehal_bindings."""
from __future__ import annotations

from unittest.mock import patch

from integrations.loxone_client import fetch_thermal_readings


def test_fetch_thermal_readings_ehal_only():
    consumer = {
        "id": "swimspa",
        "ehal_bindings": {
            "sens_temperature_water": "Ist",
            "get_temperature_water_setpoint": "Soll",
            "get_temperature_tolerance_c": "Tol",
            "sens_heating_active": "Heat",
            "sens_temperature_outside": "Outside",
        },
        "thermal_control": {"setpoint_c": 35.0, "tolerance_c": 1.0},
    }

    def _fake(io_name: str):
        return {
            "Ist": 34.0,
            "Soll": 35.0,
            "Tol": 1.0,
            "Heat": 1.0,
            "Outside": 12.0,
        }.get(str(io_name))

    with patch(
        "integrations.loxone_client.fetch_loxone_generic_value",
        side_effect=_fake,
    ):
        readings = fetch_thermal_readings(consumer)

    assert readings["actual_c"] == 34.0
    assert readings["setpoint_c"] == 35.0
    assert readings["tolerance_c"] == 1.0
    assert readings["ambient_c"] == 12.0
    assert readings["heating_active"] is True
    assert readings["missing_signals"] == []


def test_fetch_thermal_readings_plant_ambient():
    consumer = {
        "id": "swimspa",
        "ehal_bindings": {"sens_temperature_water": "Ist"},
        "thermal_control": {"setpoint_c": 35.0, "tolerance_c": 1.0},
    }
    house = {
        "plant": {
            "ehal_bindings": {"sens_temperature_outside": "PlantOutside"},
        }
    }

    def _fake(io_name: str):
        return {"Ist": 33.0, "PlantOutside": 8.0}.get(str(io_name))

    with patch(
        "integrations.loxone_client.fetch_loxone_generic_value",
        side_effect=_fake,
    ):
        readings = fetch_thermal_readings(consumer, house_doc=house)

    assert readings["actual_c"] == 33.0
    assert readings["ambient_c"] == 8.0

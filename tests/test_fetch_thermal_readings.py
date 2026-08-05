"""Unit tests for thermal Merker reads via ehal_bindings (plant ambient only)."""
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
            # leftover consumer ambient must not be used
            "sens_temperature_outside": "Outside",
        },
        "thermal_control": {"setpoint_c": 35.0, "tolerance_c": 1.0},
    }
    house = {
        "plant": {
            "ehal_bindings": {"sens_temperature_outside": "PlantOutside"},
        }
    }

    def _fake(io_name: str):
        return {
            "Ist": 34.0,
            "Soll": 35.0,
            "Tol": 1.0,
            "Heat": 1.0,
            "Outside": 12.0,
            "PlantOutside": 11.0,
        }.get(str(io_name))

    with patch(
        "integrations.loxone_client.fetch_loxone_generic_value",
        side_effect=_fake,
    ):
        readings = fetch_thermal_readings(consumer, house_doc=house)

    assert readings["actual_c"] == 34.0
    assert readings["setpoint_c"] == 35.0
    assert readings["tolerance_c"] == 1.0
    assert readings["ambient_c"] == 11.0
    assert readings["heating_active"] is True
    assert readings["missing_signals"] == []


def test_fetch_thermal_readings_ignores_consumer_only_ambient():
    consumer = {
        "id": "swimspa",
        "ehal_bindings": {
            "sens_temperature_water": "Ist",
            "sens_temperature_outside": "Outside",
        },
        "thermal_control": {"setpoint_c": 35.0, "tolerance_c": 1.0},
    }

    def _fake(io_name: str):
        return {"Ist": 33.0, "Outside": 12.0}.get(str(io_name))

    with patch(
        "integrations.loxone_client.fetch_loxone_generic_value",
        side_effect=_fake,
    ):
        readings = fetch_thermal_readings(consumer, house_doc={})

    assert readings["actual_c"] == 33.0
    assert readings["ambient_c"] is None
    assert "sens_temperature_outside" in readings["missing_signals"]


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


def test_fetch_thermal_readings_loads_plant_ambient_when_house_doc_omitted():
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
        return {"Ist": 33.0, "PlantOutside": 9.5}.get(str(io_name))

    with (
        patch(
            "integrations.loxone_client._default_house_profiles_doc",
            return_value=house,
        ),
        patch(
            "integrations.loxone_client.fetch_loxone_generic_value",
            side_effect=_fake,
        ),
    ):
        readings = fetch_thermal_readings(consumer)

    assert readings["ambient_c"] == 9.5
    assert readings["missing_signals"] == []

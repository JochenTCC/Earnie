# tests/test_components_store.py
"""Tests für config/components.json Sidecar."""
from __future__ import annotations

import json

import pytest

from house_config.components_store import (
    load_components_document,
    normalize_components_document,
    save_components_document,
)


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "components.json"
    save_components_document(
        str(path),
        {
            "batteries": [
                {
                    "id": "bat",
                    "label": "5 kWh",
                    "battery_capacity_kwh": 5.0,
                    "battery_max_charge_power_kw": 3.0,
                    "battery_max_discharge_power_kw": 2.5,
                    "battery_efficiency": 0.97,
                    "battery_min_soc": 10.0,
                    "battery_max_soc": 100.0,
                    "threshold_power": 0.05,
                    "limits_from_live": True,
                    "control": "limits_only",
                    "battery_wear": {"enabled": False},
                }
            ],
            "pv_systems": [
                {
                    "id": "pv",
                    "label": "Dach",
                    "kwp": 9.0,
                    "pv_tilt": 30,
                    "pv_azimuth": 0,
                }
            ],
        },
    )
    loaded = load_components_document(str(path))
    bat = loaded["batteries"][0]
    assert bat["id"] == "bat"
    assert bat["battery_max_charge_power_kw"] == 3.0
    assert bat["battery_max_discharge_power_kw"] == 2.5
    assert bat["limits_from_live"] is True
    assert bat["control"] == "limits_only"
    assert "battery_max_power_kw" not in bat
    assert loaded["pv_systems"][0]["kwp"] == 9.0


def test_save_migrates_legacy_max_power_to_split_fields(tmp_path):
    path = tmp_path / "components.json"
    save_components_document(
        str(path),
        {
            "batteries": [
                {
                    "id": "bat",
                    "label": "5 kWh",
                    "battery_capacity_kwh": 5.0,
                    "battery_max_power_kw": 2.5,
                    "battery_efficiency": 0.97,
                    "battery_min_soc": 10.0,
                    "battery_max_soc": 100.0,
                    "threshold_power": 0.05,
                    "battery_wear": {"enabled": False},
                }
            ],
            "pv_systems": [],
        },
    )
    bat = load_components_document(str(path))["batteries"][0]
    assert bat["battery_max_charge_power_kw"] == 2.5
    assert bat["battery_max_discharge_power_kw"] == 2.5
    assert bat["limits_from_live"] is False
    assert "battery_max_power_kw" not in bat


def test_normalize_rejects_duplicate_battery_ids():
    with pytest.raises(ValueError, match="doppelte id"):
        normalize_components_document(
            {
                "batteries": [
                    {
                        "id": "bat",
                        "battery_capacity_kwh": 5.0,
                        "battery_max_power_kw": 2.5,
                        "battery_efficiency": 0.97,
                        "battery_min_soc": 10.0,
                        "battery_max_soc": 100.0,
                    },
                    {
                        "id": "bat",
                        "battery_capacity_kwh": 8.0,
                        "battery_max_power_kw": 4.0,
                        "battery_efficiency": 0.95,
                        "battery_min_soc": 10.0,
                        "battery_max_soc": 100.0,
                    },
                ],
                "pv_systems": [],
            }
        )


def test_load_missing_file_returns_empty_catalog(tmp_path):
    doc = load_components_document(str(tmp_path / "missing.json"))
    assert doc == {"batteries": [], "pv_systems": []}


def test_save_persists_powerstation_type_fields(tmp_path):
    path = tmp_path / "components.json"
    save_components_document(
        str(path),
        {
            "batteries": [
                {
                    "id": "ps_wm",
                    "label": "1 kWh Virtuell",
                    "type": "powerstation",
                    "backing": "virtual",
                    "role": "single_use",
                    "attached_consumer_id": "waschmaschine",
                    "battery_capacity_kwh": 1.0,
                    "battery_max_charge_power_kw": 1.0,
                    "battery_max_discharge_power_kw": 0.0,
                    "battery_efficiency": 0.95,
                    "battery_min_soc": 5.0,
                    "battery_max_soc": 100.0,
                    "threshold_power": 0.05,
                    "battery_wear": {"enabled": False},
                }
            ],
            "pv_systems": [],
        },
    )
    bat = load_components_document(str(path))["batteries"][0]
    assert bat["type"] == "powerstation"
    assert bat["backing"] == "virtual"
    assert bat["role"] == "single_use"
    assert bat["attached_consumer_ids"] == ["waschmaschine"]
    assert bat["attached_consumer_id"] == "waschmaschine"


def test_save_persists_powerstation_without_attached_consumer(tmp_path):
    path = tmp_path / "components.json"
    save_components_document(
        str(path),
        {
            "batteries": [
                {
                    "id": "ps_wm",
                    "label": "1 kWh Virtuell",
                    "type": "powerstation",
                    "backing": "virtual",
                    "role": "single_use",
                    "battery_capacity_kwh": 1.0,
                    "battery_max_charge_power_kw": 1.0,
                    "battery_max_discharge_power_kw": 0.0,
                    "battery_efficiency": 0.95,
                    "battery_min_soc": 5.0,
                    "battery_max_soc": 100.0,
                    "threshold_power": 0.05,
                    "battery_wear": {"enabled": False},
                }
            ],
            "pv_systems": [],
        },
    )
    bat = load_components_document(str(path))["batteries"][0]
    assert bat["type"] == "powerstation"
    assert bat.get("attached_consumer_id", "") == ""

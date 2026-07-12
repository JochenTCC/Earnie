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
                    "battery_max_power_kw": 2.5,
                    "battery_efficiency": 0.97,
                    "battery_min_soc": 10.0,
                    "battery_max_soc": 100.0,
                    "threshold_power": 0.05,
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
    assert loaded["batteries"][0]["id"] == "bat"
    assert loaded["pv_systems"][0]["kwp"] == 9.0


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

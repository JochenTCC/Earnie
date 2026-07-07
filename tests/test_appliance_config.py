"""Tests für den appliances-Config-Block (Empfehlungsmodus)."""
from __future__ import annotations

import pytest

import config
from config import Config


def test_get_appliances_empty_without_block():
    # Fixture-Config (conftest) enthält keinen appliances-Block → leere Liste.
    assert config.get_appliances() == []


def test_normalize_loxone_appliance():
    spec = Config._normalize_appliance(
        {
            "id": "waschmaschine",
            "name": "Waschmaschine",
            "power_source": "loxone",
            "loxone_power_name": "Leistung Waschmaschine",
            "default_power_kw": 2.0,
            "default_runtime_h": 2.0,
        },
        0,
    )
    assert spec["power_source"] == "loxone"
    assert spec["loxone_power_name"] == "Leistung Waschmaschine"
    assert spec["default_runtime_h"] == 2.0
    assert spec["default_power_kw"] == 2.0


def test_loxone_appliance_requires_default_power():
    with pytest.raises(ValueError, match="default_power_kw"):
        Config._normalize_appliance(
            {
                "id": "waschmaschine",
                "name": "Waschmaschine",
                "power_source": "loxone",
                "loxone_power_name": "Leistung Waschmaschine",
            },
            0,
        )


def test_normalize_manual_appliance():
    spec = Config._normalize_appliance(
        {
            "id": "geschirrspueler",
            "name": "Geschirrspüler",
            "power_source": "manual",
            "default_power_kw": 1.2,
        },
        0,
    )
    assert spec["power_source"] == "manual"
    assert spec["default_power_kw"] == 1.2
    assert spec["loxone_power_name"] == ""


def test_loxone_appliance_requires_merker_name():
    with pytest.raises(ValueError, match="loxone_power_name"):
        Config._normalize_appliance(
            {"id": "x", "name": "X", "power_source": "loxone"}, 0
        )


def test_invalid_power_source_raises():
    with pytest.raises(ValueError, match="power_source"):
        Config._normalize_appliance(
            {"id": "x", "name": "X", "power_source": "hue"}, 0
        )


def test_missing_id_raises():
    with pytest.raises(ValueError, match="id fehlt"):
        Config._normalize_appliance(
            {"name": "X", "power_source": "manual"}, 3
        )


def test_negative_runtime_raises():
    with pytest.raises(ValueError, match="default_runtime_h"):
        Config._normalize_appliance(
            {"id": "x", "name": "X", "power_source": "manual", "default_runtime_h": 0},
            0,
        )

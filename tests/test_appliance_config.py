"""Tests für den appliances-Config-Block (Empfehlungsmodus)."""
from __future__ import annotations

import json

import pytest

import config
from config import Config, reinit_config


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


def test_update_appliance_defaults_roundtrip(tmp_path, monkeypatch):
    base = json.loads(open(config.CONFIG_JSON_PATH, encoding="utf-8").read())
    cfg_path = tmp_path / "config.json"
    base["appliances"] = [
        {
            "id": "waschmaschine",
            "name": "Waschmaschine",
            "power_source": "manual",
            "default_power_kw": 2.0,
            "default_runtime_h": 2.0,
        }
    ]
    cfg_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(cfg_path))
    reinit_config()

    config.update_appliance_defaults("waschmaschine", power_kw=2.5, runtime_h=1.75)
    reinit_config()

    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    entry = saved["appliances"][0]
    assert entry["default_power_kw"] == 2.5
    assert entry["default_runtime_h"] == 1.75
    appliance = config.get_appliances()[0]
    assert appliance["default_power_kw"] == 2.5
    assert appliance["default_runtime_h"] == 1.75


def test_update_appliance_unknown_id_raises(tmp_path, monkeypatch):
    base = json.loads(open(config.CONFIG_JSON_PATH, encoding="utf-8").read())
    base["appliances"] = []
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(base, indent=2), encoding="utf-8")
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(cfg_path))
    reinit_config()
    with pytest.raises(KeyError, match="waschmaschine"):
        config.update_appliance_defaults("waschmaschine", power_kw=2.0, runtime_h=2.0)


def test_recommendation_appliances_from_house_profile():
    from settings.appliances import recommendation_appliances_from_profile

    profile = {
        "id": "example_efh",
        "consumers": [
            {
                "id": "waschmaschine",
                "label": "Waschmaschine",
                "type": "generic",
                "nominal_power_kw": 2.0,
                "earnie_role": "manual",
                "schedule": {
                    "runs_per_week": 5,
                    "duration_h": 2.0,
                    "start_hour": 15,
                    "start_shift_h": 4.0,
                },
                "appliance_recommendation": {
                    "power_source": "loxone",
                    "default_power_kw": 2.0,
                    "default_runtime_h": 2.0,
                },
                "loxone_inputs": {"power_name": "Leistung Waschmaschine"},
            }
        ],
    }
    appliances = recommendation_appliances_from_profile(profile)
    assert len(appliances) == 1
    assert appliances[0]["id"] == "waschmaschine"
    assert appliances[0]["name"] == "Waschmaschine"
    assert appliances[0]["default_runtime_h"] == 2.0
    assert appliances[0]["recommendation_horizon_h"] == 4
    assert appliances[0]["loxone_inputs"] == {"power_name": "Leistung Waschmaschine"}

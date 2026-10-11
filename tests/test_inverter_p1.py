"""2.7.l Inverter P1: schema resolution, migrate, fail-fast."""
from __future__ import annotations

import json

import pytest

from house_config.entity_resolution import resolve_components_into_settings
from house_config.inverter import (
    needs_inverter_migration,
    reject_if_needs_inverter_migration,
    validate_inverter_topology,
)
from house_config.migrate_inverters import migrate_components_inverters


def test_needs_migration_when_kind_present():
    assert needs_inverter_migration(
        {"batteries": [{"id": "a", "kind": "isolated"}], "pv_systems": []}
    )


def test_needs_migration_when_inverters_key_missing():
    assert needs_inverter_migration(
        {"batteries": [{"id": "a"}], "pv_systems": []}
    )


def test_no_migration_when_empty_catalog():
    assert not needs_inverter_migration({"batteries": [], "pv_systems": []})


def test_migrate_isolated_gets_owned_island():
    doc = {
        "batteries": [
            {
                "id": "eco",
                "kind": "isolated",
                "battery_capacity_kwh": 2,
            }
        ],
        "pv_systems": [{"id": "pv1", "kwp": 1.0}],
    }
    out, changed = migrate_components_inverters(doc)
    assert changed
    assert "kind" not in out["batteries"][0]
    inv_id = out["batteries"][0]["inverter_id"]
    assert inv_id == "wr_eco"
    island = next(i for i in out["inverters"] if i["id"] == inv_id)
    assert island["ac_connection"] == "island"
    assert island["owned_by"] == "eco"
    assert out["pv_systems"][0]["inverter_id"] == "wr_main"


def test_resolve_planning_inverters():
    components = {
        "inverters": [
            {
                "id": "wr_main",
                "type": "hybrid",
                "ac_connection": "grid_tied",
                "control": "full",
            }
        ],
        "batteries": [
            {
                "id": "bat",
                "label": "B",
                "inverter_id": "wr_main",
                "battery_capacity_kwh": 5.0,
                "battery_max_charge_power_kw": 2.5,
                "battery_max_discharge_power_kw": 2.5,
                "battery_efficiency": 0.97,
                "battery_min_soc": 10.0,
                "battery_max_soc": 100.0,
                "threshold_power": 0.02,
                "control": "full",
                "ehal_bindings": {},
                "battery_wear": None,
            }
        ],
        "pv_systems": [
            {
                "id": "pv",
                "kwp": 6.0,
                "inverter_id": "wr_main",
            }
        ],
    }
    resolved = resolve_components_into_settings(
        {"battery_ids": ["bat"], "pv_system_ids": ["pv"]},
        components,
    )
    assert len(resolved["_planning_inverters"]) == 1
    assert resolved["_planning_batteries"][0]["ac_connection"] == "grid_tied"
    assert resolved["battery_ac_connection"] == "grid_tied"


def test_validate_unknown_inverter_id():
    with pytest.raises(ValueError, match="unbekannte inverter_id"):
        validate_inverter_topology(
            inverters={},
            batteries={
                "bat": {"id": "bat", "inverter_id": "missing", "type": "house"}
            },
            pv_systems={},
        )


def test_migrate_script_roundtrip(tmp_path):
    from scripts.migrate_inverters_once import main

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "components.json"
    path.write_text(
        json.dumps(
            {
                "batteries": [
                    {
                        "id": "a",
                        "kind": "battery_inverter",
                        "battery_capacity_kwh": 5,
                    }
                ],
                "pv_systems": [],
            }
        ),
        encoding="utf-8",
    )
    main(["--config-dir", str(config_dir)])
    doc = json.loads(path.read_text(encoding="utf-8"))
    reject_if_needs_inverter_migration(doc)
    assert doc["batteries"][0]["inverter_id"] == "wr_main"

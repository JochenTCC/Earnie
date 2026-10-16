"""Topology P1: regulates_on, plant.grid_meter, live validation, migrate."""
from __future__ import annotations

import json

import pytest

from house_config.entity_resolution import normalize_battery, resolve_components_into_settings
from house_config.inverter import normalize_inverter, validate_inverter_topology
from house_config.migrate_topology import (
    migrate_components_topology,
    migrate_house_profiles_grid_meter,
    needs_topology_migration,
    reject_if_needs_topology_migration,
)
from house_config.profiles_store import _normalize_plant
from house_config.topology_live import validate_live_topology


def _house_bat(**overrides):
    base = {
        "id": "home",
        "label": "Home",
        "inverter_id": "wr_main",
        "battery_capacity_kwh": 10.0,
        "battery_max_charge_power_kw": 5.0,
        "battery_max_discharge_power_kw": 5.0,
        "battery_efficiency": 0.95,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "regulates_on": "grid",
        "battery_wear": {"enabled": False},
    }
    base.update(overrides)
    return base


def _hybrid(**overrides):
    base = {
        "id": "wr_main",
        "type": "hybrid",
        "ac_connection": "grid_tied",
        "control": "full",
        "efficiency": 0.97,
    }
    base.update(overrides)
    return base


def test_normalize_house_requires_regulates_on():
    raw = _house_bat()
    del raw["regulates_on"]
    with pytest.raises(ValueError, match="regulates_on fehlt"):
        normalize_battery(raw, 0)


def test_normalize_house_rejects_unknown_regulates_on():
    raw = _house_bat()
    raw["regulates_on"] = "node_x"
    with pytest.raises(ValueError, match="regulates_on muss"):
        normalize_battery(raw, 0)


def test_normalize_powerstation_rejects_regulates_on():
    with pytest.raises(ValueError, match="nur für type=house"):
        normalize_battery(
            {
                "id": "ps",
                "type": "powerstation",
                "backing": "virtual",
                "role": "single_use",
                "attached_consumer_id": "wm",
                "battery_capacity_kwh": 2.0,
                "battery_max_charge_power_kw": 1.0,
                "battery_max_discharge_power_kw": 0.0,
                "battery_efficiency": 0.9,
                "battery_min_soc": 0.0,
                "battery_max_soc": 100.0,
                "regulates_on": "grid",
                "battery_wear": {"enabled": False},
            },
            0,
        )


def test_normalize_powerstation_ok_without_regulates_on():
    bat = normalize_battery(
        {
            "id": "ps",
            "type": "powerstation",
            "backing": "virtual",
            "role": "single_use",
            "attached_consumer_id": "wm",
            "battery_capacity_kwh": 2.0,
            "battery_max_charge_power_kw": 1.0,
            "battery_max_discharge_power_kw": 0.0,
            "battery_efficiency": 0.9,
            "battery_min_soc": 0.0,
            "battery_max_soc": 100.0,
            "battery_wear": {"enabled": False},
        },
        0,
    )
    assert "regulates_on" not in bat


def test_normalize_inverter_optional_regulates_on():
    inv = normalize_inverter(_hybrid(), 0)
    assert "regulates_on" not in inv
    inv2 = normalize_inverter(_hybrid(regulates_on="grid"), 0)
    assert inv2["regulates_on"] == "grid"


def test_reject_battery_on_pv_string():
    with pytest.raises(ValueError, match="pv_string"):
        validate_inverter_topology(
            inverters={
                "wr_pv": {
                    "id": "wr_pv",
                    "type": "pv_string",
                    "ac_connection": "grid_tied",
                }
            },
            batteries={
                "bat": {
                    "id": "bat",
                    "type": "house",
                    "inverter_id": "wr_pv",
                    "regulates_on": "grid",
                }
            },
            pv_systems={},
        )


def test_plant_grid_meter_normalize():
    plant = _normalize_plant(
        {
            "grid_meter": {
                "at_house_connection": True,
                "single_tariff": True,
            }
        }
    )
    assert plant["grid_meter"]["at_house_connection"] is True
    with pytest.raises(ValueError, match="boolean"):
        _normalize_plant({"grid_meter": {"at_house_connection": 1, "single_tariff": True}})


def test_migrate_components_sets_grid_and_lists_ids():
    doc = {
        "batteries": [
            {k: v for k, v in _house_bat(id="a").items() if k != "regulates_on"},
            {k: v for k, v in _house_bat(id="b").items() if k != "regulates_on"},
        ],
        "inverters": [_hybrid()],
        "pv_systems": [],
    }
    assert needs_topology_migration(doc)
    out, ids = migrate_components_topology(doc)
    assert sorted(ids) == ["a", "b"]
    assert out["batteries"][0]["regulates_on"] == "grid"
    assert not needs_topology_migration(out)
    reject_if_needs_topology_migration(out)


def test_migrate_seed_grid_meter():
    doc = {"profiles": [], "plant": {"max_export_power_kw": 5.0}}
    out, changed = migrate_house_profiles_grid_meter(doc)
    assert changed
    assert out["plant"]["grid_meter"] == {
        "at_house_connection": True,
        "single_tariff": True,
    }
    out2, changed2 = migrate_house_profiles_grid_meter(out)
    assert not changed2


def test_migrate_script_roundtrip(tmp_path):
    from scripts.migrate_topology_once import main

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "components.json").write_text(
        json.dumps(
            {
                "earnie_data_model": 4,
                "inverters": [_hybrid()],
                "batteries": [
                    {
                        k: v
                        for k, v in _house_bat(id="home").items()
                        if k != "regulates_on"
                    }
                ],
                "pv_systems": [],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "house_profiles.json").write_text(
        json.dumps({"earnie_data_model": 4, "profiles": [], "plant": {}}),
        encoding="utf-8",
    )
    main(["--config-dir", str(config_dir)])
    comps = json.loads((config_dir / "components.json").read_text(encoding="utf-8"))
    assert comps["batteries"][0]["regulates_on"] == "grid"
    house = json.loads((config_dir / "house_profiles.json").read_text(encoding="utf-8"))
    assert house["plant"]["grid_meter"]["at_house_connection"] is True


def test_live_ok_single_grid_tied_read_only():
    validate_live_topology(
        plant={
            "grid_meter": {
                "at_house_connection": True,
                "single_tariff": True,
            }
        },
        batteries=[
            {
                **normalize_battery(_house_bat(control="read_only"), 0),
                "ac_connection": "grid_tied",
            }
        ],
        inverters=[normalize_inverter(_hybrid(), 0)],
        live_battery_ids=["home"],
    )


def test_live_refuse_missing_grid_meter():
    with pytest.raises(ValueError, match="grid_meter fehlt"):
        validate_live_topology(
            plant={},
            batteries=[],
            inverters=[],
            live_battery_ids=[],
        )


def test_live_refuse_two_grid_tied_house():
    # regulates_on=none so rule (i) does not fire first; rule (ii) still refuses.
    bat_a = {
        **normalize_battery(_house_bat(id="a", regulates_on="none"), 0),
        "ac_connection": "grid_tied",
    }
    bat_b = {
        **normalize_battery(
            _house_bat(id="b", inverter_id="wr_main", regulates_on="none"), 0
        ),
        "ac_connection": "grid_tied",
    }
    with pytest.raises(ValueError, match="höchstens eine netzgekoppelte"):
        validate_live_topology(
            plant={
                "grid_meter": {
                    "at_house_connection": True,
                    "single_tariff": True,
                }
            },
            batteries=[bat_a, bat_b],
            inverters=[normalize_inverter(_hybrid(), 0)],
            live_battery_ids=["a", "b"],
        )


def test_live_ok_island_plus_one_grid_tied():
    house = {
        **normalize_battery(_house_bat(id="home"), 0),
        "ac_connection": "grid_tied",
    }
    island = {
        **normalize_battery(
            _house_bat(id="island", inverter_id="wr_island", regulates_on="grid"),
            0,
        ),
        "ac_connection": "island",
    }
    validate_live_topology(
        plant={
            "grid_meter": {
                "at_house_connection": True,
                "single_tariff": True,
            }
        },
        batteries=[house, island],
        inverters=[
            normalize_inverter(_hybrid(), 0),
            normalize_inverter(
                _hybrid(id="wr_island", ac_connection="island"), 0
            ),
        ],
        live_battery_ids=["home", "island"],
    )


def test_live_refuse_battery_and_inverter_both_grid():
    with pytest.raises(ValueError, match="mehr als ein geschlossener Regler"):
        validate_live_topology(
            plant={
                "grid_meter": {
                    "at_house_connection": True,
                    "single_tariff": True,
                }
            },
            batteries=[
                {
                    **normalize_battery(_house_bat(), 0),
                    "ac_connection": "grid_tied",
                }
            ],
            inverters=[normalize_inverter(_hybrid(regulates_on="grid"), 0)],
            live_battery_ids=["home"],
        )


def test_resolve_components_still_works_with_regulates_on():
    components = {
        "inverters": [_hybrid()],
        "batteries": [_house_bat(id="bat")],
        "pv_systems": [{"id": "pv", "kwp": 6.0, "inverter_id": "wr_main"}],
    }
    resolved = resolve_components_into_settings(
        {"battery_ids": ["bat"], "pv_system_ids": ["pv"]},
        components,
    )
    assert resolved["_planning_batteries"][0]["regulates_on"] == "grid"


def test_reject_if_needs_topology_migration_hint():
    doc = {
        "batteries": [
            {k: v for k, v in _house_bat().items() if k != "regulates_on"}
        ]
    }
    with pytest.raises(ValueError, match="migrate_topology_once"):
        reject_if_needs_topology_migration(doc)

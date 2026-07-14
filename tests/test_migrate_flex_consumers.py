"""Tests für scripts/migrate_flex_consumers.py (1.95c)."""
from __future__ import annotations

from scripts.migrate_flex_consumers import migrate_prod_consumers


def _legacy_config() -> dict:
    return {
        "flexible_consumers": [
            {
                "id": "waermepumpe",
                "name": "Wärmepumpe",
                "nominal_power_kw": 1.6,
            },
            {
                "id": "eauto",
                "name": "E-Auto",
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "min_on_quarterhours": 1,
            },
        ],
        "appliances": [],
    }


def test_migrate_prod_consumers_moves_legacy_flex_to_profile():
    config, profiles, status = migrate_prod_consumers(
        _legacy_config(),
        {"profiles": [{"id": "example_efh", "consumers": []}]},
    )
    flex_ids = {entry["id"] for entry in config.get("flexible_consumers", [])}
    assert "waermepumpe" not in flex_ids
    assert "eauto" not in flex_ids
    profile = profiles["profiles"][0]
    consumer_ids = {consumer["id"] for consumer in profile["consumers"]}
    assert consumer_ids >= {"wp_heating", "ev"}
    migrated_ids = {row["id"] for row in status}
    assert migrated_ids >= {"wp_heating", "ev"}


def test_migrate_prod_consumers_places_thermal_annual_first():
    config, profiles, _ = migrate_prod_consumers(
        _legacy_config(),
        {"profiles": [{"id": "example_efh", "consumers": []}]},
    )
    consumers = profiles["profiles"][0]["consumers"]
    assert consumers[0]["type"] == "thermal_annual"
    assert consumers[0]["id"] == "wp_heating"


def test_migrate_prod_consumers_unifies_appliances_into_profile():
    config = {
        **_legacy_config(),
        "appliances": [
            {
                "id": "waschmaschine",
                "name": "Waschmaschine",
                "power_source": "manual",
                "default_power_kw": 2.0,
                "default_runtime_h": 2.0,
            }
        ],
    }
    migrated_config, profiles, status = migrate_prod_consumers(
        config,
        {"profiles": [{"id": "example_efh", "consumers": []}]},
    )
    assert "appliances" not in migrated_config
    wm = next(
        consumer
        for consumer in profiles["profiles"][0]["consumers"]
        if consumer["id"] == "waschmaschine"
    )
    assert wm["type"] == "generic"
    assert wm["appliance_recommendation"]["power_source"] == "manual"
    assert any(row.get("status") == "retired-config-block" for row in status)


def test_migrate_prod_consumers_is_idempotent():
    config, profiles, _ = migrate_prod_consumers(
        _legacy_config(),
        {"profiles": [{"id": "example_efh", "consumers": []}]},
    )
    config2, profiles2, status2 = migrate_prod_consumers(config, profiles)
    assert config2.get("flexible_consumers") == config.get("flexible_consumers")
    assert profiles2 == profiles
    assert status2 == []

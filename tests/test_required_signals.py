"""Binding P5a — required-signal kinds and activation."""
from __future__ import annotations

from ehal.ess_fields import ess_field
from ehal.required_signals import (
    activate_required_keys,
    missing_required_keys,
    required_binding_keys,
    required_kinds_for_battery,
)
from house_config.required_signal_activation import (
    activate_battery_required,
    activate_plant_required,
    pack_missing_required,
)
from runtime_store.migration.steps.required_signal_activation import (
    STEP_ID,
    apply,
    detect,
)


def test_battery_control_levels():
    assert required_kinds_for_battery("read_only") == ("sens_ess_soc",)
    assert "set_ess_charge_power_limit" in required_kinds_for_battery("limits_only")
    assert "set_ess_active_power" not in required_kinds_for_battery("limits_only")
    assert "set_ess_active_power" in required_kinds_for_battery("full")


def test_battery_keys_entity_scoped():
    keys = required_binding_keys(
        component_kind="battery", entity_id="house", control="full"
    )
    assert ess_field("house", "sens_ess_soc") in keys
    assert ess_field("house", "set_ess_active_power") in keys


def test_activate_preserves_existing_values():
    bindings = {ess_field("house", "sens_ess_soc"): "Merker_SoC"}
    keys = required_binding_keys(
        component_kind="battery", entity_id="house", control="read_only"
    )
    out = activate_required_keys(bindings, keys)
    assert out[ess_field("house", "sens_ess_soc")] == "Merker_SoC"


def test_activate_battery_required_adds_empty_keys():
    bat = activate_battery_required({"id": "house", "control": "full"})
    assert bat["ehal_bindings"][ess_field("house", "sens_ess_soc")] == ""
    assert bat["ehal_bindings"][ess_field("house", "set_ess_active_power")] == ""


def test_activate_plant_required():
    plant = activate_plant_required({})
    assert plant["ehal_bindings"]["sens_grid_power_active"] == ""
    assert plant["ehal_bindings"]["sens_pv_production_active"] == ""


def test_pack_missing_and_migration_step():
    house = {"plant": {"ehal_bindings": {}}, "profiles": {}}
    components = {
        "batteries": [{"id": "house", "control": "read_only", "ehal_bindings": {}}]
    }
    assert pack_missing_required(house, components) is True
    assert detect(
        {"house_profiles.json": house, "components.json": components}
    ) is True
    result = apply(
        {"house_profiles.json": house, "components.json": components},
        {},
    )
    assert STEP_ID.startswith("dm4.")
    assert "house_profiles.json" in result.changed_files
    assert not missing_required_keys(
        result.docs["components.json"]["batteries"][0]["ehal_bindings"],
        required_binding_keys(
            component_kind="battery", entity_id="house", control="read_only"
        ),
    )
    assert pack_missing_required(
        result.docs["house_profiles.json"],
        result.docs["components.json"],
    ) is False

"""Tests for ehal.profiles — device roles, hardware outlines, Loxone recipes (2.4.g)."""

from __future__ import annotations

import pytest

from ehal.profiles import (
    M1_EHAL_FIELDS,
    field_role_id,
    group_fields_by_role,
    list_device_roles,
    list_hardware_profiles,
    list_loxone_recipes,
    load_device_role,
    load_hardware_profile,
    load_loxone_recipe,
    role_field_labels,
)
from ehal.validate import EhalValidationError


def test_all_device_roles_validate() -> None:
    roles = list_device_roles()
    assert set(roles) >= {"grid", "pv", "ess", "evcs", "consumer", "heatpump"}
    for role_id in roles:
        doc = load_device_role(role_id)
        assert doc["role_id"] == role_id


def test_m1_roles_only_reference_m1_fields() -> None:
    for role_id in ("grid", "pv", "ess", "evcs"):
        doc = load_device_role(role_id)
        assert doc.get("status", "m1") == "m1"
        for item in doc["ehal_fields"]:
            assert item["kind"] != "stub"
            assert item["field"] in M1_EHAL_FIELDS


def test_stub_roles_use_stub_kind() -> None:
    for role_id in ("consumer", "heatpump"):
        doc = load_device_role(role_id)
        assert doc["status"] == "stub"
        assert all(item["kind"] == "stub" for item in doc["ehal_fields"])


def test_all_hardware_profiles_validate() -> None:
    stems = list_hardware_profiles()
    assert "sunspec_inverter_ess.outline" in stems
    assert "huawei_via_loxone.outline" in stems
    for stem in stems:
        doc = load_hardware_profile(stem)
        assert doc["protocol"] in ("sunspec", "proprietary")
        assert doc["status"] in ("outline", "example")
        assert doc["ehal_bindings"]


def test_huawei_outline_maps_control_cmd_to_set_ess_mode() -> None:
    doc = load_hardware_profile("huawei_via_loxone.outline")
    fields = {b["ehal_field"] for b in doc["ehal_bindings"]}
    assert "set_ess_mode" in fields
    assert not any(str(f).startswith("loxone_extra:") for f in fields)
    assert "loxone_extra:target_soc_name" not in fields


def test_all_loxone_recipes_validate() -> None:
    recipes = list_loxone_recipes()
    assert set(recipes) >= {"grid", "pv", "ess", "evcs", "consumer"}
    for role_id in recipes:
        doc = load_loxone_recipe(role_id)
        assert doc["role_id"] == role_id
        assert doc["recommended_markers"]


def test_plant_recipes_align_with_device_roles() -> None:
    for role_id in ("grid", "pv", "ess", "evcs"):
        assert role_id in list_device_roles()
        assert role_id in list_loxone_recipes()
        load_device_role(role_id)
        load_loxone_recipe(role_id)


def test_role_field_labels_cover_m1_mapping_fields() -> None:
    labels = role_field_labels()
    for field in (
        "sens_grid_power_active",
        "sens_pv_production_active",
        "sens_ess_soc",
        "sens_ess_power",
        "sens_evcs_active_power",
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
        "set_ess_mode",
        "set_evcs_max_current",
    ):
        assert field in labels
        assert labels[field]


def test_group_fields_by_role_order() -> None:
    fields = (
        "sens_ess_soc",
        "sens_grid_power_active",
        "set_evcs_max_current",
        "sens_pv_production_active",
    )
    groups = group_fields_by_role(fields)
    assert [g[0] for g in groups] == ["grid", "pv", "ess", "evcs"]
    assert groups[0][1] == ["sens_grid_power_active"]
    assert field_role_id("sens_ess_soc") == "ess"


def test_missing_role_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_device_role("no_such_role")
    with pytest.raises(FileNotFoundError):
        load_loxone_recipe("no_such_role")
    with pytest.raises(FileNotFoundError):
        load_hardware_profile("missing")


def test_invalid_role_document_raises(tmp_path, monkeypatch) -> None:
    import ehal.profiles as profiles

    bad = tmp_path / "grid.json"
    bad.write_text('{"role_id": "grid"}', encoding="utf-8")
    monkeypatch.setattr(profiles, "_ROLES_DIR", tmp_path)
    with pytest.raises(EhalValidationError):
        profiles.load_device_role("grid")

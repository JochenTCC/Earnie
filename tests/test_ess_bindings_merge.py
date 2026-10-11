"""Primary house-battery entity-scoped ESS resolve (no plant-flat aliases)."""
from __future__ import annotations

from ehal.ess_fields import ess_field
from house_config.ess_bindings import (
    entity_scoped_battery_bindings,
    resolve_primary_ess_binding,
)


def test_empty_activation_returns_entity_scoped_qid():
    """Q8: empty Merker on entity-scoped → exchange id, not plant-flat."""
    house_id = "15_kwh_speicher"
    batteries = [
        {
            "id": house_id,
            "type": "house",
            "ehal_bindings": {
                ess_field(house_id, "sens_ess_soc"): "",
                ess_field(house_id, "set_ess_mode"): "",
                ess_field(house_id, "sens_ess_power"): "",
            },
        },
    ]
    assert resolve_primary_ess_binding("sens_ess_soc", batteries=batteries) == ess_field(
        house_id, "sens_ess_soc"
    )
    assert resolve_primary_ess_binding("set_ess_mode", batteries=batteries) == ess_field(
        house_id, "set_ess_mode"
    )


def test_primary_resolve_prefers_house_when_powerstations_listed_first():
    """NAS-style: virtual/physical PS before house must not win primary SoC."""
    house_id = "15_kwh_speicher"
    batteries = [
        {"id": "virtual_gs", "type": "powerstation", "ehal_bindings": {}},
        {
            "id": "ecoflow_delta_3",
            "type": "powerstation",
            "backing": "physical",
            "ehal_bindings": {
                ess_field("ecoflow_delta_3", "sens_ess_soc"): "PS_SoC",
            },
        },
        {
            "id": house_id,
            "type": "house",
            "ehal_bindings": {
                ess_field(house_id, "sens_ess_soc"): "Earnie_Batterie_SoC",
                ess_field(house_id, "sens_ess_power"): "Earnie_Batterie_Leistung",
            },
        },
    ]
    assert (
        resolve_primary_ess_binding("sens_ess_soc", batteries=batteries)
        == "Earnie_Batterie_SoC"
    )
    assert (
        resolve_primary_ess_binding("sens_ess_power", batteries=batteries)
        == "Earnie_Batterie_Leistung"
    )
    all_b = entity_scoped_battery_bindings(batteries)
    assert all_b[ess_field(house_id, "sens_ess_soc")] == "Earnie_Batterie_SoC"
    assert "sens_ess_soc" not in all_b
    # Physical powerstations keep their entity-scoped key (virtual_gs is filtered out).
    assert all_b[ess_field("ecoflow_delta_3", "sens_ess_soc")] == "PS_SoC"


def test_entity_scoped_bindings_no_flat_aliases():
    house_id = "house_a"
    batteries = [
        {
            "id": "ps_only",
            "type": "powerstation",
            "ehal_bindings": {
                ess_field("ps_only", "sens_ess_soc"): "PS_SoC",
            },
        },
        {
            "id": house_id,
            "type": "house",
            "ehal_bindings": {
                ess_field(house_id, "sens_ess_soc"): "House_SoC",
            },
        },
    ]
    assert resolve_primary_ess_binding("sens_ess_soc", batteries=batteries) == "House_SoC"
    out = entity_scoped_battery_bindings(batteries)
    assert out[ess_field(house_id, "sens_ess_soc")] == "House_SoC"
    assert "sens_ess_soc" not in out

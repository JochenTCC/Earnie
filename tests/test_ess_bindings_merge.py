"""Pattern-B ESS merge → plant-flat aliases (2.7.c / house vs powerstation)."""
from __future__ import annotations

from ehal.ess_fields import ess_field
from house_config.ess_bindings import merge_ess_bindings_into_plant


def test_flat_aliases_prefer_house_when_powerstations_listed_first():
    """NAS-style: virtual/physical PS before house must not blank plant SoC."""
    house_id = "15_kwh_speicher"
    batteries = [
        {"id": "virtual_gs", "type": "powerstation", "ehal_bindings": {}},
        {
            "id": "ecoflow_delta_3",
            "type": "powerstation",
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
    merged = merge_ess_bindings_into_plant({}, batteries)
    assert merged["sens_ess_soc"] == "Earnie_Batterie_SoC"
    assert merged["sens_ess_power"] == "Earnie_Batterie_Leistung"
    assert merged[ess_field("ecoflow_delta_3", "sens_ess_soc")] == "PS_SoC"
    # Powerstation SoC must not become the plant-flat alias.
    assert merged["sens_ess_soc"] != "PS_SoC"


def test_explicit_battery_ids_still_prefer_house_among_selected():
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
    merged = merge_ess_bindings_into_plant(
        {},
        batteries,
        battery_ids=["ps_only", house_id],
    )
    assert merged["sens_ess_soc"] == "House_SoC"

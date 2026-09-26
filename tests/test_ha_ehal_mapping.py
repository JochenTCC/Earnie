"""Regression tests for HA suggest-and-confirm heuristic (2.6.b / 2.6.e)."""
from __future__ import annotations

import pytest

from integrations.ha_adapter import MAPPABLE_DOMAINS, entity_domain
from integrations.ha_ehal_mapping import (
    heuristic_propose,
    resolve_field_select_default,
)
from house_sim.archetype import load_archetype

_ARCHETYPES = ("evcc_en", "fronius_de", "huawei_en", "sma_keba")
_DISTRACTORS = frozenset(
    {
        "sensor.inverter_active_power",
        "sensor.sn_3012345678_grid_power",
        "sensor.solarnet_leistung_verbrauch",
    }
)


def _scan_rows_from_fixture(entities: list[dict]) -> list[dict]:
    """Shape fixture HA states like HaAdapter.list_mappable_entities()."""
    rows: list[dict] = []
    for item in entities:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id") or "").strip()
        domain = entity_domain(entity_id)
        if domain not in MAPPABLE_DOMAINS:
            continue
        attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        rows.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "state": item.get("state"),
                "unit": attrs.get("unit_of_measurement"),
                "device_class": attrs.get("device_class"),
                "state_class": attrs.get("state_class"),
                "friendly_name": attrs.get("friendly_name") or entity_id,
            }
        )
    return rows


def test_evcc_en_empty_map_matches_golden():
    pkg = load_archetype("evcc_en")
    rows = _scan_rows_from_fixture(pkg.entities)
    proposals = heuristic_propose(rows)
    proposed = {field: entry["entity_id"] for field, entry in proposals.items()}
    assert proposed == pkg.ehal_entities
    assert "sensor.house_sim_buffer_temp" not in proposed.values()
    assert all(not eid.startswith("switch.") for eid in proposed.values())


@pytest.mark.parametrize("name", _ARCHETYPES)
def test_archetype_propose_subset_of_golden(name: str):
    pkg = load_archetype(name)
    rows = _scan_rows_from_fixture(pkg.entities)
    proposals = heuristic_propose(rows)
    golden = pkg.ehal_entities
    for field, entry in proposals.items():
        eid = entry["entity_id"]
        assert eid in golden.values(), f"{name}: {field} → {eid} not in golden"
        if field in golden:
            assert eid == golden[field], f"{name}: {field} wrong (got {eid})"


@pytest.mark.parametrize("name", _ARCHETYPES)
def test_archetype_distractors_never_proposed(name: str):
    pkg = load_archetype(name)
    rows = _scan_rows_from_fixture(pkg.entities)
    proposals = heuristic_propose(rows)
    proposed_ids = {entry["entity_id"] for entry in proposals.values()}
    assert proposed_ids.isdisjoint(_DISTRACTORS)


def test_vendor_unambiguous_hits():
    """Backlog 2.6.e vocab examples that must be proposed when present."""
    huawei = load_archetype("huawei_en")
    h_prop = {
        f: e["entity_id"]
        for f, e in heuristic_propose(_scan_rows_from_fixture(huawei.entities)).items()
    }
    assert h_prop.get("sens_ess_soc") == "sensor.batteries_state_of_capacity"
    assert h_prop.get("sens_grid_power_active") == "sensor.power_meter_active_power"
    assert h_prop.get("sens_evcs_active_power") == "sensor.goe_204711_nrg_11"

    sma = load_archetype("sma_keba")
    s_prop = {
        f: e["entity_id"]
        for f, e in heuristic_propose(_scan_rows_from_fixture(sma.entities)).items()
    }
    assert s_prop.get("sens_evcs_active_power") == "sensor.keba_p30_charging_power"
    assert (
        s_prop.get("sens_grid_energy_import")
        == "sensor.sn_3012345678_metering_total_absorbed"
    )
    assert (
        s_prop.get("sens_grid_energy_export")
        == "sensor.sn_3012345678_metering_total_yield"
    )

    fronius = load_archetype("fronius_de")
    f_prop = {
        f: e["entity_id"]
        for f, e in heuristic_propose(_scan_rows_from_fixture(fronius.entities)).items()
    }
    assert f_prop.get("sens_grid_power_active") == "sensor.solarnet_leistung_netz"
    assert (
        f_prop.get("sens_ess_soc")
        == "sensor.byd_battery_box_premium_hv_ladezustand"
    )
    assert (
        f_prop.get("sens_pv_production_active")
        == "sensor.solarnet_leistung_photovoltaik"
    )


def test_token_boundary_solar_vs_solarnet():
    rows = [
        {
            "entity_id": "sensor.solarnet_leistung_netz",
            "domain": "sensor",
            "unit": "W",
            "device_class": "power",
            "friendly_name": "SolarNet Leistung Netz",
        },
        {
            "entity_id": "sensor.solarnet_leistung_photovoltaik",
            "domain": "sensor",
            "unit": "W",
            "device_class": "power",
            "friendly_name": "SolarNet Leistung Photovoltaik",
        },
    ]
    proposals = heuristic_propose(rows)
    assert (
        proposals.get("sens_pv_production_active", {}).get("entity_id")
        == "sensor.solarnet_leistung_photovoltaik"
    )
    assert (
        proposals.get("sens_grid_power_active", {}).get("entity_id")
        == "sensor.solarnet_leistung_netz"
    )


def test_token_boundary_charge_power_vs_discharge_power():
    rows = [
        {
            "entity_id": "sensor.batteries_charge_discharge_power",
            "domain": "sensor",
            "unit": "W",
            "device_class": "power",
            "friendly_name": "Batteries Charge/Discharge power",
        },
        {
            "entity_id": "sensor.goe_1_nrg_11",
            "domain": "sensor",
            "unit": "W",
            "device_class": "power",
            "friendly_name": "go-e nrg 11",
        },
    ]
    proposals = heuristic_propose(rows)
    assert (
        proposals.get("sens_ess_power", {}).get("entity_id")
        == "sensor.batteries_charge_discharge_power"
    )
    assert proposals.get("sens_evcs_active_power", {}).get("entity_id") == "sensor.goe_1_nrg_11"


def test_buffer_temp_not_proposed():
    pkg = load_archetype("evcc_en")
    rows = _scan_rows_from_fixture(pkg.entities)
    proposals = heuristic_propose(rows)
    for entry in proposals.values():
        assert entry["entity_id"] != "sensor.house_sim_buffer_temp"


def test_switch_not_in_mappable_scan_input():
    pkg = load_archetype("evcc_en")
    rows = _scan_rows_from_fixture(pkg.entities)
    ids = {row["entity_id"] for row in rows}
    assert "switch.evcc_loadpoint_1_enable" not in ids


def test_resolve_field_select_default_keeps_existing():
    assert (
        resolve_field_select_default("sensor.saved_grid", "sensor.evcc_grid_power")
        == "sensor.saved_grid"
    )
    assert (
        resolve_field_select_default("", "sensor.evcc_grid_power")
        == "sensor.evcc_grid_power"
    )
    assert resolve_field_select_default("", "") == ""


def test_ambiguous_name_left_empty():
    rows = [
        {
            "entity_id": "sensor.misc_value",
            "domain": "sensor",
            "unit": "W",
            "device_class": "power",
            "friendly_name": "Misc Value",
        }
    ]
    proposals = heuristic_propose(rows)
    assert proposals == {}

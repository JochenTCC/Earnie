"""Regression tests for HA suggest-and-confirm heuristic (2.6.b)."""
from __future__ import annotations

from integrations.ha_adapter import MAPPABLE_DOMAINS, entity_domain
from integrations.ha_ehal_mapping import (
    heuristic_propose,
    resolve_field_select_default,
)
from house_sim.archetype import load_archetype


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

"""Tests for Loxone EFM / Zähler → Hausprofil proposals (2.4.l)."""
from __future__ import annotations

import json
from pathlib import Path

from integrations.loxone_efm_meters import (
    ROLE_BATTERY,
    ROLE_CONSUMER,
    ROLE_GRID,
    ROLE_PV,
    ROLE_RESIDUAL,
    apply_consumer_imports,
    apply_plant_power_suggestions,
    csv_stem_from_name,
    extract_efm_meters,
    propose_consumer_imports,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "loxapp3_efm_meters.json"


def _doc() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_extract_efm_meters_roles_and_rest():
    rows = extract_efm_meters(_doc())
    by_name = {r.name: r for r in rows}
    assert by_name["Zähler Netz"].role == ROLE_GRID
    assert by_name["Zähler Netz"].plant_field == "sens_grid_power_active"
    assert by_name["Zähler PV-Anlage"].role == ROLE_PV
    assert by_name["Zähler Batterie"].role == ROLE_BATTERY
    assert by_name["Zähler Wärmepumpe"].role == ROLE_CONSUMER
    assert by_name["Zähler Kochen"].role == ROLE_CONSUMER
    assert by_name["Zähler TV"].role == ROLE_CONSUMER
    assert by_name["Rest"].role == ROLE_RESIDUAL
    assert by_name["Rest"].node_type in {"Load", "Rest"}
    assert "Haushaltsgeräte" not in by_name
    assert by_name["Zähler Wärmepumpe"].power_address == "Zähler Wärmepumpe"


def test_propose_create_match_and_skip_residual():
    candidates = extract_efm_meters(_doc())
    existing = [{"id": "zaehler_waermepumpe", "label": "Zähler Wärmepumpe", "type": "generic"}]
    proposals = propose_consumer_imports(candidates, existing)
    by_name = {p.name: p for p in proposals}
    assert by_name["Zähler Wärmepumpe"].action == "match"
    assert by_name["Zähler Kochen"].action == "create"
    assert by_name["Zähler Kochen"].consumer_id
    assert by_name["Rest"].action == "skip_residual"
    assert by_name["Zähler Netz"].action == "skip_plant"
    assert by_name["Zähler TV"].csv_stem == csv_stem_from_name("Zähler TV")


def test_apply_consumer_imports_sets_flex_power_only():
    house = {
        "plant": {"ehal_bindings": {}},
        "profiles": {"live": {"id": "live", "consumers": []}},
    }
    selected = [
        {
            "action": "create",
            "consumer_id": "zaehler_kochen",
            "label": "Zähler Kochen",
            "power_address": "Zähler Kochen",
            "bind_power": True,
        }
    ]
    out = apply_consumer_imports(house, profile_id="live", selected=selected)
    cons = out["profiles"]["live"]["consumers"]
    assert len(cons) == 1
    assert cons[0]["earnie_role"] == "known"
    assert cons[0]["ehal_bindings"]["flex.power_name"] == "Zähler Kochen"
    assert "flex.enable_name" not in cons[0]["ehal_bindings"]
    assert "flex.power_setpoint_name" not in cons[0]["ehal_bindings"]


def test_apply_plant_power_suggestions():
    house = {"plant": {"ehal_bindings": {"sens_ess_soc": "SoC"}}, "profiles": {}}
    selected = [
        {
            "action": "skip_plant",
            "plant_field": "sens_grid_power_active",
            "power_address": "Zähler Netz",
            "bind_plant": True,
        }
    ]
    out = apply_plant_power_suggestions(house, selected=selected)
    bindings = out["plant"]["ehal_bindings"]
    assert bindings["sens_grid_power_active"] == "Zähler Netz"
    assert bindings["sens_ess_soc"] == "SoC"

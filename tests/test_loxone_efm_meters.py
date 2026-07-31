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
    meter_display_name,
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


def test_meter_display_name_strips_zaehler():
    assert meter_display_name("Zähler Kochen") == "Kochen"
    assert meter_display_name("Zaehler TV") == "TV"
    assert meter_display_name("Waschmaschine") == "Waschmaschine"
    assert csv_stem_from_name("Zähler TV") == "tv"


def test_meter_display_name_strips_verbraucher_n():
    assert meter_display_name("Verbraucher 2: E-Auto") == "E-Auto"
    assert meter_display_name("Verbraucher 8:smart") == "smart"
    assert csv_stem_from_name("Verbraucher 2: E-Auto") == "e_auto"


def test_propose_create_match_and_skip_residual():
    candidates = extract_efm_meters(_doc())
    existing = [{"id": "waermepumpe", "label": "Wärmepumpe", "type": "generic"}]
    proposals = propose_consumer_imports(candidates, existing)
    by_name = {p.name: p for p in proposals}
    assert by_name["Zähler Wärmepumpe"].action == "match"
    assert by_name["Zähler Wärmepumpe"].consumer_id == "waermepumpe"
    assert by_name["Zähler Kochen"].action == "create"
    assert by_name["Zähler Kochen"].consumer_id == "kochen"
    assert by_name["Zähler Kochen"].label == "Kochen"
    assert by_name["Rest"].action == "skip_residual"
    assert by_name["Zähler Netz"].action == "skip_plant"
    assert by_name["Zähler TV"].csv_stem == csv_stem_from_name("Zähler TV")


def test_propose_matches_ev_wallbox_alias():
    from integrations.loxone_efm_meters import EfmMeterCandidate

    wallbox = EfmMeterCandidate(
        name="Zähler Wallbox",
        uuid="u-wb",
        role=ROLE_CONSUMER,
        power_address="Zähler Wallbox",
        csv_stem="wallbox",
    )
    existing = [{"id": "e_auto", "label": "E-Auto", "type": "ev"}]
    proposals = propose_consumer_imports([wallbox], existing)
    assert proposals[0].action == "match"
    assert proposals[0].consumer_id == "e_auto"


def test_propose_matches_zaehler_smart_onto_ev():
    from integrations.loxone_efm_meters import EfmMeterCandidate

    smart = EfmMeterCandidate(
        name="Zähler smart",
        uuid="u-sm",
        role=ROLE_CONSUMER,
        power_address="Zähler smart",
        csv_stem="smart",
    )
    existing = [{"id": "e_auto", "label": "E-Auto", "type": "ev"}]
    proposals = propose_consumer_imports([smart], existing)
    assert proposals[0].action == "match"
    assert proposals[0].consumer_id == "e_auto"
    assert proposals[0].label == "smart"


def test_propose_merges_verbraucher_e_auto_and_smart_in_batch():
    from integrations.loxone_efm_meters import EfmMeterCandidate

    e_auto = EfmMeterCandidate(
        name="Verbraucher 2: E-Auto",
        uuid="u2",
        role=ROLE_CONSUMER,
        power_address="Verbraucher 2: E-Auto",
        csv_stem="e_auto",
    )
    smart = EfmMeterCandidate(
        name="Verbraucher 8:smart",
        uuid="u8",
        role=ROLE_CONSUMER,
        power_address="Verbraucher 8:smart",
        csv_stem="smart",
    )
    proposals = propose_consumer_imports([e_auto, smart], [])
    by_name = {p.name: p for p in proposals}
    assert by_name["Verbraucher 2: E-Auto"].action == "create"
    assert by_name["Verbraucher 2: E-Auto"].consumer_id == "e_auto"
    assert by_name["Verbraucher 8:smart"].action == "match"
    assert by_name["Verbraucher 8:smart"].consumer_id == "e_auto"
    assert by_name["Verbraucher 8:smart"].label == "smart"


def test_apply_match_prefers_smart_label_over_e_auto():
    house = {
        "plant": {"ehal_bindings": {}},
        "profiles": {
            "live": {
                "id": "live",
                "consumers": [
                    {
                        "id": "e_auto",
                        "label": "E-Auto",
                        "type": "ev",
                        "ehal_bindings": {},
                    }
                ],
            }
        },
    }
    selected = [
        {
            "action": "match",
            "consumer_id": "e_auto",
            "name": "Zähler smart",
            "label": "smart",
            "power_address": "Zähler smart",
            "bind_power": True,
        }
    ]
    out = apply_consumer_imports(house, profile_id="live", selected=selected)
    cons = out["profiles"]["live"]["consumers"][0]
    assert cons["id"] == "e_auto"
    assert cons["label"] == "smart"
    assert cons["ehal_bindings"]["sens_evcs_active_power"] == "Zähler smart"


def test_apply_consumer_imports_sets_flex_power_only():
    house = {
        "plant": {"ehal_bindings": {}},
        "profiles": {"live": {"id": "live", "consumers": []}},
    }
    selected = [
        {
            "action": "create",
            "consumer_id": "kochen",
            "label": "Kochen",
            "power_address": "Zähler Kochen",
            "bind_power": True,
        }
    ]
    out = apply_consumer_imports(house, profile_id="live", selected=selected)
    cons = out["profiles"]["live"]["consumers"]
    assert len(cons) == 1
    assert cons[0]["id"] == "kochen"
    assert cons[0]["label"] == "Kochen"
    assert cons[0]["earnie_role"] == "known"
    assert cons[0]["ehal_bindings"]["flex.kochen.sens_power_act"] == "Zähler Kochen"
    assert "flex.enable_name" not in cons[0]["ehal_bindings"]
    assert "flex.power_setpoint_name" not in cons[0]["ehal_bindings"]
    assert "flex.kochen.set_enable" not in cons[0]["ehal_bindings"]
    assert "flex.kochen.set_power_setpoint" not in cons[0]["ehal_bindings"]


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

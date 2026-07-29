"""Tests for Loxone EHAL mapping helpers + Ollama parse (2.4.f)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from integrations.loxone_ehal_mapping import (
    ehal_mapping_to_loxone_blocks,
    heuristic_propose,
    merge_loxone_blocks,
    parse_ollama_proposals,
    propose_with_ollama,
)


def test_ehal_mapping_to_loxone_blocks():
    blocks = ehal_mapping_to_loxone_blocks(
        {
            "sens_ess_soc": "Batterie_SoC",
            "sens_pv_production_active": "PV_Leistung_kW",
            "sens_evcs_active_power": "ignored-no-block-key",
            "set_ess_mode": "Steuerbefehl",
        },
        extras={"control_cmd_name": ""},
    )
    assert blocks == {
        "soc_name": "Batterie_SoC",
        "pv_power_name": "PV_Leistung_kW",
        "control_cmd_name": "Steuerbefehl",
    }


def test_ehal_mapping_dual_read_legacy_keys():
    blocks = ehal_mapping_to_loxone_blocks(
        {
            "ess_soc": "Batterie_SoC",
            "grid_power_active": "Netz",
        }
    )
    assert blocks == {
        "soc_name": "Batterie_SoC",
        "grid_power_name": "Netz",
    }


def test_merge_preserves_unrelated_keys():
    merged = merge_loxone_blocks(
        {"soc_name": "old", "grid_power_name": "live_grid"},
        {"soc_name": "new", "pv_power_name": "PV"},
    )
    assert merged["soc_name"] == "new"
    assert merged["pv_power_name"] == "PV"
    assert merged["grid_power_name"] == "live_grid"


def test_heuristic_propose_energy_names():
    names = [
        "PV_Leistung_kW",
        "Netz_Leistung",
        "Batterie_SoC",
        "Batterie_Leistung",
        "Wohnzimmer Licht",
    ]
    proposals = heuristic_propose(names)
    assert proposals["sens_pv_production_active"]["marker_name"] == "PV_Leistung_kW"
    assert proposals["sens_grid_power_active"]["marker_name"] == "Netz_Leistung"
    assert proposals["sens_ess_soc"]["marker_name"] == "Batterie_SoC"
    assert 0.35 <= proposals["sens_ess_soc"]["confidence"] <= 0.75


def test_parse_ollama_proposals_filters_unknown():
    content = json_blob(
        {
            "mappings": [
                {
                    "field": "sens_pv_production_active",
                    "marker_name": "PV_Leistung_kW",
                    "confidence": 0.9,
                },
                {
                    "field": "sens_ess_soc",
                    "marker_name": "not-in-list",
                    "confidence": 0.9,
                },
            ]
        }
    )
    out = parse_ollama_proposals(
        content,
        allowed_names={"PV_Leistung_kW"},
        fields=("sens_pv_production_active", "sens_ess_soc"),
    )
    assert list(out) == ["sens_pv_production_active"]
    assert out["sens_pv_production_active"]["source"] == "ollama"


@patch("integrations.loxone_ehal_mapping.requests.post")
def test_propose_with_ollama_ok(post_mock):
    post_mock.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "message": {
                "content": json_blob(
                    {
                        "mappings": [
                            {
                                "field": "sens_grid_power_active",
                                "marker_name": "Netz_Leistung",
                                "confidence": 0.8,
                            }
                        ]
                    }
                )
            }
        },
        raise_for_status=lambda: None,
    )
    out = propose_with_ollama(["Netz_Leistung", "Other"])
    assert out["sens_grid_power_active"]["marker_name"] == "Netz_Leistung"


@patch("integrations.loxone_ehal_mapping.requests.post")
def test_propose_with_ollama_degrades(post_mock):
    post_mock.side_effect = OSError("offline")
    assert propose_with_ollama(["Netz_Leistung"]) == {}


def json_blob(obj: dict) -> str:
    import json

    return json.dumps(obj)

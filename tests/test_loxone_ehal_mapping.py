"""Tests for Loxone EHAL mapping helpers + Ollama parse (2.4.f)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from integrations.loxone_ehal_mapping import (
    heuristic_propose,
    parse_ollama_proposals,
    propose_with_ollama,
)


def test_heuristic_propose_energy_names():
    names = [
        "PV_Leistung_kW",
        "Netz_Leistung",
        "Batterie_SoC",
        "Batterie_Leistung",
        "Wohnzimmer Licht",
    ]
    proposals = heuristic_propose(names)
    assert proposals["sens_inv_power_pv"]["marker_name"] == "PV_Leistung_kW"
    assert proposals["sens_grid_power_active"]["marker_name"] == "Netz_Leistung"
    assert proposals["sens_ess_soc"]["marker_name"] == "Batterie_SoC"
    assert 0.35 <= proposals["sens_ess_soc"]["confidence"] <= 0.75


def test_heuristic_propose_soc_min_immediate_and_absent():
    proposals = heuristic_propose(
        ["Earnie_Abwesend", "Earnie_EAuto_SOCMinSofort"],
        fields=("sens_absent_mode", "get_evcs_soc_min_immediate"),
    )
    assert proposals["sens_absent_mode"]["marker_name"] == "Earnie_Abwesend"
    assert (
        proposals["get_evcs_soc_min_immediate"]["marker_name"]
        == "Earnie_EAuto_SOCMinSofort"
    )


def test_heuristic_propose_skips_source_select():
    """Plant Quellenwahl stays unbound until the operator maps it (standby_backup)."""
    proposals = heuristic_propose(
        ["Earnie_Speicher_Quellenwahl", "Delta3_Grid_ByPass", "Netz_Leistung"]
    )
    assert "set_ess_source_select" not in proposals


def test_heuristic_propose_grid_export_power_limit():
    proposals = heuristic_propose(
        ["Earnie_Einspeisegrenze", "Netz_Leistung"],
        fields=("set_grid_export_power_limit", "sens_grid_power_active"),
    )
    assert (
        proposals["set_grid_export_power_limit"]["marker_name"]
        == "Earnie_Einspeisegrenze"
    )


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

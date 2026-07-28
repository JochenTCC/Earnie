"""Tests for LoxAPP3 normalize / multi-source structure compare (2.4.f)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.loxone_structure import (
    SOURCE_HTTP_PROBE,
    SOURCE_LOXAPP3,
    SOURCE_MCP17,
    SOURCE_UNION,
    LoxoneStructureError,
    normalize_loxapp3,
    probe_configured_names,
    probe_mcp17,
    scan_structure,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "loxapp3_minimal.json"


def test_normalize_loxapp3_flattens_controls():
    doc = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    items = normalize_loxapp3(doc)
    names = [row.name for row in items]
    assert "PV_Leistung_kW" in names
    assert "Netz_Leistung" in names
    pv = next(row for row in items if row.name == "PV_Leistung_kW")
    assert pv.type == "InfoOnlyAnalog"
    assert pv.room == "Energie"
    assert pv.category == "Status"


def test_normalize_loxapp3_rejects_bad_root():
    with pytest.raises(LoxoneStructureError):
        normalize_loxapp3({"controls": []})  # type: ignore[arg-type]


@patch("integrations.loxone_structure.requests.post")
@patch("integrations.loxone_structure.requests.get")
def test_scan_structure_runs_all_variants(get_mock, post_mock):
    doc = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    get_response = MagicMock()
    get_response.status_code = 200
    get_response.json.return_value = doc
    get_mock.return_value = get_response
    post_response = MagicMock()
    post_response.status_code = 200
    post_response.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "weather_forecast"}]},
    }
    post_mock.return_value = post_response

    result = scan_structure(
        host="192.168.1.10",
        username="user",
        password="pass",
        configured_names=["PV_Leistung_kW", "missing"],
        mcp_base_url="http://127.0.0.1:9000",
        fetch_raw=lambda name: 1.0 if name == "PV_Leistung_kW" else None,
    )
    sources = [v.source for v in result.variants]
    assert sources == [SOURCE_LOXAPP3, SOURCE_HTTP_PROBE, SOURCE_MCP17]
    assert result.variant(SOURCE_LOXAPP3).ok
    assert result.variant(SOURCE_HTTP_PROBE).ok
    assert result.variant(SOURCE_MCP17).mcp_tools == ["weather_forecast"]
    union_names = {item.name for item in result.mapping_items(use_source=SOURCE_UNION)}
    assert "PV_Leistung_kW" in union_names
    assert "Netz_Leistung" in union_names
    rows = result.comparison_rows()
    assert len(rows) == 3


@patch("integrations.loxone_structure.requests.get")
def test_scan_structure_records_loxapp3_failure_still_runs_others(get_mock):
    get_mock.side_effect = requests.ConnectionError("down")
    result = scan_structure(
        host="192.168.1.10",
        username="user",
        password="pass",
        configured_names=["PV_Leistung_kW"],
        fetch_raw=lambda name: 1.0 if name == "PV_Leistung_kW" else None,
        mcp_base_url="",
    )
    assert not result.variant(SOURCE_LOXAPP3).ok
    assert result.variant(SOURCE_HTTP_PROBE).ok
    assert result.variant(SOURCE_MCP17).skipped
    assert [item.name for item in result.mapping_items()] == ["PV_Leistung_kW"]


def test_probe_configured_names():
    result = probe_configured_names(
        ["A", "B"],
        fetch_raw=lambda name: 0.0 if name == "A" else None,
    )
    assert result.source == SOURCE_HTTP_PROBE
    assert [row.name for row in result.items] == ["A"]
    assert any("B" in err for err in result.errors)


@patch("integrations.loxone_structure.requests.post")
def test_probe_mcp17_tools_without_structure(post_mock):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "weather_forecast"}]},
    }
    post_mock.return_value = response
    result = probe_mcp17("http://127.0.0.1:8080")
    assert result.source == SOURCE_MCP17
    assert result.mcp_tools == ["weather_forecast"]
    assert result.items == []
    assert result.errors


@patch("integrations.loxone_structure.requests.get")
def test_scan_structure_can_restrict_sources(get_mock):
    get_mock.side_effect = requests.ConnectionError("down")
    result = scan_structure(
        host="x",
        username="u",
        password="p",
        sources=(SOURCE_LOXAPP3,),
    )
    assert [v.source for v in result.variants] == [SOURCE_LOXAPP3]
    assert result.mapping_items() == []

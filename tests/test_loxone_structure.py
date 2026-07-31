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
    _extract_controls,
    normalize_loxapp3,
    probe_http_markers,
    probe_mcp17,
    scan_structure,
)
from integrations.loxone_mcp_oauth import McpOAuthError

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


@patch("integrations.loxone_structure.obtain_access_token")
@patch("integrations.loxone_structure.requests.post")
@patch("integrations.loxone_structure.requests.get")
@patch("integrations.loxone_greenfield_import.requests.get")
def test_scan_structure_runs_all_variants(probe_get, get_mock, post_mock, token_mock):
    doc = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    get_response = MagicMock()
    get_response.status_code = 200
    get_response.json.return_value = doc
    get_mock.return_value = get_response
    token_mock.return_value = "token-123"
    post_response = MagicMock()
    post_response.status_code = 200
    post_response.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "weather_forecast"}]},
    }
    post_mock.return_value = post_response

    def _probe_side_effect(url, auth=None, timeout=5.0):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"{}"
        name = url.rsplit("/", 1)[-1]
        if name in {"PV_Leistung_kW", "Earnie_Waermepumpe_Freigabe"}:
            resp.json.return_value = {"LL": {"Code": "200", "value": "1"}}
        elif "Earnie_" in name:
            resp.json.return_value = {"LL": {"Code": "403", "value": ""}}
        else:
            resp.status_code = 404
            resp.json.return_value = {"LL": {"Code": "404", "value": ""}}
        return resp

    probe_get.side_effect = _probe_side_effect

    result = scan_structure(
        host="192.168.1.10",
        username="user",
        password="pass",
        configured_names=["PV_Leistung_kW", "missing"],
        mcp_base_url="http://127.0.0.1:9000",
    )
    sources = [v.source for v in result.variants]
    assert sources == [SOURCE_LOXAPP3, SOURCE_HTTP_PROBE, SOURCE_MCP17]
    assert result.variant(SOURCE_LOXAPP3).ok
    assert result.variant(SOURCE_HTTP_PROBE).ok
    assert "Earnie_Waermepumpe_Freigabe" in {i.name for i in result.variant(SOURCE_HTTP_PROBE).items}
    assert result.variant(SOURCE_MCP17).mcp_tools == ["weather_forecast"]
    post_kwargs = post_mock.call_args.kwargs
    assert post_kwargs["headers"]["Authorization"] == "Bearer token-123"
    union_names = {item.name for item in result.mapping_items(use_source=SOURCE_UNION)}
    assert "PV_Leistung_kW" in union_names
    assert "Netz_Leistung" in union_names
    assert "Earnie_Waermepumpe_Freigabe" in union_names
    rows = result.comparison_rows()
    assert len(rows) == 3


@patch("integrations.loxone_greenfield_import.requests.get")
@patch("integrations.loxone_structure.requests.get")
def test_scan_structure_records_loxapp3_failure_still_runs_probe_and_mcp(
    get_mock, probe_get
):
    get_mock.side_effect = requests.ConnectionError("down")

    def _probe_side_effect(url, auth=None, timeout=5.0):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"{}"
        resp.json.return_value = {"LL": {"Code": "403", "value": ""}}
        return resp

    probe_get.side_effect = _probe_side_effect
    result = scan_structure(
        host="192.168.1.10",
        username="user",
        password="pass",
        configured_names=["PV_Leistung_kW"],
        mcp_base_url="",
    )
    assert not result.variant(SOURCE_LOXAPP3).ok
    assert result.variant(SOURCE_HTTP_PROBE).ok
    assert result.variant(SOURCE_MCP17).skipped
    assert "PV_Leistung_kW" in {i.name for i in result.mapping_items()}


@patch("integrations.loxone_greenfield_import.requests.get")
def test_probe_http_markers_403_counts_as_present(probe_get):
    def _probe_side_effect(url, auth=None, timeout=5.0):
        resp = MagicMock()
        resp.content = b"{}"
        if "missing" in url:
            resp.status_code = 404
            resp.json.return_value = {"LL": {"Code": "404", "value": ""}}
        else:
            resp.status_code = 200
            resp.json.return_value = {"LL": {"Code": "403", "value": ""}}
        return resp

    probe_get.side_effect = _probe_side_effect
    result = probe_http_markers(
        host="192.168.1.10",
        username="u",
        password="p",
        configured_names=["Earnie_Waermepumpe_Freigabe", "missing_marker"],
    )
    assert result.source == SOURCE_HTTP_PROBE
    assert result.ok
    names = {i.name for i in result.items}
    assert "Earnie_Waermepumpe_Freigabe" in names
    assert "missing_marker" not in names
    assert any("missing" in err for err in result.errors)


@patch("integrations.loxone_structure.obtain_access_token")
@patch("integrations.loxone_structure.requests.post")
def test_probe_mcp17_tools_without_structure(post_mock, token_mock):
    token_mock.return_value = "oauth-token"
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = ValueError("SSE")
    response.text = (
        "data: \n"
        "id: 0/0\n"
        "retry: 3000\n\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"weather_forecast"}]}}\n\n'
    )
    post_mock.return_value = response
    result = probe_mcp17(
        "http://127.0.0.1:8080", username="u", password="p"
    )
    assert result.source == SOURCE_MCP17
    assert result.mcp_tools == ["weather_forecast"]
    assert result.items == []
    assert result.errors
    assert (
        post_mock.call_args.kwargs["headers"]["Authorization"]
        == "Bearer oauth-token"
    )


@patch("integrations.loxone_structure.obtain_access_token")
@patch("integrations.loxone_structure.requests.post")
@patch("integrations.loxone_structure.requests.get")
def test_probe_mcp17_resolves_connect_then_posts_with_auth(
    get_mock, post_mock, token_mock
):
    get_response = MagicMock()
    get_response.status_code = 307
    get_response.headers = {
        "Location": "https://relay.dyndns.loxonecloud.com:41234/mcp"
    }
    get_mock.return_value = get_response
    token_mock.return_value = "oauth-token"
    post_response = MagicMock()
    post_response.status_code = 200
    post_response.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "control_find"}]},
    }
    post_mock.return_value = post_response

    result = probe_mcp17(
        "https://connect.loxonecloud.com/504F94A1137C/mcp",
        username="admin",
        password="secret",
    )
    assert result.mcp_tools == ["control_find"]
    get_mock.assert_called_once()
    assert get_mock.call_args.kwargs.get("allow_redirects") is False
    assert get_mock.call_args.kwargs.get("auth") is None
    assert "connect.loxonecloud.com" in get_mock.call_args.args[0]
    token_mock.assert_called_once()
    assert post_mock.call_args.args[0] == (
        "https://relay.dyndns.loxonecloud.com:41234/mcp"
    )
    assert (
        post_mock.call_args.kwargs["headers"]["Authorization"]
        == "Bearer oauth-token"
    )


@patch("integrations.loxone_structure.obtain_access_token")
@patch("integrations.loxone_structure.requests.post")
@patch("integrations.loxone_structure.requests.get")
def test_probe_mcp17_connect_follow_would_401_but_manual_redirect_ok(
    get_mock, post_mock, token_mock
):
    """Regression: do not treat relay GET 401 (OAuth challenge) as resolve failure."""
    get_response = MagicMock()
    get_response.status_code = 307
    get_response.headers = {
        "Location": "https://1-2-3-4.abc.dyndns.loxonecloud.com:30001/"
    }
    get_mock.return_value = get_response
    token_mock.return_value = "oauth-token"
    post_response = MagicMock()
    post_response.status_code = 401
    post_mock.return_value = post_response

    result = probe_mcp17(
        "https://connect.loxonecloud.com/504F94A1137C",
        username="u",
        password="p",
    )
    assert not result.ok
    assert "401" in result.errors[0]
    assert "OAuth Bearer" in result.errors[0]
    assert "rejected" in result.errors[0]
    assert post_mock.call_args.args[0].endswith("/mcp")


@patch("integrations.loxone_structure.obtain_access_token")
@patch("integrations.loxone_structure.requests.get")
def test_probe_mcp17_surfaces_oauth_error(get_mock, token_mock):
    get_response = MagicMock()
    get_response.status_code = 307
    get_response.headers = {
        "Location": "https://relay.dyndns.loxonecloud.com:41234/mcp"
    }
    get_mock.return_value = get_response
    token_mock.side_effect = McpOAuthError("login was rejected")
    result = probe_mcp17(
        "https://connect.loxonecloud.com/504F94A1137C/mcp",
        username="u",
        password="p",
    )
    assert not result.ok
    assert result.errors == ["MCP OAuth failed: login was rejected"]


@patch("integrations.loxone_structure._resolve_mcp_broad_controls")
@patch("integrations.loxone_structure.obtain_access_token")
@patch("integrations.loxone_structure.requests.post")
def test_probe_mcp17_422_retries_with_initialize(post_mock, token_mock, broad_mock):
    token_mock.return_value = "oauth-token"
    broad_mock.return_value = []
    first = MagicMock()
    first.status_code = 422
    first.text = "session required"
    second = MagicMock()
    second.status_code = 200
    second.headers = {"Mcp-Session-Id": "sid-1"}
    second.json.return_value = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"protocolVersion": "2025-03-26", "capabilities": {}},
    }
    third = MagicMock()
    third.status_code = 200
    third.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "control_find"}]},
    }
    post_mock.side_effect = [first, second, third]
    result = probe_mcp17("https://relay.example/mcp", username="u", password="p")
    assert result.mcp_tools == ["control_find"]
    assert post_mock.call_count == 3
    call_retry = post_mock.call_args_list[2]
    assert call_retry.kwargs["headers"]["Mcp-Session-Id"] == "sid-1"
    assert (
        call_retry.kwargs["headers"]["Mcp-Protocol-Version"] == "2025-03-26"
    )


def test_extract_controls_unwraps_mcp_content_text_json():
    result = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "controls": [
                            {
                                "name": "Ernie_EAuto_Ziel_kW",
                                "uuid": "abc-123",
                                "type": "InfoOnlyAnalog",
                            }
                        ]
                    }
                ),
            }
        ]
    }
    controls = _extract_controls(result)
    assert len(controls) == 1
    assert controls[0]["name"] == "Ernie_EAuto_Ziel_kW"
    assert controls[0]["uuid"] == "abc-123"


def test_extract_controls_prefers_structured_content():
    result = {
        "content": [{"type": "text", "text": "ignored"}],
        "structuredContent": {
            "items": [{"name": "Netz_Leistung", "id": "uuid-9"}]
        },
    }
    controls = _extract_controls(result)
    assert controls[0]["name"] == "Netz_Leistung"


def test_filter_mcp_mapping_items_drops_rest_meters():
    from integrations.loxone_structure import StructureItem, _filter_mcp_mapping_items

    rows = [
        StructureItem(
            name="Rest",
            uuid="u1",
            type="Meter",
            room="r",
            source=SOURCE_MCP17,
        ),
        StructureItem(
            name="Ernie_EAuto_Ziel_kW",
            uuid="u2",
            type="InfoOnlyAnalog",
            source=SOURCE_MCP17,
        ),
        StructureItem(
            name="Ernie_EAuto_Ziel_kW",
            uuid="u3",
            type="InfoOnlyAnalog",
            source=SOURCE_MCP17,
        ),
    ]
    filtered = _filter_mcp_mapping_items(rows)
    assert [r.name for r in filtered] == ["Ernie_EAuto_Ziel_kW"]


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

"""MCP 17.1 structure probe (broad resolve + probe_mcp17)."""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable

import requests

from integrations.loxone_mcp_oauth import McpOAuthError
from integrations.loxone_structure import (
    SOURCE_MCP17,
    StructureItem,
    StructureScanResult,
)
from integrations.loxone_mcp_transport import (
    _control_metadata_from_describe,
    _control_name,
    _control_uuid,
    _ensure_mcp_session,
    _extract_controls,
    _filter_mcp_mapping_items,
    _is_useful_mcp_mapping_item,
    _mcp_http_error_message,
    _mcp_initialize_then_retry,
    _mcp_tools_scan_result,
    _normalize_mcp_endpoint,
    _oauth_bearer_token,
    _parse_mcp_jsonrpc_body,
    _parse_sse_json_response,
    _post_mcp_tool_call,
    _post_mcp_tools_list,
    _resolve_mcp_configured_names,
    _resolve_mcp_entry,
    _response_text_snippet,
    _unwrap_tool_call_result,
)

logger = logging.getLogger(__name__)


def _structure_mod():
    from integrations import loxone_structure as mod

    return mod



def _mcp_broad_query_candidates(seed_queries: list[str] | None) -> list[dict[str, Any]]:
    query_candidates: list[dict[str, Any]] = []
    for seed in seed_queries or []:
        seed = str(seed or "").strip()
        if seed:
            query_candidates.extend(
                [{"query": seed}, {"name": seed}, {"text": seed}]
            )
    # Avoid empty/wildcard queries — they tend to return EFM "Rest" meters.
    if not query_candidates:
        for token in ("Ernie", "Earnie", "Status", "Leistung", "SoC", "SOC"):
            query_candidates.append({"query": token})
    return query_candidates


def _run_control_find_queries(
    mcp_call: Any,
    query_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for args in query_candidates:
        resp = mcp_call("control_find", args)
        if resp.status_code >= 400:
            continue
        body, _ = _parse_mcp_jsonrpc_body(resp)
        if not body:
            continue
        found = _extract_controls(body.get("result"))
        if found:
            controls.extend(found)
    return controls


def _seed_items_by_uuid(
    controls: list[dict[str, Any]],
    max_controls: int,
) -> dict[str, StructureItem]:
    items_by_uuid: dict[str, StructureItem] = {}
    for c in controls[:max_controls]:
        uuid = _control_uuid(c)
        if not uuid:
            continue
        name = _control_name(c) or uuid
        items_by_uuid[uuid] = StructureItem(
            name=name,
            uuid=uuid,
            type=str(c.get("type") or c.get("controlType") or ""),
            room=str(c.get("room") or ""),
            category=str(c.get("category") or ""),
            source=SOURCE_MCP17,
        )
    return items_by_uuid


def _describe_one_control(mcp_call: Any, uuid: str) -> Any:
    for dargs in ({"uuid": uuid}, {"id": uuid}):
        resp = mcp_call("control_describe", dargs)
        if resp.status_code >= 400:
            continue
        body, _ = _parse_mcp_jsonrpc_body(resp)
        if not body:
            continue
        return _unwrap_tool_call_result(body.get("result"))
    return None


def _describe_items_in_place(
    mcp_call: Any,
    items_by_uuid: dict[str, StructureItem],
    max_describe: int,
) -> None:
    uuids = list(items_by_uuid.keys())
    for uuid in uuids[:max_describe]:
        describe_any = _describe_one_control(mcp_call, uuid)
        if describe_any is None:
            continue
        meta = _control_metadata_from_describe(describe_any)
        it = items_by_uuid.get(uuid)
        if not it:
            continue
        items_by_uuid[uuid] = StructureItem(
            name=_control_name(meta) or it.name,
            uuid=uuid,
            type=str(meta.get("type") or it.type or ""),
            room=str(meta.get("room") or it.room or ""),
            category=str(meta.get("category") or it.category or ""),
            source=SOURCE_MCP17,
        )


def _resolve_mcp_broad_controls(
    endpoint: str,
    *,
    bearer_token: str,
    timeout_sec: float,
    max_controls: int = 300,
    max_describe: int = 50,
    seed_queries: list[str] | None = None,
) -> list[StructureItem]:
    session_id, protocol_version = _ensure_mcp_session(
        endpoint, bearer_token=bearer_token, timeout_sec=timeout_sec
    )

    def mcp_call(tool_name: str, arguments: dict[str, Any]) -> requests.Response:
        nonlocal session_id, protocol_version
        resp = _post_mcp_tool_call(
            endpoint,
            bearer_token=bearer_token,
            tool_name=tool_name,
            arguments=arguments,
            session_id=session_id,
            protocol_version=protocol_version,
            timeout_sec=timeout_sec,
        )
        if resp.status_code != 422 or session_id:
            return resp
        session_id, protocol_version = _ensure_mcp_session(
            endpoint, bearer_token=bearer_token, timeout_sec=timeout_sec
        )
        return _post_mcp_tool_call(
            endpoint,
            bearer_token=bearer_token,
            tool_name=tool_name,
            arguments=arguments,
            session_id=session_id,
            protocol_version=protocol_version,
            timeout_sec=timeout_sec,
        )

    query_candidates = _mcp_broad_query_candidates(seed_queries)
    controls = _run_control_find_queries(mcp_call, query_candidates)
    if not controls:
        return []

    items_by_uuid = _seed_items_by_uuid(controls, max_controls)
    _describe_items_in_place(mcp_call, items_by_uuid, max_describe)

    out = list(items_by_uuid.values())
    out.sort(key=lambda row: row.name.lower())
    return _filter_mcp_mapping_items(out)


def _resolve_mcp_endpoint_and_token(
    mcp_base_url: str,
    *,
    username: str,
    password: str,
    timeout_sec: float,
) -> tuple[str, str, StructureScanResult | None]:
    """Resolve the MCP endpoint and OAuth bearer token, or an early error result."""
    base = str(mcp_base_url or "").strip()
    if not base:
        return "", "", StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=["MCP base URL is empty"],
            skipped=True,
        )
    endpoint = _normalize_mcp_endpoint(base)
    endpoint, resolve_err = _resolve_mcp_entry(endpoint, timeout_sec=timeout_sec)
    if resolve_err:
        return "", "", StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[resolve_err],
        )
    try:
        bearer_token = _oauth_bearer_token(
            endpoint,
            username=username,
            password=password,
            timeout_sec=max(timeout_sec, 20.0),
        )
    except McpOAuthError as exc:
        return "", "", StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[f"MCP OAuth failed: {exc}"],
        )
    return endpoint, bearer_token, None


def _fetch_initial_tools_list(
    endpoint: str,
    *,
    bearer_token: str,
    timeout_sec: float,
) -> tuple[requests.Response | None, StructureScanResult | None]:
    try:
        response = _post_mcp_tools_list(
            endpoint,
            bearer_token=bearer_token,
            timeout_sec=max(timeout_sec, 20.0),
        )
    except _structure_mod().requests.RequestException as exc:
        return None, StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[f"MCP unreachable: {exc}"],
        )
    return response, None


def _retry_tools_list_via_422(
    response: requests.Response,
    endpoint: str,
    *,
    bearer_token: str,
    timeout_sec: float,
) -> tuple[requests.Response | None, StructureScanResult | None]:
    try:
        retried, init_err = _mcp_initialize_then_retry(
            endpoint,
            bearer_token=bearer_token,
            timeout_sec=max(timeout_sec, 20.0),
        )
    except _structure_mod().requests.RequestException as exc:
        return None, StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[f"MCP initialize/retry failed: {exc}"],
        )
    if init_err:
        return None, StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[init_err],
        )
    if retried is not None and retried.status_code < 400:
        return retried, None
    if retried is not None:
        return None, StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[
                _mcp_http_error_message(
                    retried.status_code,
                    endpoint,
                    auth_mode="OAuth Bearer tools/list after initialize",
                    response_text=_response_text_snippet(retried),
                )
            ],
        )
    return None, StructureScanResult(
        source=SOURCE_MCP17,
        structure_complete=False,
        errors=[
            _mcp_http_error_message(
                response.status_code,
                endpoint,
                auth_mode="OAuth Bearer",
                response_text=_response_text_snippet(response),
            )
        ],
    )


def _resolve_tools_list_response(
    response: requests.Response,
    endpoint: str,
    *,
    bearer_token: str,
    timeout_sec: float,
) -> tuple[requests.Response | None, StructureScanResult | None]:
    """Handle non-2xx ``tools/list`` responses, including the 422 initialize+retry path."""
    if response.status_code < 400:
        return response, None
    if int(response.status_code) == 422:
        return _retry_tools_list_via_422(
            response, endpoint, bearer_token=bearer_token, timeout_sec=timeout_sec
        )
    return None, StructureScanResult(
        source=SOURCE_MCP17,
        structure_complete=False,
        errors=[
            _mcp_http_error_message(
                response.status_code,
                endpoint,
                auth_mode="OAuth Bearer",
                response_text=_response_text_snippet(response),
            )
        ],
    )


def _configured_names_scan_result(
    endpoint: str,
    *,
    bearer_token: str,
    configured: list[str],
    timeout_sec: float,
    tools: list[str],
) -> StructureScanResult | None:
    mcp_items = _filter_mcp_mapping_items(
        _resolve_mcp_configured_names(
            endpoint,
            bearer_token=bearer_token,
            configured_names=configured,
            timeout_sec=max(timeout_sec, 20.0),
        )
    )
    if not mcp_items:
        return None
    return StructureScanResult(
        source=SOURCE_MCP17,
        structure_complete=True,
        items=mcp_items,
        errors=[],
        mcp_tools=tools,
    )


def _broad_discovery_scan_result(
    endpoint: str,
    *,
    bearer_token: str,
    timeout_sec: float,
    seeds: list[str],
    tools: list[str],
) -> StructureScanResult | None:
    broad = _structure_mod()._resolve_mcp_broad_controls(
        endpoint,
        bearer_token=bearer_token,
        timeout_sec=max(timeout_sec, 20.0),
        seed_queries=seeds,
    )
    if not broad:
        return None
    return StructureScanResult(
        source=SOURCE_MCP17,
        structure_complete=True,
        items=broad,
        errors=[],
        mcp_tools=tools,
    )


def probe_mcp17(
    mcp_base_url: str,
    *,
    username: str = "",
    password: str = "",
    timeout_sec: float = 8.0,
    configured_names: list[str] | None = None,
    seed_names: list[str] | None = None,
) -> StructureScanResult:
    """Probe official Loxone 17.1 MCP and resolve control names for mapping.

    Auth uses Miniserver credentials via headless OAuth 2.1 on the relay
    (``connect.loxonecloud.com`` → 307 → dyndns relay). After ``tools/list``,
    discovery prefers ``control_find`` / ``control_describe`` for configured
    marker names, then falls back to broad ``control_find`` queries. Tool-call
    payloads unwrap MCP ``content`` / ``structuredContent``.
    """
    endpoint, bearer_token, error_result = _resolve_mcp_endpoint_and_token(
        mcp_base_url, username=username, password=password, timeout_sec=timeout_sec
    )
    if error_result is not None:
        return error_result

    response, error_result = _fetch_initial_tools_list(
        endpoint, bearer_token=bearer_token, timeout_sec=timeout_sec
    )
    if error_result is not None:
        return error_result

    response, error_result = _resolve_tools_list_response(
        response, endpoint, bearer_token=bearer_token, timeout_sec=timeout_sec
    )
    if error_result is not None:
        return error_result

    tools, parse_error = _parse_mcp_tools(response)
    if parse_error:
        return _mcp_tools_scan_result(tools, parse_error)

    configured = configured_names or []
    seeds = list(dict.fromkeys([*(seed_names or []), *configured]))
    if configured:
        configured_result = _configured_names_scan_result(
            endpoint,
            bearer_token=bearer_token,
            configured=configured,
            timeout_sec=timeout_sec,
            tools=tools,
        )
        if configured_result is not None:
            return configured_result
        # Fall through to broad discovery with seeds.

    # Broad discovery when configured resolve found 0 / no configured names yet.
    broad_result = _broad_discovery_scan_result(
        endpoint,
        bearer_token=bearer_token,
        timeout_sec=timeout_sec,
        seeds=seeds,
        tools=tools,
    )
    if broad_result is not None:
        return broad_result
    return _mcp_tools_scan_result(tools, parse_error)


def _parse_mcp_tools(response: requests.Response) -> tuple[list[str], str | None]:
    try:
        body = response.json()
    except ValueError:
        body, parse_err = _parse_sse_json_response(response)
        if parse_err:
            text = (response.text or "")[:200]
            return [], f"MCP non-JSON response: {text!r}"
    if not isinstance(body, dict):
        return [], "MCP JSON root is not an object"
    if body.get("error"):
        return [], f"MCP error: {body.get('error')}"
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    raw_tools = result.get("tools") if isinstance(result.get("tools"), list) else []
    names: list[str] = []
    for tool in raw_tools:
        if isinstance(tool, dict) and tool.get("name"):
            names.append(str(tool["name"]))
    return names, None


def _has_structure_tool(tool_names: list[str]) -> bool:
    hints = (
        "list_controls",
        "list_devices",
        "get_structure",
        "structure",
        "control_find",
        "control_describe",
    )
    return any(any(hint in name.lower() for hint in hints) for name in tool_names)


def _items_from_mcp_tools_meta(tool_names: list[str]) -> list[StructureItem]:
    """No standard Loxone structure payload wired yet — listing deferred to lab."""
    del tool_names
    return []


def _union_items(variants: Iterable[StructureScanResult]) -> list[StructureItem]:
    by_name: dict[str, StructureItem] = {}
    source_hits: dict[str, list[str]] = {}
    for variant in variants:
        for item in variant.items:
            name = item.name
            source_hits.setdefault(name, [])
            if variant.source not in source_hits[name]:
                source_hits[name].append(variant.source)
            if name not in by_name:
                by_name[name] = item
    merged: list[StructureItem] = []
    for name, item in by_name.items():
        sources = source_hits.get(name) or ([item.source] if item.source else [])
        merged.append(
            StructureItem(
                name=item.name,
                uuid=item.uuid,
                type=item.type,
                room=item.room,
                category=item.category,
                source="+".join(sources) if sources else SOURCE_UNION,
            )
        )
    merged.sort(key=lambda row: row.name.lower())
    return merged



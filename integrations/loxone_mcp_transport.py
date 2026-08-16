"""Low-level MCP HTTP/SSE/OAuth transport for Loxone structure probe."""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth

from integrations.loxone_mcp_oauth import (
    McpOAuthError,
    entry_origin_from_mcp_url,
    obtain_access_token,
)
from integrations.loxone_structure import (
    SOURCE_MCP17,
    StructureItem,
    StructureScanResult,
)

logger = logging.getLogger(__name__)

_CONTENT_TYPE_JSON = "application/json"
_ACCEPT_JSON_OR_SSE = "application/json, text/event-stream"


def _structure_mod():
    """Facade module — tests patch requests/OAuth on loxone_structure."""
    from integrations import loxone_structure as mod
    return mod



def _normalize_mcp_endpoint(base: str) -> str:
    text = str(base or "").strip()
    if text.rstrip("/").endswith("/mcp"):
        return text
    return urljoin(text.rstrip("/") + "/", "mcp")


def _resolve_mcp_entry(
    endpoint: str,
    *,
    timeout_sec: float,
) -> tuple[str, str | None]:
    """Resolve connect.loxonecloud.com → current relay MCP URL (manual redirect).

    Connect itself is unauthenticated (307 + Location). Following redirects with
    ``allow_redirects=True`` often lands on the relay GET ``/mcp``, which returns
    401 as an OAuth challenge — that must not be treated as a failed resolve.
    """
    if "connect.loxonecloud.com" not in endpoint.lower():
        return endpoint, None
    try:
        response = _structure_mod().requests.get(
            endpoint,
            timeout=timeout_sec,
            allow_redirects=False,
        )
    except _structure_mod().requests.RequestException as exc:
        return endpoint, f"MCP connect resolve failed: {exc}"
    if 300 <= int(response.status_code) < 400:
        location = response.headers.get("Location") or response.headers.get("location")
        if not location:
            return endpoint, "MCP connect redirect missing Location header"
        final = urljoin(endpoint, str(location).strip())
        if not final.lower().startswith("https://"):
            return endpoint, f"MCP connect redirected to non-HTTPS: {final}"
        if not final.rstrip("/").endswith("/mcp"):
            final = urljoin(final.rstrip("/") + "/", "mcp")
        return final, None
    if int(response.status_code) >= 400:
        return (
            endpoint,
            f"MCP connect resolve HTTP {response.status_code} at {endpoint}",
        )
    return (
        endpoint,
        f"MCP connect did not redirect (HTTP {response.status_code})",
    )


def _post_mcp_tools_list(
    endpoint: str,
    *,
    bearer_token: str | None,
    session_id: str = "",
    protocol_version: str = "",
    timeout_sec: float,
) -> requests.Response:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    headers = {
        "Content-Type": _CONTENT_TYPE_JSON,
        "Accept": _ACCEPT_JSON_OR_SSE,
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if protocol_version:
        headers["Mcp-Protocol-Version"] = protocol_version
    return _structure_mod().requests.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=timeout_sec,
    )


def _post_mcp_tool_call(
    endpoint: str,
    *,
    bearer_token: str | None,
    tool_name: str,
    arguments: dict[str, Any],
    session_id: str = "",
    protocol_version: str = "",
    timeout_sec: float,
) -> requests.Response:
    payload = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = {
        "Content-Type": _CONTENT_TYPE_JSON,
        "Accept": _ACCEPT_JSON_OR_SSE,
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if protocol_version:
        headers["Mcp-Protocol-Version"] = protocol_version
    return _structure_mod().requests.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=timeout_sec,
    )


def _parse_mcp_jsonrpc_body(
    response: requests.Response,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        body = response.json()
    except ValueError:
        body, parse_err = _parse_sse_json_response(response)
        return (body, parse_err)
    if isinstance(body, dict):
        return body, None
    return None, "MCP JSON root is not an object"


def _parse_sse_json_response(
    response: requests.Response,
) -> tuple[dict[str, Any] | None, str | None]:
    text = str(response.text or "")
    if "data:" not in text:
        return None, "response is not SSE"
    chunks = [part.strip() for part in text.split("\n\n") if part.strip()]
    for chunk in chunks:
        data_lines: list[str] = []
        for line in chunk.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue
        payload = "\n".join(data_lines)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed, None
    return None, "SSE had no JSON object payload"


def _post_mcp_initialize(
    endpoint: str,
    *,
    bearer_token: str | None,
    timeout_sec: float,
) -> requests.Response:
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "earnie-mcp-probe", "version": "0.1"},
        },
    }
    headers = {
        "Content-Type": _CONTENT_TYPE_JSON,
        "Accept": _ACCEPT_JSON_OR_SSE,
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return _structure_mod().requests.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=timeout_sec,
    )


def _response_text_snippet(response: requests.Response, *, limit: int = 220) -> str:
    text = str(getattr(response, "text", "") or "").strip()
    if not text:
        return ""
    return text[:limit]


def _mcp_http_error_message(
    status_code: int,
    endpoint: str,
    *,
    auth_mode: str,
    response_text: str = "",
) -> str:
    msg = f"MCP HTTP {status_code} at {endpoint} ({auth_mode})"
    if int(status_code) == 401:
        msg += "; relay rejected OAuth Bearer or session establishment failed"
    if int(status_code) == 422:
        msg += "; MCP likely requires initialize/session handshake"
    if response_text:
        msg += f"; response={response_text!r}"
    return msg


def _mcp_initialize_then_retry(
    endpoint: str,
    *,
    bearer_token: str,
    timeout_sec: float,
) -> tuple[requests.Response | None, str | None]:
    init = _post_mcp_initialize(
        endpoint, bearer_token=bearer_token, timeout_sec=timeout_sec
    )
    if init.status_code >= 400:
        return None, _mcp_http_error_message(
            init.status_code,
            endpoint,
            auth_mode="OAuth Bearer initialize",
            response_text=_response_text_snippet(init),
        )
    session_id = str(init.headers.get("Mcp-Session-Id") or "").strip()
    protocol_version = ""
    try:
        body = init.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        result = body.get("result")
        if isinstance(result, dict):
            protocol_version = str(result.get("protocolVersion") or "").strip()
    retried = _post_mcp_tools_list(
        endpoint,
        bearer_token=bearer_token,
        session_id=session_id,
        protocol_version=protocol_version,
        timeout_sec=timeout_sec,
    )
    return retried, None


def _oauth_bearer_token(
    endpoint: str,
    *,
    username: str,
    password: str,
    timeout_sec: float,
) -> str:
    origin = entry_origin_from_mcp_url(endpoint)
    return _structure_mod().obtain_access_token(
        origin,
        username,
        password,
        timeout_sec=max(timeout_sec, 20.0),
    )


def _mcp_tools_scan_result(
    tools: list[str],
    parse_error: str | None,
) -> StructureScanResult:
    from integrations.loxone_mcp_probe import (
        _has_structure_tool,
        _items_from_mcp_tools_meta,
    )

    if parse_error:
        return StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[parse_error],
            mcp_tools=tools,
        )
    items = _items_from_mcp_tools_meta(tools)
    if items:
        err: list[str] = []
    elif _has_structure_tool(tools):
        err = [
            "MCP control_find/control_describe available but returned no controls"
        ]
    else:
        err = [
            "MCP tools/list OK but no structure-related tools "
            "(expected control_find/control_describe)"
        ]
    return StructureScanResult(
        source=SOURCE_MCP17,
        structure_complete=bool(items),
        items=items,
        mcp_tools=tools,
        errors=err,
    )


def _text_blocks_from_content(content: list[Any]) -> list[str]:
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") != "text":
            continue
        text = str(block.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _joined_content_payload(content: list[Any]) -> Any | None:
    texts = _text_blocks_from_content(content)
    if not texts:
        return None
    joined = "\n".join(texts).strip()
    try:
        return json.loads(joined)
    except ValueError:
        # Non-JSON text — keep as string for debug / callers.
        return joined


def _unwrap_tool_call_result(result_any: Any) -> Any:
    """Normalize MCP tools/call result (content[] / structuredContent) to payload."""
    if not isinstance(result_any, dict):
        return result_any
    structured = result_any.get("structuredContent")
    if structured is not None:
        return structured
    content = result_any.get("content")
    if isinstance(content, list):
        payload = _joined_content_payload(content)
        if payload is not None:
            return payload
    return result_any


def _extract_controls(result_any: Any) -> list[dict[str, Any]]:
    result_any = _unwrap_tool_call_result(result_any)
    if isinstance(result_any, list):
        return [c for c in result_any if isinstance(c, dict)]
    if isinstance(result_any, str):
        # Sometimes Loxone returns a line-oriented / markdown dump.
        return []
    if not isinstance(result_any, dict):
        return []
    # Common response shapes from different MCP implementations.
    for key in (
        "controls",
        "items",
        "results",
        "matches",
        "data",
        "devices",
        "found",
        "entries",
    ):
        maybe = result_any.get(key)
        if isinstance(maybe, list):
            return [c for c in maybe if isinstance(c, dict)]
    # Some servers nest again under a secondary `result` field.
    nested = result_any.get("result")
    if isinstance(nested, list):
        return [c for c in nested if isinstance(c, dict)]
    if isinstance(nested, dict):
        return _extract_controls(nested)
    # If this dict already looks like a single control, treat it as one.
    if any(
        isinstance(result_any.get(k), str) and str(result_any.get(k)).strip()
        for k in ("uuid", "id", "name", "label")
    ):
        return [result_any]
    return []


def _control_uuid(control: dict[str, Any]) -> str:
    for k in (
        "uuidAction",
        "uuid",
        "control_uuid",
        "controlUuid",
        "controlId",
        "control_id",
        "id",
    ):
        v = control.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _control_name(control: dict[str, Any]) -> str:
    for k in ("name", "label", "title", "displayName", "caption"):
        v = control.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for k, v in control.items():
        if (
            isinstance(k, str)
            and k.lower().endswith("_name")
            and isinstance(v, str)
            and v.strip()
        ):
            return v.strip()
    return ""


def _is_useful_mcp_mapping_item(item: StructureItem) -> bool:
    """Drop EFM leftovers / uuid-as-name junk that is useless for Merker mapping."""
    name = str(item.name or "").strip()
    if not name:
        return False
    if name == item.uuid:
        return False
    # UUID-shaped labels are not mapping-friendly Merker names.
    if len(name) >= 30 and name.count("-") >= 3:
        return False
    type_l = str(item.type or "").lower()
    # Broad control_find often returns Energieflussmonitor "Rest" meters.
    if name.lower() == "rest" and "meter" in type_l:
        return False
    return True


def _filter_mcp_mapping_items(items: list[StructureItem]) -> list[StructureItem]:
    out: list[StructureItem] = []
    seen_names: set[str] = set()
    for item in items:
        if not _is_useful_mcp_mapping_item(item):
            continue
        key = item.name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        out.append(item)
    return out


def _control_metadata_from_describe(desc_any: Any) -> dict[str, Any]:
    desc_any = _unwrap_tool_call_result(desc_any)
    if not isinstance(desc_any, dict):
        return {}
    for k in ("control", "device", "entity", "data", "result"):
        v = desc_any.get(k)
        if isinstance(v, dict):
            return v
    return desc_any


def _find_control_for_query(
    mcp_call: Any,
    query: str,
) -> tuple[dict[str, Any] | None, str]:
    find_args_candidates = [
        {"query": query},
        {"name": query},
        {"text": query},
    ]
    for find_args in find_args_candidates:
        resp = mcp_call("control_find", find_args)
        if resp.status_code >= 400:
            continue
        body, _ = _parse_mcp_jsonrpc_body(resp)
        if not body or not isinstance(body.get("result"), (dict, list)):
            continue
        controls = _extract_controls(body.get("result"))
        found_control: dict[str, Any] | None = None
        for c in controls:
            cname = _control_name(c)
            if cname and cname.lower() == query.lower():
                found_control = c
                break
        if not found_control and controls:
            found_control = controls[0]
        if found_control:
            return found_control, _control_uuid(found_control)
    return None, ""


def _describe_configured_control(mcp_call: Any, found_uuid: str) -> Any:
    for describe_args in ({"uuid": found_uuid}, {"id": found_uuid}):
        resp = mcp_call("control_describe", describe_args)
        if resp.status_code >= 400:
            continue
        body, _ = _parse_mcp_jsonrpc_body(resp)
        if not body:
            continue
        return body.get("result")
    return None


def _resolve_one_configured_name(mcp_call: Any, query: str) -> StructureItem | None:
    found_control, found_uuid = _find_control_for_query(mcp_call, query)
    if not found_control or not found_uuid:
        return None
    describe_any = _describe_configured_control(mcp_call, found_uuid)
    if describe_any is None:
        return None
    meta = _control_metadata_from_describe(describe_any)
    return StructureItem(
        name=_control_name(meta) or query,
        uuid=found_uuid,
        type=str(meta.get("type") or ""),
        room=str(meta.get("room") or ""),
        category=str(meta.get("category") or ""),
        source=SOURCE_MCP17,
    )


def _resolve_mcp_configured_names(
    endpoint: str,
    *,
    bearer_token: str,
    configured_names: list[str],
    timeout_sec: float,
) -> list[StructureItem]:
    session_id, protocol_version = _ensure_mcp_session(
        endpoint, bearer_token=bearer_token, timeout_sec=timeout_sec
    )
    items: list[StructureItem] = []
    seen_names: set[str] = set()

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

    for raw_name in configured_names:
        query = str(raw_name or "").strip()
        if not query or query.lower() in seen_names:
            continue
        seen_names.add(query.lower())
        item = _resolve_one_configured_name(mcp_call, query)
        if item is not None:
            items.append(item)

    items.sort(key=lambda row: row.name.lower())
    return items


def _post_mcp_initialized_notification(
    endpoint: str,
    *,
    bearer_token: str | None,
    session_id: str = "",
    protocol_version: str = "",
    timeout_sec: float,
) -> None:
    headers = {
        "Content-Type": _CONTENT_TYPE_JSON,
        "Accept": _ACCEPT_JSON_OR_SSE,
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if protocol_version:
        headers["Mcp-Protocol-Version"] = protocol_version
    try:
        _structure_mod().requests.post(
            endpoint,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=headers,
            timeout=timeout_sec,
        )
    except _structure_mod().requests.RequestException:
        # Non-fatal: some relays ignore the notification.
        return


def _ensure_mcp_session(
    endpoint: str,
    *,
    bearer_token: str,
    timeout_sec: float,
) -> tuple[str, str]:
    """Initialize MCP session; return (session_id, protocol_version)."""
    init = _post_mcp_initialize(
        endpoint, bearer_token=bearer_token, timeout_sec=timeout_sec
    )
    if init.status_code >= 400:
        return "", ""
    session_id = str(init.headers.get("Mcp-Session-Id") or "").strip()
    protocol_version = ""
    try:
        body = init.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and isinstance(body.get("result"), dict):
        protocol_version = str(body["result"].get("protocolVersion") or "").strip()
    _post_mcp_initialized_notification(
        endpoint,
        bearer_token=bearer_token,
        session_id=session_id,
        protocol_version=protocol_version,
        timeout_sec=timeout_sec,
    )
    return session_id, protocol_version



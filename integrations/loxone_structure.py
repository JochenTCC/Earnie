"""Miniserver structure scan for Loxone → EHAL mapping (2.4.f / 2.4.n).

Research mode (default): LoxAPP3 + HTTP marker probe (known Earnie_* / configured
names via ``/jdev/sps/io``) + optional MCP 17.1, then compare results.
A single preferred source may be selected later once lab data decides the winner.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth

from integrations.loxone_mcp_oauth import (
    McpOAuthError,
    entry_origin_from_mcp_url,
    obtain_access_token,
)

logger = logging.getLogger(__name__)

SOURCE_LOXAPP3 = "loxapp3"
SOURCE_HTTP_PROBE = "http_probe"
SOURCE_MCP17 = "mcp17"
SOURCE_UNION = "union"
SOURCE_NONE = "none"

ALL_SOURCES = (SOURCE_LOXAPP3, SOURCE_HTTP_PROBE, SOURCE_MCP17)


@dataclass(frozen=True)
class StructureItem:
    name: str
    uuid: str = ""
    type: str = ""
    room: str = ""
    category: str = ""
    source: str = ""


@dataclass
class StructureScanResult:
    source: str
    structure_complete: bool
    items: list[StructureItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mcp_tools: list[str] = field(default_factory=list)
    skipped: bool = False

    def as_dicts(self) -> list[dict[str, str]]:
        return [
            {
                "name": item.name,
                "uuid": item.uuid,
                "type": item.type,
                "room": item.room,
                "category": item.category,
                "source": item.source or self.source,
            }
            for item in self.items
        ]

    @property
    def ok(self) -> bool:
        return (not self.skipped) and (bool(self.items) or bool(self.mcp_tools))


@dataclass
class StructureCompareResult:
    """Outcome of probing one or more structure sources (research compare)."""

    variants: list[StructureScanResult] = field(default_factory=list)
    selected_source: str = SOURCE_UNION

    def variant(self, source: str) -> StructureScanResult | None:
        for row in self.variants:
            if row.source == source:
                return row
        return None

    def comparison_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for variant in self.variants:
            rows.append(
                {
                    "source": variant.source,
                    "ok": variant.ok,
                    "skipped": variant.skipped,
                    "item_count": len(variant.items),
                    "structure_complete": variant.structure_complete,
                    "mcp_tools": ", ".join(variant.mcp_tools[:12]),
                    "errors": "; ".join(variant.errors[:3]),
                }
            )
        return rows

    def mapping_items(self, *, use_source: str | None = None) -> list[StructureItem]:
        """Names for HITL dropdowns; default = union of all variants."""
        source = str(use_source or self.selected_source or SOURCE_UNION).strip()
        if source and source != SOURCE_UNION:
            variant = self.variant(source)
            return list(variant.items) if variant else []
        return _union_items(self.variants)

    def all_errors(self) -> list[str]:
        out: list[str] = []
        for variant in self.variants:
            for err in variant.errors:
                out.append(f"[{variant.source}] {err}")
        return out


class LoxoneStructureError(RuntimeError):
    """Raised when a structure source fails hard."""


def _room_cat_names(doc: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    rooms_raw = doc.get("rooms") if isinstance(doc.get("rooms"), dict) else {}
    cats_raw = doc.get("cats") if isinstance(doc.get("cats"), dict) else {}
    rooms = {
        str(uid): str(meta.get("name") or "")
        for uid, meta in rooms_raw.items()
        if isinstance(meta, dict)
    }
    cats = {
        str(uid): str(meta.get("name") or "")
        for uid, meta in cats_raw.items()
        if isinstance(meta, dict)
    }
    return rooms, cats


def normalize_loxapp3(doc: dict[str, Any]) -> list[StructureItem]:
    """Flatten LoxAPP3 controls into mappable name rows."""
    if not isinstance(doc, dict):
        raise LoxoneStructureError("LoxAPP3 root must be an object")
    controls = doc.get("controls")
    if not isinstance(controls, dict):
        raise LoxoneStructureError("LoxAPP3 missing controls object")
    rooms, cats = _room_cat_names(doc)
    items: list[StructureItem] = []
    seen: set[str] = set()
    for uid, meta in controls.items():
        if not isinstance(meta, dict):
            continue
        name = str(meta.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        room_id = str(meta.get("room") or "")
        cat_id = str(meta.get("cat") or "")
        items.append(
            StructureItem(
                name=name,
                uuid=str(uid),
                type=str(meta.get("type") or ""),
                room=rooms.get(room_id, ""),
                category=cats.get(cat_id, ""),
                source=SOURCE_LOXAPP3,
            )
        )
    items.sort(key=lambda row: row.name.lower())
    return items


def fetch_loxapp3_json(
    *,
    host: str,
    username: str,
    password: str,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    """GET http://{host}/data/LoxAPP3.json with HTTP Basic Auth."""
    ip = str(host or "").strip().removeprefix("http://").removeprefix("https://")
    ip = ip.split("/")[0]
    if not ip:
        raise LoxoneStructureError("LOXONE_IP is empty")
    url = f"http://{ip}/data/LoxAPP3.json"
    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(username, password),
            timeout=timeout_sec,
        )
    except (requests.RequestException, OSError, ValueError) as exc:
        raise LoxoneStructureError(f"LoxAPP3 fetch failed: {exc}") from exc
    if response.status_code != 200:
        raise LoxoneStructureError(
            f"LoxAPP3 HTTP {response.status_code} from {url}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise LoxoneStructureError("LoxAPP3 response is not JSON") from exc
    if not isinstance(payload, dict):
        raise LoxoneStructureError("LoxAPP3 JSON root is not an object")
    return payload


def scan_loxapp3(
    *,
    host: str,
    username: str,
    password: str,
    timeout_sec: float = 15.0,
) -> StructureScanResult:
    doc = fetch_loxapp3_json(
        host=host, username=username, password=password, timeout_sec=timeout_sec
    )
    items = normalize_loxapp3(doc)
    return StructureScanResult(
        source=SOURCE_LOXAPP3,
        structure_complete=True,
        items=items,
    )


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
        response = requests.get(
            endpoint,
            timeout=timeout_sec,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
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
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if protocol_version:
        headers["Mcp-Protocol-Version"] = protocol_version
    return requests.post(
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
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if protocol_version:
        headers["Mcp-Protocol-Version"] = protocol_version
    return requests.post(
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
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return requests.post(
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
    return obtain_access_token(
        origin,
        username,
        password,
        timeout_sec=max(timeout_sec, 20.0),
    )


def _mcp_tools_scan_result(
    tools: list[str],
    parse_error: str | None,
) -> StructureScanResult:
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


def _unwrap_tool_call_result(result_any: Any) -> Any:
    """Normalize MCP tools/call result (content[] / structuredContent) to payload."""
    if not isinstance(result_any, dict):
        return result_any
    structured = result_any.get("structuredContent")
    if structured is not None:
        return structured
    content = result_any.get("content")
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "") != "text":
                continue
            text = str(block.get("text") or "").strip()
            if text:
                texts.append(text)
        if texts:
            joined = "\n".join(texts).strip()
            try:
                return json.loads(joined)
            except ValueError:
                # Non-JSON text — keep as string for debug / callers.
                return joined
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

        find_args_candidates = [
            {"query": query},
            {"name": query},
            {"text": query},
        ]
        found_control: dict[str, Any] | None = None
        found_uuid = ""

        for find_args in find_args_candidates:
            resp = mcp_call("control_find", find_args)
            if resp.status_code >= 400:
                continue
            body, _ = _parse_mcp_jsonrpc_body(resp)
            if not body or not isinstance(body.get("result"), (dict, list)):
                continue
            controls = _extract_controls(body.get("result"))
            for c in controls:
                cname = _control_name(c)
                if cname and cname.lower() == query.lower():
                    found_control = c
                    break
            if not found_control and controls:
                found_control = controls[0]
            if found_control:
                found_uuid = _control_uuid(found_control)
                break

        if not found_control or not found_uuid:
            continue

        describe_args_candidates = [
            {"uuid": found_uuid},
            {"id": found_uuid},
        ]
        describe_any: Any = None
        for describe_args in describe_args_candidates:
            resp = mcp_call("control_describe", describe_args)
            if resp.status_code >= 400:
                continue
            body, _ = _parse_mcp_jsonrpc_body(resp)
            if not body:
                continue
            describe_any = body.get("result")
            break
        if describe_any is None:
            continue

        meta = _control_metadata_from_describe(describe_any)
        item_name = _control_name(meta) or query
        items.append(
            StructureItem(
                name=item_name,
                uuid=found_uuid,
                type=str(meta.get("type") or ""),
                room=str(meta.get("room") or ""),
                category=str(meta.get("category") or ""),
                source=SOURCE_MCP17,
            )
        )

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
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if protocol_version:
        headers["Mcp-Protocol-Version"] = protocol_version
    try:
        requests.post(
            endpoint,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=headers,
            timeout=timeout_sec,
        )
    except requests.RequestException:
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
    items_by_uuid: dict[str, StructureItem] = {}

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

    if not controls:
        return []

    for c in controls[:max_controls]:
        uuid = _control_uuid(c)
        name = _control_name(c) or uuid
        if not uuid:
            continue
        items_by_uuid[uuid] = StructureItem(
            name=name,
            uuid=uuid,
            type=str(c.get("type") or c.get("controlType") or ""),
            room=str(c.get("room") or ""),
            category=str(c.get("category") or ""),
            source=SOURCE_MCP17,
        )

    uuids = list(items_by_uuid.keys())
    for uuid in uuids[:max_describe]:
        describe_args_candidates = [{"uuid": uuid}, {"id": uuid}]
        describe_any: Any = None
        for dargs in describe_args_candidates:
            resp = mcp_call("control_describe", dargs)
            if resp.status_code >= 400:
                continue
            body, _ = _parse_mcp_jsonrpc_body(resp)
            if not body:
                continue
            describe_any = _unwrap_tool_call_result(body.get("result"))
            break
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

    out = list(items_by_uuid.values())
    out.sort(key=lambda row: row.name.lower())
    return _filter_mcp_mapping_items(out)


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
    base = str(mcp_base_url or "").strip()
    if not base:
        return StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=["MCP base URL is empty"],
            skipped=True,
        )
    endpoint = _normalize_mcp_endpoint(base)
    endpoint, resolve_err = _resolve_mcp_entry(endpoint, timeout_sec=timeout_sec)
    if resolve_err:
        return StructureScanResult(
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
        return StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[f"MCP OAuth failed: {exc}"],
        )
    try:
        response = _post_mcp_tools_list(
            endpoint,
            bearer_token=bearer_token,
            timeout_sec=max(timeout_sec, 20.0),
        )
    except requests.RequestException as exc:
        return StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[f"MCP unreachable: {exc}"],
        )
    if response.status_code >= 400:
        if int(response.status_code) == 422:
            try:
                retried, init_err = _mcp_initialize_then_retry(
                    endpoint,
                    bearer_token=bearer_token,
                    timeout_sec=max(timeout_sec, 20.0),
                )
            except requests.RequestException as exc:
                return StructureScanResult(
                    source=SOURCE_MCP17,
                    structure_complete=False,
                    errors=[f"MCP initialize/retry failed: {exc}"],
                )
            if init_err:
                return StructureScanResult(
                    source=SOURCE_MCP17,
                    structure_complete=False,
                    errors=[init_err],
                )
            if retried is not None and retried.status_code < 400:
                tools, parse_error = _parse_mcp_tools(retried)
                response = retried
            elif retried is not None:
                return StructureScanResult(
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
            else:
                return StructureScanResult(
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
        else:
            return StructureScanResult(
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
    tools, parse_error = _parse_mcp_tools(response)
    if parse_error:
        return _mcp_tools_scan_result(tools, parse_error)

    configured = configured_names or []
    seeds = list(dict.fromkeys([*(seed_names or []), *configured]))
    if configured:
        mcp_items = _filter_mcp_mapping_items(
            _resolve_mcp_configured_names(
                endpoint,
                bearer_token=bearer_token,
                configured_names=configured,
                timeout_sec=max(timeout_sec, 20.0),
            )
        )
        if mcp_items:
            return StructureScanResult(
                source=SOURCE_MCP17,
                structure_complete=True,
                items=mcp_items,
                errors=[],
                mcp_tools=tools,
            )
        # Fall through to broad discovery with seeds.

    # Broad discovery when configured resolve found 0 / no configured names yet.
    broad = _resolve_mcp_broad_controls(
        endpoint,
        bearer_token=bearer_token,
        timeout_sec=max(timeout_sec, 20.0),
        seed_queries=seeds,
    )
    if broad:
        return StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=True,
            items=broad,
            errors=[],
            mcp_tools=tools,
        )
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
        payload = "\n".join(data_lines).strip()
        if not payload:
            continue
        try:
            body = json.loads(payload)
        except ValueError:
            continue
        if isinstance(body, dict):
            return body, None
    return None, "no JSON event found in SSE body"


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


def _http_probe_candidate_names(
    configured_names: list[str] | None,
    *,
    extra_names: list[str] | None = None,
) -> list[str]:
    """Device-map Earnie_* names, configured bindings, plus optional LoxAPP3 Earnie_*."""
    from integrations.loxone_greenfield_import import (
        device_map_marker_names,
        load_device_map,
    )

    names: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        name = str(raw or "").strip()
        if not name:
            return
        key = name.casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(name)

    try:
        for name in device_map_marker_names(load_device_map()):
            _add(name)
    except (OSError, ValueError, FileNotFoundError) as exc:
        logger.info("HTTP probe: device map unavailable: %s", exc)
    for raw in configured_names or []:
        _add(str(raw))
    for raw in extra_names or []:
        _add(str(raw))
    return names


def probe_http_markers(
    *,
    host: str,
    username: str,
    password: str,
    configured_names: list[str] | None = None,
    extra_names: list[str] | None = None,
    timeout_sec: float = 5.0,
) -> StructureScanResult:
    """Probe known Merker names via /jdev/sps/io (200/403 = present, 404 = missing)."""
    from integrations.loxone_greenfield_import import probe_marker_names

    names = _http_probe_candidate_names(configured_names, extra_names=extra_names)
    if not names:
        return StructureScanResult(
            source=SOURCE_HTTP_PROBE,
            structure_complete=False,
            skipped=True,
            errors=["HTTP probe: no device-map or configured names to probe"],
        )
    try:
        result = probe_marker_names(
            names,
            host=host,
            username=username,
            password=password,
            timeout_sec=timeout_sec,
        )
    except ValueError as exc:
        return StructureScanResult(
            source=SOURCE_HTTP_PROBE,
            structure_complete=False,
            errors=[str(exc)],
        )
    items = [
        StructureItem(name=name, type="http_probe", source=SOURCE_HTTP_PROBE)
        for name in sorted(result.present)
    ]
    errors: list[str] = []
    if result.missing:
        sample = ", ".join(sorted(result.missing)[:8])
        more = len(result.missing) - min(8, len(result.missing))
        suffix = f" (+{more})" if more else ""
        errors.append(f"HTTP probe missing (404): {sample}{suffix}")
    if result.errors:
        errors.append(
            "HTTP probe errors: " + ", ".join(sorted(result.errors)[:6])
        )
    return StructureScanResult(
        source=SOURCE_HTTP_PROBE,
        structure_complete=bool(items),
        items=items,
        errors=errors,
    )


def scan_structure(
    *,
    host: str,
    username: str,
    password: str,
    configured_names: list[str] | None = None,
    mcp_base_url: str = "",
    timeout_sec: float = 15.0,
    sources: tuple[str, ...] | None = None,
    selected_source: str = SOURCE_UNION,
) -> StructureCompareResult:
    """Probe structure sources and return a comparison (default: all variants).

    Default variants: LoxAPP3.json, HTTP probe of known greenfield / configured
    Merker names, and optional MCP 17.1. ``selected_source`` only affects which
    item set feeds mapping dropdowns (``union`` = merge all names).
    """
    wanted = tuple(sources) if sources is not None else ALL_SOURCES
    variants: list[StructureScanResult] = []

    if SOURCE_LOXAPP3 in wanted:
        variants.append(
            _safe_loxapp3(
                host=host,
                username=username,
                password=password,
                timeout_sec=timeout_sec,
            )
        )

    if SOURCE_HTTP_PROBE in wanted:
        loxapp3_for_probe = next(
            (v for v in variants if v.source == SOURCE_LOXAPP3 and v.ok),
            None,
        )
        earnie_from_loxapp3 = [
            item.name
            for item in (loxapp3_for_probe.items if loxapp3_for_probe else [])
            if str(item.name or "").casefold().startswith("earnie_")
        ]
        variants.append(
            probe_http_markers(
                host=host,
                username=username,
                password=password,
                configured_names=configured_names or [],
                extra_names=earnie_from_loxapp3,
                timeout_sec=min(timeout_sec, 5.0),
            )
        )

    if SOURCE_MCP17 in wanted:
        loxapp3 = next(
            (v for v in variants if v.source == SOURCE_LOXAPP3 and v.ok),
            None,
        )
        seed_from_loxapp3 = (
            [item.name for item in loxapp3.items[:80]] if loxapp3 else []
        )
        variants.append(
            probe_mcp17(
                mcp_base_url,
                username=username,
                password=password,
                timeout_sec=max(timeout_sec, 45.0),
                configured_names=configured_names or [],
                seed_names=seed_from_loxapp3,
            )
        )

    return StructureCompareResult(
        variants=variants,
        selected_source=selected_source or SOURCE_UNION,
    )


def _safe_loxapp3(
    *,
    host: str,
    username: str,
    password: str,
    timeout_sec: float,
) -> StructureScanResult:
    try:
        return scan_loxapp3(
            host=host,
            username=username,
            password=password,
            timeout_sec=timeout_sec,
        )
    except LoxoneStructureError as exc:
        logger.info("LoxAPP3 scan failed: %s", exc)
        return StructureScanResult(
            source=SOURCE_LOXAPP3,
            structure_complete=False,
            errors=[str(exc)],
        )

"""Miniserver structure scan for Loxone → EHAL mapping (2.4.f).

Research mode (default): run **all** structure variants and compare results.
A single preferred source may be selected later once lab data decides the winner.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth

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


def probe_configured_names(
    names: list[str],
    *,
    fetch_raw,
) -> StructureScanResult:
    """Partial scan: keep names that respond on Miniserver HTTP."""
    items: list[StructureItem] = []
    errors: list[str] = []
    for raw_name in names:
        name = str(raw_name or "").strip()
        if not name:
            continue
        try:
            value = fetch_raw(name)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        if value is None:
            errors.append(f"{name}: no value")
            continue
        items.append(
            StructureItem(name=name, type="http_probe", source=SOURCE_HTTP_PROBE)
        )
    return StructureScanResult(
        source=SOURCE_HTTP_PROBE,
        structure_complete=False,
        items=items,
        errors=errors,
    )


def probe_mcp17(
    mcp_base_url: str,
    *,
    timeout_sec: float = 8.0,
) -> StructureScanResult:
    """Probe official Loxone 17.1 MCP (tools/list). Structure listing if exposed."""
    base = str(mcp_base_url or "").strip()
    if not base:
        return StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=["MCP base URL is empty"],
            skipped=True,
        )
    endpoint = base if base.rstrip("/").endswith("/mcp") else urljoin(
        base.rstrip("/") + "/", "mcp"
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            timeout=timeout_sec,
        )
    except requests.RequestException as exc:
        return StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[f"MCP unreachable: {exc}"],
        )
    if response.status_code >= 400:
        return StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[f"MCP HTTP {response.status_code} at {endpoint}"],
        )
    tools, parse_error = _parse_mcp_tools(response)
    if parse_error:
        return StructureScanResult(
            source=SOURCE_MCP17,
            structure_complete=False,
            errors=[parse_error],
            mcp_tools=tools,
        )
    items = _items_from_mcp_tools_meta(tools)
    has_structure_tool = _has_structure_tool(tools)
    if items:
        err: list[str] = []
    elif has_structure_tool:
        err = [
            "MCP exposes a structure-related tool; control listing not wired yet "
            "(research/compare — decide later)"
        ]
    else:
        err = [
            "MCP tools/list OK but no structure-listing tools found "
            "(research/compare — decide later)"
        ]
    return StructureScanResult(
        source=SOURCE_MCP17,
        structure_complete=bool(items),
        items=items,
        mcp_tools=tools,
        errors=err,
    )


def _parse_mcp_tools(response: requests.Response) -> tuple[list[str], str | None]:
    try:
        body = response.json()
    except ValueError:
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
    hints = ("list_controls", "list_devices", "get_structure", "structure")
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


def scan_structure(
    *,
    host: str,
    username: str,
    password: str,
    configured_names: list[str] | None = None,
    mcp_base_url: str = "",
    fetch_raw=None,
    timeout_sec: float = 15.0,
    sources: tuple[str, ...] | None = None,
    selected_source: str = SOURCE_UNION,
) -> StructureCompareResult:
    """Probe structure sources and return a comparison (default: all variants).

    Unless ``sources`` is restricted, every known variant is attempted so lab
    data can decide the best path later. ``selected_source`` only affects which
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
        variants.append(
            _safe_http_probe(configured_names or [], fetch_raw=fetch_raw)
        )

    if SOURCE_MCP17 in wanted:
        variants.append(
            probe_mcp17(mcp_base_url, timeout_sec=min(timeout_sec, 8.0))
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


def _safe_http_probe(
    names: list[str],
    *,
    fetch_raw,
) -> StructureScanResult:
    if fetch_raw is None:
        return StructureScanResult(
            source=SOURCE_HTTP_PROBE,
            structure_complete=False,
            errors=["fetch_raw callback not provided"],
            skipped=True,
        )
    if not names:
        return StructureScanResult(
            source=SOURCE_HTTP_PROBE,
            structure_complete=False,
            errors=["no configured marker names to probe"],
            skipped=True,
        )
    return probe_configured_names(names, fetch_raw=fetch_raw)

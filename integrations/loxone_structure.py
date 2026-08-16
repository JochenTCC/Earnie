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



from integrations.loxone_mcp_probe import (  # noqa: E402
    probe_mcp17,
    _has_structure_tool,
    _items_from_mcp_tools_meta,
    _normalize_mcp_endpoint,
    _parse_mcp_tools,
    _parse_sse_json_response,
    _resolve_mcp_broad_controls,
    _resolve_mcp_entry,
    _union_items,
)
from integrations.loxone_mcp_transport import (  # noqa: E402
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
    _oauth_bearer_token,
    _parse_mcp_jsonrpc_body,
    _parse_sse_json_response,
    _post_mcp_initialize,
    _post_mcp_initialized_notification,
    _post_mcp_tool_call,
    _post_mcp_tools_list,
    _resolve_mcp_configured_names,
    _response_text_snippet,
    _unwrap_tool_call_result,
)

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


# Re-Exports für API-Stabilität
__all__ = [
    "ALL_SOURCES",
    "LoxoneStructureError",
    "SOURCE_HTTP_PROBE",
    "SOURCE_LOXAPP3",
    "SOURCE_MCP17",
    "SOURCE_NONE",
    "SOURCE_UNION",
    "StructureCompareResult",
    "StructureItem",
    "StructureScanResult",
    "fetch_loxapp3_json",
    "normalize_loxapp3",
    "probe_http_markers",
    "probe_mcp17",
    "scan_loxapp3",
    "scan_structure",
]

"""Land/Typ filters for Bezugs- and Einspeisetarif pickers."""
from __future__ import annotations

from typing import Literal

import streamlit as st

from data.tariff_parameter_preview import (
    EXPORT_TYPE_LABELS,
    IMPORT_TYPE_LABELS,
    tariff_parameter_rows,
    type_caption,
)

ALL_FILTER = "Alle"

# Month-constant feed-in is catalog type monthly_table (owned monthly_rates).
EXPORT_MONTHLY_UI_TYPES = frozenset({"monthly_table"})
EXPORT_MONTHLY_UI_KEY = "monthly_table"

# Re-export for existing imports.
__all__ = [
    "ALL_FILTER",
    "EXPORT_MONTHLY_UI_KEY",
    "EXPORT_MONTHLY_UI_TYPES",
    "EXPORT_TYPE_LABELS",
    "IMPORT_TYPE_LABELS",
    "filter_tariffs",
    "lands_present",
    "lands_union",
    "render_shared_land_filter",
    "render_tariff_parameter_preview",
    "tariff_meta_caption",
    "tariff_parameter_rows",
    "type_caption",
    "types_present",
    "with_current_tariff",
]


def _canonicalize_export_type(tariff_type: str) -> str:
    if tariff_type in EXPORT_MONTHLY_UI_TYPES:
        return EXPORT_MONTHLY_UI_KEY
    return tariff_type


def _export_type_matches(item_type: str, filter_type: str) -> bool:
    if filter_type in EXPORT_MONTHLY_UI_TYPES:
        return item_type in EXPORT_MONTHLY_UI_TYPES
    return item_type == filter_type


def tariff_meta_caption(tariff: dict) -> str:
    parts: list[str] = []
    land = tariff.get("land")
    currency = tariff.get("currency")
    if land:
        parts.append(f"Land: {land}")
    if currency:
        parts.append(f"Währung: {currency}")
    notes = tariff.get("notes")
    if notes:
        parts.append(str(notes))
    return " · ".join(parts)


def render_tariff_parameter_preview(
    tariff: dict,
    *,
    title: str,
    kind: Literal["import", "export"],
    container=None,
) -> None:
    """Show compact read-only tariff parameters under a Szenarienkonfigurator select."""
    root = container if container is not None else st
    rows = tariff_parameter_rows(tariff, kind=kind)
    if not rows:
        return
    root.caption(title)
    for label, value in rows:
        root.caption(f"{label}: {value}")


def lands_present(tariffs: list[dict]) -> list[str]:
    lands = {
        str(item.get("land") or "").strip().upper()
        for item in tariffs
        if str(item.get("land") or "").strip()
    }
    return sorted(lands)


def lands_union(*tariff_lists: list[dict]) -> list[str]:
    """Sorted unique lands across multiple tariff catalogs (import + export)."""
    combined: list[dict] = []
    for tariffs in tariff_lists:
        combined.extend(tariffs)
    return lands_present(combined)


def types_present(
    tariffs: list[dict],
    *,
    kind: Literal["import", "export"] | None = None,
) -> list[str]:
    """Sorted unique types; export month-constant is monthly_table."""
    types: set[str] = set()
    for item in tariffs:
        raw = str(item.get("type") or "").strip().lower()
        if not raw:
            continue
        if kind == "export":
            raw = _canonicalize_export_type(raw)
        types.add(raw)
    return sorted(types)


def filter_tariffs(
    tariffs: list[dict],
    *,
    land: str | None = None,
    tariff_type: str | None = None,
    kind: Literal["import", "export"] | None = None,
) -> list[dict]:
    """Filter by land and/or type. None / empty means no restriction on that axis."""
    land_key = (land or "").strip().upper() or None
    type_key = (tariff_type or "").strip().lower() or None
    result: list[dict] = []
    for item in tariffs:
        if land_key is not None:
            item_land = str(item.get("land") or "").strip().upper()
            if item_land != land_key:
                continue
        if type_key is not None:
            item_type = str(item.get("type") or "").strip().lower()
            if kind == "export":
                if not _export_type_matches(item_type, type_key):
                    continue
            elif item_type != type_key:
                continue
        result.append(item)
    return result


def with_current_tariff(
    filtered: list[dict],
    all_tariffs: list[dict],
    current_id: str | None,
) -> tuple[list[dict], bool]:
    """Ensure current_id remains in the list. Returns (list, was_outside_filters)."""
    cid = (current_id or "").strip()
    if not cid:
        return list(filtered), False
    if any(str(item.get("id", "")).strip() == cid for item in filtered):
        return list(filtered), False
    match = next(
        (item for item in all_tariffs if str(item.get("id", "")).strip() == cid),
        None,
    )
    if match is None:
        return list(filtered), False
    return [match, *filtered], True


def _type_labels_for(kind: Literal["import", "export"]) -> dict[str, str]:
    return IMPORT_TYPE_LABELS if kind == "import" else EXPORT_TYPE_LABELS


def _format_type_option(type_key: str, labels: dict[str, str]) -> str:
    if type_key == ALL_FILTER:
        return ALL_FILTER
    return labels.get(type_key, type_key)


def render_shared_land_filter(
    *,
    key: str,
    import_tariffs: list[dict],
    export_tariffs: list[dict],
    default_land: str = "AT",
    container=None,
) -> str:
    """Single mandatory Land selectbox (AT/DE/CH). Never returns Alle/None."""
    root = container if container is not None else st
    available = lands_union(import_tariffs, export_tariffs)
    land_options = available if available else ["AT", "DE", "CH"]
    preferred = (default_land or "AT").strip().upper()
    if preferred not in {"AT", "DE", "CH"}:
        preferred = "AT"
    if preferred not in land_options:
        preferred = land_options[0]
    if key not in st.session_state or st.session_state[key] not in land_options:
        st.session_state[key] = preferred
    land_pick = root.selectbox("Land", options=land_options, key=key)
    return str(land_pick).strip().upper()


def render_tariff_type_filter(
    *,
    key_prefix: str,
    tariffs: list[dict],
    kind: Literal["import", "export"],
    land: str | None = None,
    current_id: str | None = None,
    label_prefix: str = "",
    container=None,
) -> list[dict]:
    """Render Typ filter (after shared Land); return filtered tariffs."""
    root = container if container is not None else st
    type_labels = _type_labels_for(kind)
    after_land = filter_tariffs(tariffs, land=land, kind=kind)
    type_options = [ALL_FILTER, *types_present(after_land, kind=kind)]
    type_key = f"{key_prefix}_type"
    if type_key in st.session_state and st.session_state[type_key] not in type_options:
        st.session_state[type_key] = ALL_FILTER
    type_pick = root.selectbox(
        f"{label_prefix}Typ".strip(),
        options=type_options,
        key=type_key,
        format_func=lambda t: _format_type_option(t, type_labels),
    )
    type_filter = None if type_pick == ALL_FILTER else type_pick
    filtered = filter_tariffs(after_land, tariff_type=type_filter, kind=kind)
    result, outside = with_current_tariff(filtered, tariffs, current_id)
    if outside:
        root.caption(
            "Aktuelle Auswahl liegt außerhalb der Filter — Tarif bleibt wählbar."
        )
    return result

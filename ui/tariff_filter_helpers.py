"""Land/Typ filters for Bezugs- and Einspeisetarif pickers."""
from __future__ import annotations

from typing import Literal

import streamlit as st

ALL_FILTER = "Alle"

IMPORT_TYPE_LABELS = {
    "awattar": "aWATTar (EPEX + Aufschlag aus tariffs.json)",
    "fixed_cent": "Fixpreis Bezug",
    "spot_hourly": "Spot stündlich",
    "ex_post_spot": "Spot ex-post",
    "monthly_market": "Monatsmarkt",
    "monthly_table": "Monatstabelle Bezug",
}

EXPORT_TYPE_LABELS = {
    "fixed": "Fixpreis Einspeise",
    "dynamic_epex": "Dynamisch EPEX (Legacy)",
    "monthly_table": "Monatstabelle",
    "monthly_float": "Monatsfloat",
    "spot_hourly": "Spot stündlich",
    "ex_post_spot": "Spot ex-post",
}


def type_caption(tariff: dict, labels: dict[str, str]) -> str:
    tariff_type = str(tariff.get("type", "")).strip().lower()
    return labels.get(tariff_type, tariff_type or "unbekannt")


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


def lands_present(tariffs: list[dict]) -> list[str]:
    lands = {
        str(item.get("land") or "").strip().upper()
        for item in tariffs
        if str(item.get("land") or "").strip()
    }
    return sorted(lands)


def types_present(tariffs: list[dict]) -> list[str]:
    types = {
        str(item.get("type") or "").strip().lower()
        for item in tariffs
        if str(item.get("type") or "").strip()
    }
    return sorted(types)


def filter_tariffs(
    tariffs: list[dict],
    *,
    land: str | None = None,
    tariff_type: str | None = None,
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
            if item_type != type_key:
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


def render_tariff_filter_row(
    *,
    key_prefix: str,
    tariffs: list[dict],
    kind: Literal["import", "export"],
    current_id: str | None = None,
    label_prefix: str = "",
) -> list[dict]:
    """Render Land + Typ filters; return filtered tariffs (current kept if needed)."""
    type_labels = _type_labels_for(kind)
    land_options = [ALL_FILTER, *lands_present(tariffs)]
    land_col, type_col = st.columns(2)
    with land_col:
        land_pick = st.selectbox(
            f"{label_prefix}Land".strip(),
            options=land_options,
            key=f"{key_prefix}_land",
        )
    land_filter = None if land_pick == ALL_FILTER else land_pick
    after_land = filter_tariffs(tariffs, land=land_filter)
    type_options = [ALL_FILTER, *types_present(after_land)]
    type_key = f"{key_prefix}_type"
    if type_key in st.session_state and st.session_state[type_key] not in type_options:
        st.session_state[type_key] = ALL_FILTER
    with type_col:
        type_pick = st.selectbox(
            f"{label_prefix}Typ".strip(),
            options=type_options,
            key=type_key,
            format_func=lambda t: _format_type_option(t, type_labels),
        )
    type_filter = None if type_pick == ALL_FILTER else type_pick
    filtered = filter_tariffs(after_land, tariff_type=type_filter)
    result, outside = with_current_tariff(filtered, tariffs, current_id)
    if outside:
        st.caption(
            "Aktuelle Auswahl liegt außerhalb der Filter — Tarif bleibt wählbar."
        )
    return result

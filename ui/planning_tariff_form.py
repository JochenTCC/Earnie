"""Tarif-Auswahl-Tab im Hauskonfigurator (kein Tarif-Editor)."""
from __future__ import annotations

import os

import streamlit as st

from ui.house_config_io import (
    get_planning_tariff_selection,
    list_export_tariffs,
    list_import_tariffs,
    load_tariffs_catalog_meta,
    save_planning_tariff_selection,
    tariffs_json_path,
)

_IMPORT_TYPE_LABELS = {
    "awattar": "aWATTar (EPEX + Aufschlag aus config.json)",
    "fixed_cent": "Fixpreis Bezug",
    "spot_hourly": "Spot stündlich",
    "ex_post_spot": "Spot ex-post",
    "monthly_market": "Monatsmarkt",
}

_EXPORT_TYPE_LABELS = {
    "fixed": "Fixpreis Einspeise",
    "dynamic_epex": "Dynamisch EPEX (Legacy)",
    "monthly_table": "Monatstabelle",
    "spot_hourly": "Spot stündlich",
    "ex_post_spot": "Spot ex-post",
}


def _tariff_label(tariff: dict) -> str:
    return str(tariff.get("label") or tariff.get("id", ""))


def _type_caption(tariff: dict, labels: dict[str, str]) -> str:
    tariff_type = str(tariff.get("type", "")).strip().lower()
    return labels.get(tariff_type, tariff_type or "unbekannt")


def _tariff_meta_caption(tariff: dict) -> str:
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


def render_tariff_selection_tab() -> None:
    catalog_meta = load_tariffs_catalog_meta()
    catalog_as_of = catalog_meta.get("catalog_as_of")
    if catalog_as_of:
        st.caption(f"Tarifkatalog: Stand {catalog_as_of}")

    imports = list_import_tariffs()
    exports = list_export_tariffs()
    if not imports or not exports:
        catalog_path = tariffs_json_path()
        missing_hint = " (Datei nicht gefunden)" if not os.path.isfile(catalog_path) else ""
        st.warning(
            f"Der Tarif-Katalog in `{catalog_path}` ist leer oder unvollständig{missing_hint}. "
            "Neue Tarife bitte manuell in der Datei ergänzen (Vorlage: `tariffs.example.json`)."
        )
        return

    current_import, current_export = get_planning_tariff_selection()
    import_ids = [item["id"] for item in imports]
    export_ids = [item["id"] for item in exports]
    import_index = import_ids.index(current_import) if current_import in import_ids else 0
    export_index = export_ids.index(current_export) if current_export in export_ids else 0

    import_pick = st.selectbox(
        "Bezugstarif",
        options=import_ids,
        index=import_index,
        format_func=lambda tariff_id: _tariff_label(next(t for t in imports if t["id"] == tariff_id)),
        key="planning_import_tariff",
    )
    import_tariff = next(item for item in imports if item["id"] == import_pick)
    st.caption(f"Typ: {_type_caption(import_tariff, _IMPORT_TYPE_LABELS)}")
    meta_caption = _tariff_meta_caption(import_tariff)
    if meta_caption:
        st.caption(meta_caption)

    export_pick = st.selectbox(
        "Einspeisetarif",
        options=export_ids,
        index=export_index,
        format_func=lambda tariff_id: _tariff_label(next(t for t in exports if t["id"] == tariff_id)),
        key="planning_export_tariff",
    )
    export_tariff = next(item for item in exports if item["id"] == export_pick)
    st.caption(f"Typ: {_type_caption(export_tariff, _EXPORT_TYPE_LABELS)}")
    meta_caption = _tariff_meta_caption(export_tariff)
    if meta_caption:
        st.caption(meta_caption)

    st.info(
        "Neue Tarife werden nicht in der UI angelegt. "
        f"Ergänze Einträge manuell in `{tariffs_json_path()}` "
        "(Referenz: `config/tariffs.example.json` oder `tools/convert_dach_tariffs.py`)."
    )

    if st.button("Tarifwahl speichern", type="primary", key="planning_tariff_save"):
        save_planning_tariff_selection(import_pick, export_pick)
        st.success("Tarifwahl gespeichert.")
        st.rerun()

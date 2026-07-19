"""Tarif-Auswahl-Tab im Hauskonfigurator (kein Tarif-Editor)."""
from __future__ import annotations

import os

import streamlit as st

from ui.form_layout import labeled_selectbox
from ui.house_config_io import (
    get_planning_tariff_selection,
    list_export_tariffs,
    list_import_tariffs,
    load_tariffs_catalog_meta,
    save_planning_tariff_selection,
    tariffs_json_path,
)
from ui.label_select import (
    align_label_select_session,
    label_select_choices,
    resolve_label_select,
)
from ui.tariff_filter_helpers import (
    EXPORT_TYPE_LABELS,
    IMPORT_TYPE_LABELS,
    tariff_meta_caption,
    type_caption,
)

# Backward-compatible aliases for existing UI imports.
_IMPORT_TYPE_LABELS = IMPORT_TYPE_LABELS
_EXPORT_TYPE_LABELS = EXPORT_TYPE_LABELS
_type_caption = type_caption
_tariff_meta_caption = tariff_meta_caption


def _tariff_label(tariff: dict) -> str:
    return str(tariff.get("label") or tariff.get("id", ""))


def _render_tariff_picker(
    *,
    title: str,
    tariffs: list[dict],
    current_id: str,
    select_key: str,
    selected_id_key: str,
    type_labels: dict,
) -> str:
    tariff_map = {item["id"]: item for item in tariffs}
    tariff_ids = [item["id"] for item in tariffs]
    options, id_by_display = label_select_choices(
        tariff_map, tariff_ids, new_option=None
    )
    if selected_id_key not in st.session_state and current_id in tariff_map:
        st.session_state[selected_id_key] = current_id
    align_label_select_session(
        select_key=select_key,
        selected_id_key=selected_id_key,
        entity_map=tariff_map,
        entity_ids=tariff_ids,
        id_by_display=id_by_display,
        new_option=None,
    )
    if select_key not in st.session_state:
        index = tariff_ids.index(current_id) if current_id in tariff_ids else 0
        pick_display = labeled_selectbox(
            title,
            options=options,
            index=index,
            key=select_key,
        )
    else:
        pick_display = labeled_selectbox(
            title,
            options=options,
            key=select_key,
        )
    pick = resolve_label_select(pick_display, id_by_display)
    st.session_state[selected_id_key] = pick
    tariff = tariff_map[pick]
    st.caption(f"Typ: {_type_caption(tariff, type_labels)}")
    meta_caption = _tariff_meta_caption(tariff)
    if meta_caption:
        st.caption(meta_caption)
    return pick


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
    import_pick = _render_tariff_picker(
        title="Bezugstarif",
        tariffs=imports,
        current_id=current_import,
        select_key="planning_import_tariff",
        selected_id_key="planning_import_tariff_id",
        type_labels=_IMPORT_TYPE_LABELS,
    )
    export_pick = _render_tariff_picker(
        title="Einspeisetarif",
        tariffs=exports,
        current_id=current_export,
        select_key="planning_export_tariff",
        selected_id_key="planning_export_tariff_id",
        type_labels=_EXPORT_TYPE_LABELS,
    )

    st.info(
        "Neue Tarife werden nicht in der UI angelegt. "
        f"Ergänze Einträge manuell in `{tariffs_json_path()}` "
        "(Referenz: `config/tariffs.example.json` oder `tools/convert_dach_tariffs.py`)."
    )

    if st.button("Tarifwahl speichern", type="primary", key="planning_tariff_save"):
        save_planning_tariff_selection(import_pick, export_pick)
        st.success("Tarifwahl gespeichert.")
        st.rerun()

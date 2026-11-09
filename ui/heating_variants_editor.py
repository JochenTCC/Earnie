"""Heating-system variants editor (components.json ``heating_systems[]``), Hauskonfigurator area.

Lists every catalog entry. A house's reference system is read-only here (it is edited in the
house configurator, because it fixes that house's baseload). Every entry can be copied as the
start of a new variant; that copy is the only way to create one. Further variants are edited
(saved automatically on change) and deleted only here; an entry that a house profile or a
scenario references cannot be deleted.
"""
from __future__ import annotations

import streamlit as st

from house_config.heating_systems import (
    HEATING_SYSTEMS_KEY,
    assert_heating_system_deletable,
    normalize_heating_systems,
    reference_ids_by_profile,
    variant_system_id,
)
from ui.auto_persist import auto_persist, persisted_state_known, seed_persisted
from ui.number_format import format_decimal, format_general
from ui.label_select import label_select_choices, resolve_label_select

_SELECT_KEY = "hsv_select"
_PENDING_KEY = "hsv_select_pending"
_EDIT_GEN_KEY = "hsv_edit_gen"


def _load() -> tuple[dict, list[dict], dict, dict]:
    from house_config.components_store import load_components_document
    from runtime_store.persist_paths import resolve_components_json_path
    import os

    from ui.house_config_io import (
        load_backtesting_scenarios_raw,
        read_json_document,
        resolve_house_profiles_json_path,
    )

    components = load_components_document(resolve_components_json_path())
    catalog = normalize_heating_systems(components.get(HEATING_SYSTEMS_KEY))
    house_path = resolve_house_profiles_json_path()
    house_raw = read_json_document(house_path) if os.path.isfile(house_path) else {}
    return components, catalog, house_raw, load_backtesting_scenarios_raw()


def reference_owners(house_raw: dict) -> dict[str, list[str]]:
    """heating_system_id → house profile ids that use it as reference system."""
    owners: dict[str, list[str]] = {}
    for profile_id, refs in reference_ids_by_profile(house_raw).items():
        for system_id in refs.values():
            owners.setdefault(system_id, []).append(profile_id)
    return owners


def _save_catalog(components: dict, catalog: list[dict]) -> None:
    from house_config.heating_systems import serialize_heating_system
    from ui.house_config_io import _save_components_document

    import config

    _save_components_document(
        {**components, HEATING_SYSTEMS_KEY: [serialize_heating_system(e) for e in catalog]}
    )
    config.reinit_config()


def _select(system_id: str) -> None:
    st.session_state[_PENDING_KEY] = system_id
    st.session_state[_EDIT_GEN_KEY] = int(st.session_state.get(_EDIT_GEN_KEY, 0)) + 1
    st.rerun()


def _summary_lines(entry: dict) -> list[str]:
    from ui.house_config_profile_thermal_annual import _HEAT_PUMP_LABELS, _HEAT_SOURCE_LABELS

    from house_config.heat_source import heat_source_is_electric
    from house_config.heating_systems import HEATING_POWER_KEY, heating_input_power_kw

    source = entry["heat_source"]
    kind = _HEAT_SOURCE_LABELS.get(source["type"], source["type"])
    if source["type"] == "heat_pump":
        kind += f" ({_HEAT_PUMP_LABELS.get(source['heat_pump_type'], source['heat_pump_type'])})"
    power = f"Heizleistung: {format_general(entry[HEATING_POWER_KEY])} kW thermisch"
    if heat_source_is_electric(source):
        electric = heating_input_power_kw(source, entry[HEATING_POWER_KEY])
        power += f" (≈ {format_decimal(electric)} kW elektrisch)"
    lines = [f"Wärmequelle: {kind}", power]
    if entry.get("heat_storage"):
        lines.append(f"Wärmespeicher: {format_general(entry['heat_storage']['volume_liters'])} l")
    if entry.get("parts"):
        lines.append(f"Heizstab: {format_general(entry['parts'][0]['nominal_power_kw'])} kW")
    return lines


def _render_variant_form(entry: dict, scope: str) -> dict:
    """Form fields of a variant; returns the raw catalog entry (validated on save)."""
    from ui.form_layout import labeled_text_input
    from ui.house_config_profile_thermal_annual import (
        _render_heat_source_fields,
        _render_heating_rod_fields,
        _render_thermal_storage_fields,
        render_generation_power_fields,
    )

    label = labeled_text_input("Bezeichnung", value=entry.get("label", ""), key=f"{scope}__label")
    heat_source = _render_heat_source_fields(entry, 0, session_scope=scope)
    raw: dict = {
        "id": entry["id"],
        "label": str(label or "").strip() or entry["id"],
        "heat_source": heat_source,
        **render_generation_power_fields(
            heat_source,
            entry,
            power_key=f"{scope}__heat_power",
            min_on_key=f"{scope}__min_on",
        ),
    }
    storage = _render_thermal_storage_fields(entry, 0, session_scope=scope)
    if storage is not None:
        raw["heat_storage"] = storage
        parts = _render_heating_rod_fields(entry, 0, session_scope=scope)
        if parts:
            raw["parts"] = parts
    return raw


def _copy_of(entry: dict, catalog: list[dict]) -> dict:
    label = f"{entry['label']} (Kopie)"
    new = {k: v for k, v in entry.items() if k not in ("id", "label")}
    return {"id": variant_system_id(label, [e["id"] for e in catalog]), "label": label, **new}


def _persist_key(system_id: str) -> str:
    return f"hsv_variant::{system_id}"


def _render_copy_button(entry: dict, components: dict, catalog: list[dict]) -> None:
    if st.button("Als neue Variante kopieren", key="hsv_copy"):
        new = _copy_of(entry, catalog)
        _save_catalog(components, [*catalog, new])
        _select(new["id"])


def _autosave_variant(raw: dict, entry: dict, components: dict, catalog: list[dict]) -> None:
    """Write the edited variant when it is valid and differs from the saved one.

    First render: the form was just seeded from disk, so its value is recorded as saved
    (no write, no ``Gespeichert``) unless it already differs from the stored entry.
    """
    from house_config.heating_systems import serialize_heating_system

    selected_id = entry["id"]
    updated = [raw if e["id"] == selected_id else e for e in catalog]
    try:
        normalized = normalize_heating_systems(updated)
    except ValueError as exc:
        st.error(f"Variante nicht gespeichert: {exc}")
        return
    spec = next(e for e in normalized if e["id"] == selected_id)
    payload = serialize_heating_system(spec)
    state_key = _persist_key(selected_id)
    if not persisted_state_known(state_key) and payload == serialize_heating_system(entry):
        seed_persisted(state_key, payload)
        return
    label_changed = spec["label"] != entry["label"]
    wrote = auto_persist(
        state_key=state_key,
        payload=payload,
        save=lambda: _save_catalog(components, normalized),
        rerun_follows=label_changed,
    )
    if wrote and label_changed:
        # The select box shows the label: rerun so it names the saved entry.
        st.session_state[_PENDING_KEY] = selected_id
        st.rerun()


def render_heating_variants_editor() -> None:
    st.subheader("Heizsystem-Varianten")
    st.caption(
        "Heizsysteme für den Vergleich im Szenario-Explorer; die Auswahl je Szenario "
        "trifft der Szenarienkonfigurator. Das Referenzsystem eines Hauses (eingebaute "
        "Heizung) bearbeitest du im Bereich „Hausprofil“ beim Verbraucher „Haus Wärme“. "
        "Eine neue Variante entsteht als Kopie eines vorhandenen Heizsystems; Änderungen "
        "an einer Variante werden automatisch gespeichert."
    )
    try:
        components, catalog, house_raw, scenarios_raw = _load()
    except ValueError as exc:
        st.error(str(exc))
        return
    if not catalog:
        st.info(
            "Noch kein Heizsystem. Das Referenzsystem entsteht im Bereich „Hausprofil“ "
            "(Verbraucher „Haus Wärme“)."
        )
        return
    owners = reference_owners(house_raw)
    by_id = {entry["id"]: entry for entry in catalog}
    labels = {
        entry["id"]: (
            f"{entry['label']} (Referenzsystem)" if entry["id"] in owners else entry["label"]
        )
        for entry in catalog
    }
    entity_map = {sid: {"label": text} for sid, text in labels.items()}
    options, mapping = label_select_choices(entity_map, list(labels), new_option=None)
    pending = st.session_state.pop(_PENDING_KEY, None)
    if pending is not None:
        st.session_state[_SELECT_KEY] = next(
            (o for o, sid in mapping.items() if sid == pending), options[0]
        )
    if st.session_state.get(_SELECT_KEY) not in options:
        st.session_state[_SELECT_KEY] = options[0]
    pick = st.selectbox("Heizsystem", options=options, key=_SELECT_KEY)
    selected_id = resolve_label_select(pick, mapping)

    entry = by_id[selected_id]
    if selected_id in owners:
        st.info(
            "Referenzsystem von Hausprofil "
            + ", ".join(f"'{pid}'" for pid in owners[selected_id])
            + ": nur lesbar, Änderungen im Bereich „Hausprofil“ (sie verschieben die Grundlast)."
        )
        st.markdown("\n".join(f"- {line}" for line in _summary_lines(entry)))
        _render_copy_button(entry, components, catalog)
        return

    scope = f"hsv_g{int(st.session_state.get(_EDIT_GEN_KEY, 0))}_{selected_id}"
    raw = _render_variant_form(entry, scope)
    _autosave_variant(raw, entry, components, catalog)
    copy_col, delete_col = st.columns(2)
    with copy_col:
        _render_copy_button(entry, components, catalog)
    if delete_col.button("Variante entfernen", key=f"{scope}__delete"):
        try:
            assert_heating_system_deletable(
                selected_id, house_doc=house_raw, scenarios_doc=scenarios_raw
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        remaining = [e for e in catalog if e["id"] != selected_id]
        _save_catalog(components, remaining)
        st.session_state.pop(f"_auto_persist_fp::{_persist_key(selected_id)}", None)
        _select(remaining[0]["id"] if remaining else "")

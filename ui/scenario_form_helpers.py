"""Gemeinsame Hilfen für Szenario-Editor-Selectboxen und Entitäts-ID-Auflösung."""
from __future__ import annotations

import os

import streamlit as st

from house_config.id_slug import slug_id
from runtime_store.persist_paths import resolve_backtesting_scenarios_json_path
from ui.form_layout import labeled_multiselect, labeled_selectbox

NONE_LABEL = "— keine —"
EMPTY_PLACEHOLDER_PREFIX = "— noch keine"
NEW_SCENARIO_OPTION = "— neu —"


def entity_human_label(item: dict) -> str:
    """User-facing entity name without technical id."""
    return str(item.get("label") or item.get("id") or "").strip() or str(item.get("id", ""))


def format_entity_option(option: str) -> str:
    """Strip trailing `` (id)`` from entity option keys for display."""
    if option == NONE_LABEL or option.startswith(EMPTY_PLACEHOLDER_PREFIX):
        return option
    if option.endswith(")") and " (" in option:
        return option[: option.rfind(" (")]
    return option


def options_for_entities(
    items: list[dict],
    *,
    allow_none: bool = False,
) -> tuple[list[str], dict[str, str]]:
    labels: list[str] = []
    mapping: dict[str, str] = {}
    if allow_none:
        labels.append(NONE_LABEL)
        mapping[NONE_LABEL] = ""
    for item in items:
        human = entity_human_label(item)
        label = f"{human} ({item['id']})"
        labels.append(label)
        mapping[label] = item["id"]
    return labels, mapping


def default_label_index(options: list[str], item_id: str | None) -> int:
    if not item_id or not options:
        return 0
    for index, opt in enumerate(options):
        if opt.endswith(f"({item_id})"):
            return index
    return 0


def lookup_entity_id(mapping: dict[str, str], pick: str | None) -> str:
    if pick is None:
        return ""
    return mapping.get(pick, "")


def render_profile_geo_caption(profile: dict) -> None:
    """Read-only Standort/Zeitzone aus Hausprofil."""
    if not profile:
        return
    st.caption(
        "Standort (Hausprofil): "
        f"{float(profile.get('latitude', 0.0)):.4f}° N, "
        f"{float(profile.get('longitude', 0.0)):.4f}° E · "
        f"Zeitzone: {profile.get('timezone_name', 'Europe/Vienna')}"
    )


def scenario_session_scope(selected_id: str, *, is_new: bool) -> str:
    return "__new__" if is_new else selected_id


def scoped_widget_key(session_scope: str, base: str) -> str:
    return f"{session_scope}__{base}"


def backtesting_scenarios_file_stamp() -> str:
    path = resolve_backtesting_scenarios_json_path()
    try:
        return f"{os.path.abspath(path)}:{os.path.getmtime(path)}"
    except OSError:
        return os.path.abspath(path)


def clear_scoped_widget_keys(session_scope: str) -> None:
    prefix = f"{session_scope}__"
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            del st.session_state[key]


def seed_entity_select_state(
    session_scope: str,
    key_base: str,
    items: list[dict],
    current_id: str | None,
    *,
    allow_none: bool = False,
) -> None:
    labels, _ = options_for_entities(items, allow_none=allow_none)
    if not labels:
        return
    idx = default_label_index(labels, current_id)
    st.session_state[scoped_widget_key(session_scope, key_base)] = labels[idx]


def labels_for_entity_ids(items: list[dict], entity_ids: list[str]) -> list[str]:
    """Map entity ids to display labels (order preserved, unknown ids skipped)."""
    labels, mapping = options_for_entities(items, allow_none=False)
    id_to_label = {entity_id: label for label, entity_id in mapping.items()}
    return [id_to_label[entity_id] for entity_id in entity_ids if entity_id in id_to_label]


def seed_entity_multiselect_state(
    session_scope: str,
    key_base: str,
    items: list[dict],
    current_ids: list[str] | None,
) -> None:
    st.session_state[scoped_widget_key(session_scope, key_base)] = labels_for_entity_ids(
        items,
        list(current_ids or []),
    )


def render_entity_multiselect(
    label: str,
    items: list[dict],
    *,
    key: str,
    current_ids: list[str] | None = None,
) -> list[str]:
    """Multiselect for entities; returns selected display labels."""
    labels, _mapping = options_for_entities(items, allow_none=False)
    if not labels:
        placeholder = f"{EMPTY_PLACEHOLDER_PREFIX} {label.lower()} —"
        labeled_multiselect(
            label,
            options=[placeholder],
            disabled=True,
            key=key,
            format_func=format_entity_option,
        )
        return []
    if key not in st.session_state:
        st.session_state[key] = labels_for_entity_ids(items, list(current_ids or []))
    return list(
        labeled_multiselect(
            label,
            options=labels,
            key=key,
            format_func=format_entity_option,
        )
        or []
    )


def new_scenario_template(live_id: str, scenarios: list[dict]) -> dict:
    """Defaults for a new scenario — clone live settings when available."""
    live = next((item for item in scenarios if item.get("id") == live_id), None)
    if live:
        return {
            "label": "Mein Szenario",
            "settings": dict(live.get("settings", {})),
        }
    return {"label": "Mein Szenario", "settings": {}}


def resolve_scenario_id(
    *,
    is_new: bool,
    existing_id: str,
    label: str,
    scenario_ids: set[str],
) -> str:
    if not is_new and existing_id:
        return existing_id
    return slug_id(label or "szenario", existing=set(scenario_ids))


def scenario_baseline_key(session_scope: str) -> str:
    return f"scenario_editor_baseline__{session_scope}"


def build_scenario_settings(
    *,
    battery_id: str,
    pv_system_ids: list[str] | None = None,
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
    netzentgelt_cent_kwh_override: float | None = None,
) -> dict:
    settings: dict = {}
    if battery_id:
        settings["battery_id"] = battery_id
    cleaned_pv = [
        str(item or "").strip()
        for item in (pv_system_ids or [])
        if str(item or "").strip()
    ]
    if cleaned_pv:
        settings["pv_system_ids"] = cleaned_pv
    if import_tariff_id:
        settings["import_tariff_id"] = import_tariff_id
    if export_tariff_id:
        settings["export_tariff_id"] = export_tariff_id
    if house_profile_id:
        settings["house_profile_id"] = house_profile_id
    if netzentgelt_cent_kwh_override is not None and netzentgelt_cent_kwh_override > 0.0:
        settings["netzentgelt_cent_kwh_override"] = float(netzentgelt_cent_kwh_override)
    return settings


def normalize_scenario_form_snapshot(scenario: dict) -> dict:
    from house_config.entity_resolution import normalize_pv_system_ids

    raw_settings = scenario.get("settings", {}) or {}
    settings = build_scenario_settings(
        battery_id=str(raw_settings.get("battery_id", "") or "").strip(),
        pv_system_ids=normalize_pv_system_ids(raw_settings),
        import_tariff_id=str(raw_settings.get("import_tariff_id", "") or "").strip(),
        export_tariff_id=str(raw_settings.get("export_tariff_id", "") or "").strip(),
        house_profile_id=str(raw_settings.get("house_profile_id", "") or "").strip(),
        netzentgelt_cent_kwh_override=raw_settings.get("netzentgelt_cent_kwh_override"),
    )
    return {
        "label": str(scenario.get("label", "") or "").strip(),
        "settings": settings,
    }


def read_scenario_form_snapshot(
    session_state,
    session_scope: str,
    *,
    profiles: dict[str, dict],
    batteries: list[dict],
    pv_systems: list[dict],
    import_tariffs: list[dict],
    export_tariffs: list[dict],
) -> dict:
    _, prof_map = options_for_entities(list(profiles.values()), allow_none=True)
    _, bat_map = options_for_entities(batteries, allow_none=True)
    _, pv_map = options_for_entities(pv_systems, allow_none=True)
    _, imp_map = options_for_entities(import_tariffs, allow_none=True)
    _, exp_map = options_for_entities(export_tariffs, allow_none=True)

    profile_pick = session_state.get(scoped_widget_key(session_scope, "scenario_profile"))
    battery_pick = session_state.get(scoped_widget_key(session_scope, "scenario_battery"))
    pv_picks = session_state.get(scoped_widget_key(session_scope, "scenario_pv")) or []
    import_pick = session_state.get(scoped_widget_key(session_scope, "scenario_import"))
    export_pick = session_state.get(scoped_widget_key(session_scope, "scenario_export"))

    if isinstance(pv_picks, str):
        pv_picks = [pv_picks]
    pv_system_ids = [
        lookup_entity_id(pv_map, pick) for pick in pv_picks if lookup_entity_id(pv_map, pick)
    ]

    settings = build_scenario_settings(
        battery_id=lookup_entity_id(bat_map, battery_pick),
        pv_system_ids=pv_system_ids,
        import_tariff_id=lookup_entity_id(imp_map, import_pick),
        export_tariff_id=lookup_entity_id(exp_map, export_pick),
        house_profile_id=lookup_entity_id(prof_map, profile_pick),
        netzentgelt_cent_kwh_override=float(
            session_state.get(scoped_widget_key(session_scope, "scenario_netzentgelt"), 0.0) or 0.0
        ),
    )
    draft_label = str(
        session_state.get(scoped_widget_key(session_scope, "scenario_label"), "") or ""
    ).strip()
    return normalize_scenario_form_snapshot(
        {
            "label": draft_label,
            "settings": settings,
        },
    )


def store_scenario_form_baseline(
    session_state,
    session_scope: str,
    scenario: dict,
) -> None:
    session_state[scenario_baseline_key(session_scope)] = normalize_scenario_form_snapshot(
        scenario,
    )


def scenario_form_is_dirty(
    session_state,
    session_scope: str,
    *,
    profiles: dict[str, dict],
    batteries: list[dict],
    pv_systems: list[dict],
    import_tariffs: list[dict],
    export_tariffs: list[dict],
) -> bool:
    baseline = session_state.get(scenario_baseline_key(session_scope))
    if baseline is None:
        return False
    current = read_scenario_form_snapshot(
        session_state,
        session_scope,
        profiles=profiles,
        batteries=batteries,
        pv_systems=pv_systems,
        import_tariffs=import_tariffs,
        export_tariffs=export_tariffs,
    )
    return current != baseline


def render_entity_selectbox(
    label: str,
    items: list[dict],
    *,
    allow_none: bool = False,
    key: str,
    current_id: str | None = None,
) -> str | None:
    """Selectbox für Entitäten; bei leerer Liste deaktivierter Platzhalter, Rückgabe None."""
    labels, _mapping = options_for_entities(items, allow_none=allow_none)
    if not labels:
        placeholder = f"{EMPTY_PLACEHOLDER_PREFIX} {label.lower()} —"
        labeled_selectbox(
            label,
            options=[placeholder],
            disabled=True,
            key=key,
            format_func=format_entity_option,
        )
        return None
    if key in st.session_state and st.session_state[key] not in labels:
        del st.session_state[key]
    if key in st.session_state:
        return labeled_selectbox(
            label,
            options=labels,
            key=key,
            format_func=format_entity_option,
        )
    return labeled_selectbox(
        label,
        options=labels,
        index=default_label_index(labels, current_id),
        key=key,
        format_func=format_entity_option,
    )

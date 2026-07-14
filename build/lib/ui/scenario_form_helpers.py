"""Gemeinsame Hilfen für Szenario-Editor-Selectboxen und Entitäts-ID-Auflösung."""
from __future__ import annotations

import os

import streamlit as st

from house_config.id_slug import slug_id
from runtime_store.persist_paths import resolve_backtesting_scenarios_json_path

NONE_LABEL = "— keine —"
EMPTY_PLACEHOLDER_PREFIX = "— noch keine"
NEW_SCENARIO_OPTION = "— neu —"


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
        label = f"{item.get('label', item['id'])} ({item['id']})"
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
    pv_system_id: str,
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
    latitude: float | None = None,
    longitude: float | None = None,
    netzentgelt_cent_kwh_override: float | None = None,
) -> dict:
    settings: dict = {}
    if battery_id:
        settings["battery_id"] = battery_id
    if pv_system_id:
        settings["pv_system_id"] = pv_system_id
    if import_tariff_id:
        settings["import_tariff_id"] = import_tariff_id
    if export_tariff_id:
        settings["export_tariff_id"] = export_tariff_id
    if house_profile_id:
        settings["house_profile_id"] = house_profile_id
    if latitude is not None:
        settings["latitude"] = float(latitude)
    if longitude is not None:
        settings["longitude"] = float(longitude)
    if netzentgelt_cent_kwh_override is not None and netzentgelt_cent_kwh_override > 0.0:
        settings["netzentgelt_cent_kwh_override"] = float(netzentgelt_cent_kwh_override)
    return settings


def normalize_scenario_form_snapshot(scenario: dict) -> dict:
    settings = build_scenario_settings(
        battery_id=str(scenario.get("settings", {}).get("battery_id", "") or "").strip(),
        pv_system_id=str(scenario.get("settings", {}).get("pv_system_id", "") or "").strip(),
        import_tariff_id=str(scenario.get("settings", {}).get("import_tariff_id", "") or "").strip(),
        export_tariff_id=str(scenario.get("settings", {}).get("export_tariff_id", "") or "").strip(),
        house_profile_id=str(scenario.get("settings", {}).get("house_profile_id", "") or "").strip(),
        latitude=(
            float(scenario["settings"]["latitude"])
            if "latitude" in scenario.get("settings", {})
            else None
        ),
        longitude=(
            float(scenario["settings"]["longitude"])
            if "longitude" in scenario.get("settings", {})
            else None
        ),
        netzentgelt_cent_kwh_override=scenario.get("settings", {}).get(
            "netzentgelt_cent_kwh_override"
        ),
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
    pv_pick = session_state.get(scoped_widget_key(session_scope, "scenario_pv"))
    import_pick = session_state.get(scoped_widget_key(session_scope, "scenario_import"))
    export_pick = session_state.get(scoped_widget_key(session_scope, "scenario_export"))
    use_geo_override = bool(
        session_state.get(scoped_widget_key(session_scope, "scenario_geo_override"), False)
    )

    settings = build_scenario_settings(
        battery_id=lookup_entity_id(bat_map, battery_pick),
        pv_system_id=lookup_entity_id(pv_map, pv_pick),
        import_tariff_id=lookup_entity_id(imp_map, import_pick),
        export_tariff_id=lookup_entity_id(exp_map, export_pick),
        house_profile_id=lookup_entity_id(prof_map, profile_pick),
        latitude=(
            float(session_state.get(scoped_widget_key(session_scope, "scenario_lat"), 0.0))
            if use_geo_override
            else None
        ),
        longitude=(
            float(session_state.get(scoped_widget_key(session_scope, "scenario_lon"), 0.0))
            if use_geo_override
            else None
        ),
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
        st.selectbox(label, options=[placeholder], disabled=True, key=key)
        return None
    if key in st.session_state:
        return st.selectbox(label, options=labels, key=key)
    return st.selectbox(
        label,
        options=labels,
        index=default_label_index(labels, current_id),
        key=key,
    )

"""Gemeinsame Hilfen für Szenario-Editor-Selectboxen und Entitäts-ID-Auflösung."""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

import streamlit as st

from house_config.id_slug import slug_id
from runtime_store.persist_paths import resolve_backtesting_scenarios_json_path
from ui.form_layout import labeled_multiselect, labeled_selectbox

NONE_LABEL = "— keine —"
EMPTY_PLACEHOLDER_PREFIX = "— noch keine"
NEW_SCENARIO_OPTION = "— neu —"


def scenario_new_option(*, allow_new: bool) -> str | None:
    """Return ``— neu —`` when creating scenarios is allowed, else None."""
    return NEW_SCENARIO_OPTION if allow_new else None


def default_scenario_pick(
    *,
    live_id: str,
    scenario_ids: list[str],
    allow_new: bool,
) -> str:
    """Default Szenario select value; never ``— neu —`` when ``allow_new`` is False."""
    if live_id in scenario_ids:
        return live_id
    if scenario_ids:
        return scenario_ids[0]
    if allow_new:
        return NEW_SCENARIO_OPTION
    return live_id


def ordered_user_scenario_ids(
    scenario_ids: Iterable[str],
    *,
    live_scenario_id: str,
    labels: Mapping[str, str] | None = None,
) -> list[str]:
    """Live first, then remaining scenarios in input iteration order (file order).

    Display-order helper only — does not mutate JSON / file order.
    ``labels`` is accepted for call-site compatibility and ignored.
    """
    del labels  # API compat; order is file/array order, not label A–Z.
    unique = list(
        dict.fromkeys(str(sid).strip() for sid in scenario_ids if str(sid).strip())
    )
    live = str(live_scenario_id or "").strip()
    rest = [sid for sid in unique if sid != live]
    if live and live in unique:
        return [live, *rest]
    return rest


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
    """Build Bezeichnung options (display→id). No ``format_func`` — labels are the options."""
    labels: list[str] = []
    mapping: dict[str, str] = {}
    if allow_none:
        labels.append(NONE_LABEL)
        mapping[NONE_LABEL] = ""
    for item in items:
        human = entity_human_label(item)
        display = human
        if display in mapping:
            display = f"{human} ({item['id']})"
        labels.append(display)
        mapping[display] = item["id"]
    return labels, mapping


def default_label_index(
    options: list[str],
    item_id: str | None,
    mapping: dict[str, str] | None = None,
) -> int:
    if not item_id or not options:
        return 0
    if mapping:
        for index, opt in enumerate(options):
            if mapping.get(opt) == item_id:
                return index
    for index, opt in enumerate(options):
        if opt.endswith(f"({item_id})"):
            return index
        if opt == item_id:
            return index
    return 0


def lookup_entity_id(mapping: dict[str, str], pick: str | None) -> str:
    if pick is None:
        return ""
    return mapping.get(pick, "")


def _rematch_entity_option(
    current: str,
    labels: list[str],
    mapping: dict[str, str],
) -> str | None:
    """Map a stale widget value (old Bezeichnung or legacy ``Label (id)``) to a current option."""
    if current in labels:
        return current
    for display, entity_id in mapping.items():
        if not entity_id:
            continue
        if current == entity_id or current.endswith(f"({entity_id})"):
            return display
        # Legacy format_func era: option was id, display was label — already handled above
    return None


def format_entity_option(option: str) -> str:
    """Strip trailing `` (id)`` from legacy entity option keys for display.

    Prefer Bezeichnung-as-option (no format_func). Kept for back-compat callers/tests.
    """
    if option == NONE_LABEL or option.startswith(EMPTY_PLACEHOLDER_PREFIX):
        return option
    if option.endswith(")") and " (" in option:
        return option[: option.rfind(" (")]
    return option


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


# UI-only tariff filters — not part of scenario payload; keep across file reloads.
SCENARIO_FILTER_KEY_BASES = (
    "scenario_tariff_land",
    "scenario_import_filter_type",
    "scenario_export_filter_type",
)


def clear_scoped_widget_keys(
    session_scope: str,
    *,
    preserve_keys: set[str] | None = None,
) -> None:
    prefix = f"{session_scope}__"
    keep = preserve_keys or set()
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefix) and key not in keep:
            del st.session_state[key]


def seed_entity_select_state(
    session_scope: str,
    key_base: str,
    items: list[dict],
    current_id: str | None,
    *,
    allow_none: bool = False,
) -> None:
    labels, mapping = options_for_entities(items, allow_none=allow_none)
    if not labels:
        return
    idx = default_label_index(labels, current_id, mapping)
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
    container=None,
) -> list[str]:
    """Multiselect for entities; returns selected display labels."""
    root = container if container is not None else None
    labels, mapping = options_for_entities(items, allow_none=False)
    if not labels:
        placeholder = f"{EMPTY_PLACEHOLDER_PREFIX} {label.lower()} —"
        if root is not None:
            root.multiselect(label, options=[placeholder], disabled=True, key=key)
        else:
            labeled_multiselect(
                label,
                options=[placeholder],
                disabled=True,
                key=key,
            )
        return []
    if key in st.session_state:
        rematched = [
            matched
            for raw in list(st.session_state.get(key) or [])
            if (matched := _rematch_entity_option(str(raw), labels, mapping)) is not None
        ]
        st.session_state[key] = rematched
    else:
        st.session_state[key] = labels_for_entity_ids(items, list(current_ids or []))
    if root is not None:
        return list(root.multiselect(label, options=labels, key=key) or [])
    return list(
        labeled_multiselect(
            label,
            options=labels,
            key=key,
        )
        or []
    )


def new_scenario_template(
    scenarios: list[dict],
    *,
    source_id: str = "",
    live_id: str = "",
) -> dict:
    """Defaults for a new scenario — clone last selected (else Live) settings."""
    import copy

    from house_config.label_uniqueness import allocate_unique_label

    by_id = {
        str(item.get("id", "")).strip(): item
        for item in scenarios
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    source = by_id.get(str(source_id or "").strip()) or by_id.get(str(live_id or "").strip())
    if source is None:
        label = allocate_unique_label("Mein Szenario", scenarios)
        return {"label": label, "enabled": True, "settings": {}}

    source_label = str(source.get("label") or source.get("id") or "Szenario").strip()
    label = allocate_unique_label(f"{source_label} copy", scenarios)
    out: dict = {
        "label": label,
        "enabled": source.get("enabled", True) is not False,
        "settings": copy.deepcopy(dict(source.get("settings") or {})),
    }
    if "own_reference" in source:
        out["own_reference"] = bool(source.get("own_reference"))
    return out


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
    battery_ids: list[str] | None = None,
    battery_id: str | None = None,
    pv_system_ids: list[str] | None = None,
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
    use_imported_pv: bool = False,
    user_import_cent_kwh: float | None = None,
    user_export_cent_kwh: float | None = None,
) -> dict:
    from house_config.tariffs_store import (
        USER_EXPORT_CENT_KEY,
        USER_IMPORT_CENT_KEY,
        is_user_fixed_tariff_id,
    )

    settings: dict = {}
    cleaned_bat = [
        str(item or "").strip()
        for item in (battery_ids or [])
        if str(item or "").strip()
    ]
    if not cleaned_bat and battery_id:
        # Legacy kwarg from older call sites during transition
        legacy = str(battery_id or "").strip()
        if legacy:
            cleaned_bat = [legacy]
    if cleaned_bat:
        settings["battery_ids"] = cleaned_bat
    cleaned_pv = [
        str(item or "").strip()
        for item in (pv_system_ids or [])
        if str(item or "").strip()
    ]
    if cleaned_pv:
        settings["pv_system_ids"] = cleaned_pv
    if import_tariff_id:
        settings["import_tariff_id"] = import_tariff_id
        if is_user_fixed_tariff_id(import_tariff_id) and user_import_cent_kwh is not None:
            settings[USER_IMPORT_CENT_KEY] = float(user_import_cent_kwh)
    if export_tariff_id:
        settings["export_tariff_id"] = export_tariff_id
        if is_user_fixed_tariff_id(export_tariff_id) and user_export_cent_kwh is not None:
            settings[USER_EXPORT_CENT_KEY] = float(user_export_cent_kwh)
    if house_profile_id:
        settings["house_profile_id"] = house_profile_id
    if use_imported_pv:
        settings["use_imported_pv"] = True
    return settings


def _optional_user_cent(raw_settings: dict, key: str) -> float | None:
    if key not in raw_settings or raw_settings[key] is None:
        return None
    return float(raw_settings[key])


def normalize_scenario_form_snapshot(scenario: dict) -> dict:
    from house_config.entity_resolution import (
        normalize_battery_ids,
        normalize_pv_system_ids,
    )
    from house_config.tariffs_store import USER_EXPORT_CENT_KEY, USER_IMPORT_CENT_KEY

    raw_settings = scenario.get("settings", {}) or {}
    # Tolerate legacy battery_id in on-disk snapshots until migrate runs
    legacy_settings = dict(raw_settings)
    if "battery_id" in legacy_settings and "battery_ids" not in legacy_settings:
        bid = str(legacy_settings.pop("battery_id") or "").strip()
        legacy_settings["battery_ids"] = [bid] if bid else []
    settings = build_scenario_settings(
        battery_ids=normalize_battery_ids(legacy_settings),
        pv_system_ids=normalize_pv_system_ids(legacy_settings),
        import_tariff_id=str(raw_settings.get("import_tariff_id", "") or "").strip(),
        export_tariff_id=str(raw_settings.get("export_tariff_id", "") or "").strip(),
        house_profile_id=str(raw_settings.get("house_profile_id", "") or "").strip(),
        use_imported_pv=bool(raw_settings.get("use_imported_pv")),
        user_import_cent_kwh=_optional_user_cent(raw_settings, USER_IMPORT_CENT_KEY),
        user_export_cent_kwh=_optional_user_cent(raw_settings, USER_EXPORT_CENT_KEY),
    )
    out = {
        "label": str(scenario.get("label", "") or "").strip(),
        "enabled": scenario.get("enabled", True) is not False,
        "settings": settings,
    }
    if "own_reference" in scenario:
        out["own_reference"] = bool(scenario.get("own_reference"))
    return out


def _scenario_form_entity_maps(
    profiles: dict[str, dict],
    batteries: list[dict],
    pv_systems: list[dict],
    import_tariffs: list[dict],
    export_tariffs: list[dict],
) -> tuple[dict, dict, dict, dict, dict]:
    from house_config.tariffs_store import ensure_user_fixed_option

    _, prof_map = options_for_entities(list(profiles.values()), allow_none=True)
    _, bat_map = options_for_entities(batteries, allow_none=True)
    _, pv_map = options_for_entities(pv_systems, allow_none=True)
    import_with_user = ensure_user_fixed_option(import_tariffs)
    export_with_user = ensure_user_fixed_option(export_tariffs)
    _, imp_map = options_for_entities(import_with_user, allow_none=True)
    _, exp_map = options_for_entities(export_with_user, allow_none=True)
    return prof_map, bat_map, pv_map, imp_map, exp_map


def _user_cent_from_session(
    session_state,
    session_scope: str,
    *,
    tariff_id: str,
    widget_suffix: str,
) -> float | None:
    from house_config.tariffs_store import is_user_fixed_tariff_id

    if not is_user_fixed_tariff_id(tariff_id):
        return None
    raw = session_state.get(scoped_widget_key(session_scope, widget_suffix))
    if raw is None:
        return None
    return float(raw)


def _scenario_settings_from_session(
    session_state,
    session_scope: str,
    *,
    prof_map: dict,
    bat_map: dict,
    pv_map: dict,
    imp_map: dict,
    exp_map: dict,
) -> dict:
    profile_pick = session_state.get(scoped_widget_key(session_scope, "scenario_profile"))
    battery_picks = session_state.get(scoped_widget_key(session_scope, "scenario_battery")) or []
    pv_picks = session_state.get(scoped_widget_key(session_scope, "scenario_pv")) or []
    import_pick = session_state.get(scoped_widget_key(session_scope, "scenario_import"))
    export_pick = session_state.get(scoped_widget_key(session_scope, "scenario_export"))

    if isinstance(battery_picks, str):
        battery_picks = [battery_picks]
    if isinstance(pv_picks, str):
        pv_picks = [pv_picks]
    battery_ids = [
        lookup_entity_id(bat_map, pick)
        for pick in battery_picks
        if lookup_entity_id(bat_map, pick)
    ]
    pv_system_ids = [
        lookup_entity_id(pv_map, pick) for pick in pv_picks if lookup_entity_id(pv_map, pick)
    ]
    import_tariff_id = lookup_entity_id(imp_map, import_pick)
    export_tariff_id = lookup_entity_id(exp_map, export_pick)
    return build_scenario_settings(
        battery_ids=battery_ids,
        pv_system_ids=pv_system_ids,
        import_tariff_id=import_tariff_id,
        export_tariff_id=export_tariff_id,
        house_profile_id=lookup_entity_id(prof_map, profile_pick),
        use_imported_pv=bool(
            session_state.get(scoped_widget_key(session_scope, "scenario_use_imported_pv"), False)
        ),
        user_import_cent_kwh=_user_cent_from_session(
            session_state,
            session_scope,
            tariff_id=import_tariff_id,
            widget_suffix="scenario_user_import_cent",
        ),
        user_export_cent_kwh=_user_cent_from_session(
            session_state,
            session_scope,
            tariff_id=export_tariff_id,
            widget_suffix="scenario_user_export_cent",
        ),
    )


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
    prof_map, bat_map, pv_map, imp_map, exp_map = _scenario_form_entity_maps(
        profiles, batteries, pv_systems, import_tariffs, export_tariffs
    )
    settings = _scenario_settings_from_session(
        session_state,
        session_scope,
        prof_map=prof_map,
        bat_map=bat_map,
        pv_map=pv_map,
        imp_map=imp_map,
        exp_map=exp_map,
    )
    draft_label = str(
        session_state.get(scoped_widget_key(session_scope, "scenario_label"), "") or ""
    ).strip()
    snapshot_src: dict = {
        "label": draft_label,
        "enabled": bool(
            session_state.get(scoped_widget_key(session_scope, "scenario_enabled"), True)
        ),
        "settings": settings,
    }
    own_ref_key = scoped_widget_key(session_scope, "scenario_own_reference")
    if own_ref_key in session_state:
        snapshot_src["own_reference"] = bool(session_state.get(own_ref_key))
    return normalize_scenario_form_snapshot(snapshot_src)


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
    container=None,
) -> str | None:
    """Selectbox für Entitäten; bei leerer Liste deaktivierter Platzhalter, Rückgabe None."""
    root = container if container is not None else None
    labels, mapping = options_for_entities(items, allow_none=allow_none)
    if not labels:
        placeholder = f"{EMPTY_PLACEHOLDER_PREFIX} {label.lower()} —"
        if root is not None:
            root.selectbox(label, options=[placeholder], disabled=True, key=key)
        else:
            labeled_selectbox(
                label,
                options=[placeholder],
                disabled=True,
                key=key,
            )
        return None
    if key in st.session_state:
        rematched = _rematch_entity_option(str(st.session_state[key]), labels, mapping)
        if rematched is None:
            del st.session_state[key]
        elif rematched != st.session_state[key]:
            st.session_state[key] = rematched
    if root is not None:
        if key in st.session_state:
            return root.selectbox(label, options=labels, key=key)
        return root.selectbox(
            label,
            options=labels,
            index=default_label_index(labels, current_id, mapping),
            key=key,
        )
    if key in st.session_state:
        return labeled_selectbox(
            label,
            options=labels,
            key=key,
        )
    return labeled_selectbox(
        label,
        options=labels,
        index=default_label_index(labels, current_id, mapping),
        key=key,
    )

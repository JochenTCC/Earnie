"""Runtime-Szenario (Baseline): Entitäts-Referenzen in runtime_settings."""
from __future__ import annotations

import streamlit as st

import config
from ui.house_config_io import (
    get_runtime_scenario_refs,
    list_batteries,
    list_export_tariffs,
    list_import_tariffs,
    list_pv_systems,
    load_house_profiles,
    save_runtime_scenario_refs,
)
from ui.planning_tariff_form import (
    _EXPORT_TYPE_LABELS,
    _IMPORT_TYPE_LABELS,
    _tariff_meta_caption,
    _type_caption,
)


def _options(items: list[dict], *, allow_none: bool = False) -> tuple[list[str], dict[str, str]]:
    labels: list[str] = []
    mapping: dict[str, str] = {}
    if allow_none:
        labels.append("— keine —")
        mapping["— keine —"] = ""
    for item in items:
        label = f"{item.get('label', item['id'])} ({item['id']})"
        labels.append(label)
        mapping[label] = item["id"]
    return labels, mapping


def _default_label(options: list[str], item_id: str | None) -> int:
    if not item_id:
        return 0
    for index, opt in enumerate(options):
        if opt.endswith(f"({item_id})"):
            return index
    return 0


def render_runtime_scenario_form() -> None:
    st.subheader("Runtime (Betrieb & Baseline)")
    st.caption(
        "Pflicht-Szenario für Backtesting und späteren Live-Betrieb. "
        "Speichert nach `config.json` → `runtime_settings`."
    )

    refs = get_runtime_scenario_refs()
    batteries = list_batteries()
    pv_systems = list_pv_systems()
    import_tariffs = list_import_tariffs()
    export_tariffs = list_export_tariffs()
    profiles = load_house_profiles().get("profiles", {})

    if not batteries:
        st.warning("Zuerst mindestens eine Batterie unter Tab „Batterien“ anlegen.")
    if not pv_systems:
        st.warning("Zuerst eine PV-Anlage im Hauskonfigurator anlegen.")
    if not profiles:
        st.warning("Zuerst ein Hausprofil im Hauskonfigurator anlegen.")

    bat_labels, bat_map = _options(batteries)
    pv_labels, pv_map = _options(pv_systems, allow_none=True)
    imp_labels, imp_map = _options(import_tariffs)
    exp_labels, exp_map = _options(export_tariffs)
    prof_labels, prof_map = _options(list(profiles.values()))

    battery_pick = st.selectbox(
        "Batterie",
        options=bat_labels,
        index=_default_label(bat_labels, refs.get("battery_id")),
        key="runtime_battery",
    )
    pv_pick = st.selectbox(
        "PV-Anlage",
        options=pv_labels,
        index=_default_label(pv_labels, refs.get("pv_system_id")),
        key="runtime_pv",
    )
    imp_pick = st.selectbox(
        "Bezugstarif",
        options=imp_labels,
        index=_default_label(imp_labels, refs.get("import_tariff_id")),
        key="runtime_import",
    )
    exp_pick = st.selectbox(
        "Einspeisetarif",
        options=exp_labels,
        index=_default_label(exp_labels, refs.get("export_tariff_id")),
        key="runtime_export",
    )

    selected_import = imp_map[imp_pick]
    selected_export = exp_map[exp_pick]
    if selected_import:
        import_tariff = next(t for t in import_tariffs if t["id"] == selected_import)
        st.caption(
            f"Bezug: {_type_caption(import_tariff, _IMPORT_TYPE_LABELS)}"
            + (f" · {_tariff_meta_caption(import_tariff)}" if _tariff_meta_caption(import_tariff) else "")
        )
    if selected_export:
        export_tariff = next(t for t in export_tariffs if t["id"] == selected_export)
        st.caption(
            f"Einspeise: {_type_caption(export_tariff, _EXPORT_TYPE_LABELS)}"
            + (f" · {_tariff_meta_caption(export_tariff)}" if _tariff_meta_caption(export_tariff) else "")
        )

    prof_pick = st.selectbox(
        "Hausprofil",
        options=prof_labels,
        index=_default_label(prof_labels, refs.get("house_profile_id")),
        key="runtime_profile",
    )

    selected_profile_id = prof_map[prof_pick]
    selected_profile = profiles.get(selected_profile_id, {})
    if (
        selected_profile_id
        and st.session_state.get("runtime_geo_profile_id") != selected_profile_id
    ):
        st.session_state.runtime_geo_profile_id = selected_profile_id
        st.session_state.runtime_lat = float(
            selected_profile.get("latitude", refs.get("latitude", 48.2))
        )
        st.session_state.runtime_lon = float(
            selected_profile.get("longitude", refs.get("longitude", 16.37))
        )
    if "runtime_lat" not in st.session_state:
        st.session_state.runtime_lat = float(refs.get("latitude", 48.2))
    if "runtime_lon" not in st.session_state:
        st.session_state.runtime_lon = float(refs.get("longitude", 16.37))
    if "runtime_geo_profile_id" not in st.session_state:
        st.session_state.runtime_geo_profile_id = selected_profile_id

    col_a, col_b = st.columns(2)
    latitude = col_a.number_input(
        "Breitengrad",
        key="runtime_lat",
    )
    longitude = col_b.number_input(
        "Längengrad",
        key="runtime_lon",
    )

    if st.button("Auflösung testen", key="runtime_preview"):
        draft = _build_runtime_settings(
            battery_id=bat_map[battery_pick],
            pv_system_id=pv_map[pv_pick],
            import_tariff_id=imp_map[imp_pick],
            export_tariff_id=exp_map[exp_pick],
            house_profile_id=prof_map[prof_pick],
            latitude=latitude,
            longitude=longitude,
        )
        try:
            resolved = config.CONFIG.resolve_scenario_settings_dict(draft)
            st.json({k: v for k, v in resolved.items() if not k.startswith("_")})
        except ValueError as exc:
            st.error(str(exc))

    if st.button("Runtime speichern", type="primary", key="runtime_save"):
        if not bat_map[battery_pick]:
            st.error("Batterie auswählen.")
        elif not imp_map[imp_pick] or not exp_map[exp_pick]:
            st.error("Bezugs- und Einspeisetarif auswählen.")
        elif not prof_map[prof_pick]:
            st.error("Hausprofil auswählen.")
        else:
            save_runtime_scenario_refs(
                battery_id=bat_map[battery_pick],
                pv_system_id=pv_map[pv_pick],
                import_tariff_id=imp_map[imp_pick],
                export_tariff_id=exp_map[exp_pick],
                house_profile_id=prof_map[prof_pick],
                latitude=latitude,
                longitude=longitude,
                timezone_name=str(refs.get("timezone_name", "Europe/Vienna")),
            )
            st.success("Runtime-Szenario gespeichert.")
            st.rerun()


def _build_runtime_settings(
    *,
    battery_id: str,
    pv_system_id: str,
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
    latitude: float,
    longitude: float,
) -> dict:
    settings: dict = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone_name": "Europe/Vienna",
    }
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
    return settings

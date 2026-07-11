"""Szenarieneditor: Runtime-Baseline, Batterien und weitere Backtesting-Szenarien."""
from __future__ import annotations

import streamlit as st

import config
from ui.help_hint import render_page_title_with_help
from ui.house_config_io import (
    list_batteries,
    list_export_tariffs,
    list_import_tariffs,
    list_pv_systems,
    load_backtesting_scenarios_raw,
    load_house_profiles,
    load_tariffs_catalog_meta,
    upsert_scenario,
)
from ui.planning_battery_form import render_battery_planning_tab
from ui.planning_tariff_form import (
    _EXPORT_TYPE_LABELS,
    _IMPORT_TYPE_LABELS,
    _tariff_meta_caption,
    _type_caption,
)
from ui.scenario_form_helpers import (
    lookup_entity_id,
    options_for_entities,
    render_entity_selectbox,
    render_profile_geo_caption,
)
from ui.scenario_runtime_form import render_runtime_scenario_form

_HELP = (
    "Runtime-Szenario (Pflicht), Batterie-Entitäten und optionale weitere "
    "Backtesting-Varianten. Speichert Runtime nach `config.json`, "
    "weitere Szenarien nach `config/backtesting_scenarios.json`."
)


def _render_additional_scenarios_tab() -> None:
    st.subheader("Weitere Szenarien")
    st.caption("Optionale Varianten mit anderen Batterien oder Tarifen (zusätzlich zu Runtime).")

    scenarios_doc = load_backtesting_scenarios_raw()
    scenarios = scenarios_doc.get("scenarios", [])
    scenario_ids = [s.get("id", "") for s in scenarios]
    selected = st.selectbox(
        "Szenario",
        options=["— neu —", *scenario_ids],
        key="scenario_select",
    )
    existing = next((s for s in scenarios if s.get("id") == selected), None)
    if selected == "— neu —":
        existing = None

    scenario_id = st.text_input(
        "Szenario-ID",
        value=(existing or {}).get("id", "mein_szenario"),
        key="scenario_id",
    )
    label = st.text_input(
        "Bezeichnung",
        value=(existing or {}).get("label", "Mein Szenario"),
        key="scenario_label",
    )

    settings = dict((existing or {}).get("settings", {}))
    batteries = list_batteries()
    pv_systems = list_pv_systems()
    import_tariffs = list_import_tariffs()
    export_tariffs = list_export_tariffs()
    profiles = load_house_profiles().get("profiles", {})

    _, bat_map = options_for_entities(batteries, allow_none=True)
    _, pv_map = options_for_entities(pv_systems, allow_none=True)
    _, imp_map = options_for_entities(import_tariffs, allow_none=True)
    _, exp_map = options_for_entities(export_tariffs, allow_none=True)
    _, prof_map = options_for_entities(list(profiles.values()), allow_none=True)

    required_lists_empty = not (import_tariffs and export_tariffs and profiles)

    battery_pick = render_entity_selectbox(
        "Batterie",
        batteries,
        allow_none=True,
        key="scenario_battery",
        current_id=settings.get("battery_id"),
    )
    pv_pick = render_entity_selectbox(
        "PV-Anlage",
        pv_systems,
        allow_none=True,
        key="scenario_pv",
        current_id=settings.get("pv_system_id"),
    )
    imp_pick = render_entity_selectbox(
        "Bezugstarif",
        import_tariffs,
        allow_none=True,
        key="scenario_import",
        current_id=settings.get("import_tariff_id"),
    )
    exp_pick = render_entity_selectbox(
        "Einspeisetarif",
        export_tariffs,
        allow_none=True,
        key="scenario_export",
        current_id=settings.get("export_tariff_id"),
    )
    selected_import = lookup_entity_id(imp_map, imp_pick)
    selected_export = lookup_entity_id(exp_map, exp_pick)
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

    netzentgelt_override = None
    if selected_import:
        import_tariff = next(t for t in import_tariffs if t["id"] == selected_import)
        if import_tariff.get("land") == "DE" and import_tariff.get("type") in {
            "spot_hourly",
            "ex_post_spot",
            "monthly_market",
        }:
            netzentgelt_override = st.number_input(
                "Netzentgelt-Override (Cent/kWh, DE-Spot)",
                min_value=0.0,
                value=float(settings.get("netzentgelt_cent_kwh_override", 0.0) or 0.0),
                step=0.1,
                key="scenario_netzentgelt",
            )

    prof_pick = render_entity_selectbox(
        "Hausprofil",
        list(profiles.values()),
        allow_none=True,
        key="scenario_profile",
        current_id=settings.get("house_profile_id"),
    )

    selected_profile_id = lookup_entity_id(prof_map, prof_pick)
    selected_profile = profiles.get(selected_profile_id, {})
    if selected_profile:
        render_profile_geo_caption(selected_profile)

    with st.expander("Standort-Override (optional, Backtesting)", expanded=False):
        st.caption(
            "Nur für What-if-Szenarien. Leer lassen = Standort/Zeitzone aus Hausprofil."
        )
        default_lat = float(
            settings.get("latitude", selected_profile.get("latitude", 48.0))
        )
        default_lon = float(
            settings.get("longitude", selected_profile.get("longitude", 10.0))
        )
        col_a, col_b = st.columns(2)
        latitude = col_a.number_input(
            "Breitengrad (Override)",
            value=default_lat,
            key="scenario_lat",
        )
        longitude = col_b.number_input(
            "Längengrad (Override)",
            value=default_lon,
            key="scenario_lon",
        )
        use_geo_override = st.checkbox(
            "Standort-Override in Szenario speichern",
            value="latitude" in settings or "longitude" in settings,
            key="scenario_geo_override",
        )

    if st.button("Auflösung testen", key="scenario_preview", disabled=required_lists_empty):
        draft = _build_settings(
            battery_id=lookup_entity_id(bat_map, battery_pick),
            pv_system_id=lookup_entity_id(pv_map, pv_pick),
            import_tariff_id=lookup_entity_id(imp_map, imp_pick),
            export_tariff_id=lookup_entity_id(exp_map, exp_pick),
            house_profile_id=lookup_entity_id(prof_map, prof_pick),
            latitude=latitude if use_geo_override else None,
            longitude=longitude if use_geo_override else None,
            netzentgelt_cent_kwh_override=netzentgelt_override,
        )
        try:
            resolved = config.CONFIG.resolve_scenario_settings_dict(draft)
            st.json({k: v for k, v in resolved.items() if not k.startswith("_")})
        except ValueError as exc:
            st.error(str(exc))

    if st.button(
        "Szenario speichern",
        type="primary",
        key="scenario_save",
        disabled=required_lists_empty,
    ):
        if not scenario_id.strip():
            st.error("Szenario-ID fehlt.")
        elif scenario_id.strip() == "runtime_settings":
            st.error("Die ID 'runtime_settings' ist reserviert.")
        else:
            upsert_scenario(
                {
                    "id": scenario_id.strip(),
                    "label": label.strip() or scenario_id.strip(),
                    "settings": _build_settings(
                        battery_id=lookup_entity_id(bat_map, battery_pick),
                        pv_system_id=lookup_entity_id(pv_map, pv_pick),
                        import_tariff_id=lookup_entity_id(imp_map, imp_pick),
                        export_tariff_id=lookup_entity_id(exp_map, exp_pick),
                        house_profile_id=lookup_entity_id(prof_map, prof_pick),
                        latitude=latitude if use_geo_override else None,
                        longitude=longitude if use_geo_override else None,
                        netzentgelt_cent_kwh_override=netzentgelt_override,
                    ),
                }
            )
            st.success(f"Szenario '{scenario_id}' gespeichert.")
            st.rerun()


def _build_settings(
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


def render() -> None:
    render_page_title_with_help("🧪 Szenarieneditor", _HELP, key="scenario_editor_help")

    catalog_meta = load_tariffs_catalog_meta()
    if catalog_meta.get("catalog_as_of"):
        st.caption(f"Tarifkatalog: Stand {catalog_meta['catalog_as_of']}")

    tab_runtime, tab_battery, tab_more = st.tabs(
        ["Runtime (Baseline)", "Batterien", "Weitere Szenarien"]
    )
    with tab_runtime:
        render_runtime_scenario_form()
    with tab_battery:
        render_battery_planning_tab()
    with tab_more:
        _render_additional_scenarios_tab()

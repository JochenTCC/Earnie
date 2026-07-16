"""Komfort-Formular für das Live-Szenario: Entitäts-IDs speichern, Werte nur lesend."""
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
from ui.tariff_filter_helpers import (
    EXPORT_TYPE_LABELS,
    IMPORT_TYPE_LABELS,
    render_tariff_filter_row,
    tariff_meta_caption,
    type_caption,
)
from ui.runtime_config import invalidate_live_optimization_cache
from ui.form_layout import labeled_selectbox
from ui.scenario_form_helpers import (
    lookup_entity_id,
    options_for_entities,
    render_entity_multiselect,
    render_entity_selectbox,
    render_profile_geo_caption,
)


def _render_resolved_snapshot(resolved: dict) -> None:
    """Zeigt aufgelöste PV-/Batterie-/Tarif-/Standort-Parameter read-only."""
    st.markdown("#### Aufgelöste Parameter (nur Anzeige)")
    st.caption(
        "Technische Werte aus components.json (batteries[], pv_systems[]), tariffs.json und Hausprofil. "
        "Bearbeiten im Hauskonfigurator, Szenarieneditor oder Echtzeit-Umgebung."
    )

    geo_cols = st.columns(3)
    geo_cols[0].metric("Breitengrad", f"{float(resolved.get('latitude', 0.0)):.4f}")
    geo_cols[1].metric("Längengrad", f"{float(resolved.get('longitude', 0.0)):.4f}")
    geo_cols[2].metric("Zeitzone", str(resolved.get("timezone_name", "Europe/Vienna")))

    pv_cols = st.columns(3)
    planning = resolved.get("_planning_pv_systems") or []
    pv_cols[0].metric("PV Leistung (kWp)", f"{float(resolved.get('pv_kwp', 0.0)):.2f}")
    if len(planning) == 1:
        pv_cols[1].metric("Dachneigung (°)", f"{float(resolved.get('pv_tilt', 0.0)):.0f}")
        pv_cols[2].metric(
            "Ausrichtung Azimut (°)",
            f"{float(resolved.get('pv_azimuth', 0.0)):.0f}",
        )
    elif len(planning) > 1:
        pv_cols[1].metric("PV-Anlagen", str(len(planning)))
        labels = ", ".join(
            str(item.get("label") or item.get("id") or "?") for item in planning
        )
        pv_cols[2].caption(labels)
    else:
        pv_cols[1].metric("Dachneigung (°)", "—")
        pv_cols[2].metric("Ausrichtung Azimut (°)", "—")

    bat_cols = st.columns(4)
    bat_cols[0].metric(
        "Speicher-Kapazität (kWh)",
        f"{float(resolved.get('battery_capacity_kwh', 0.0)):.1f}",
    )
    bat_cols[1].metric(
        "Min. SoC (%)",
        f"{float(resolved.get('battery_min_soc', 0.0)):.0f}",
    )
    bat_cols[2].metric(
        "Max. SoC (%)",
        f"{float(resolved.get('battery_max_soc', 0.0)):.0f}",
    )
    bat_cols[3].metric(
        "Max. Lade-/Entladeleistung (kW)",
        f"{float(resolved.get('battery_max_power_kw', 0.0)):.2f}",
    )

    tariff_cols = st.columns(2)
    tariff_cols[0].metric(
        "Einspeisevergütung (Cent/kWh)",
        f"{float(resolved.get('k_push_cent', 0.0)):.2f}",
    )
    threshold = float(resolved.get("threshold_power", 0.0)) * 100.0
    tariff_cols[1].metric("Leistungs-Schwelle (%)", f"{threshold:.0f}")

    export_spec = resolved.get("_export_tariff_spec")
    import_spec = resolved.get("_import_tariff_spec")
    if import_spec:
        st.caption(
            "Bezug: "
            + type_caption(import_spec, IMPORT_TYPE_LABELS)
            + (
                f" · {tariff_meta_caption(import_spec)}"
                if tariff_meta_caption(import_spec)
                else ""
            )
        )
    if export_spec:
        st.caption(
            "Einspeise: "
            + type_caption(export_spec, EXPORT_TYPE_LABELS)
            + (
                f" · {tariff_meta_caption(export_spec)}"
                if tariff_meta_caption(export_spec)
                else ""
            )
        )


def render_runtime_entity_form_body() -> None:
    """ID-Auswahl für das Live-Szenario im Seiten-Body (Komfort-Ansicht)."""
    refs = get_runtime_scenario_refs()
    batteries = list_batteries()
    pv_systems = list_pv_systems()
    import_tariffs = list_import_tariffs()
    export_tariffs = list_export_tariffs()
    profiles = load_house_profiles().get("profiles", {})

    _, bat_map = options_for_entities(batteries)
    _, pv_map = options_for_entities(pv_systems, allow_none=True)
    _, imp_map = options_for_entities(import_tariffs)
    _, exp_map = options_for_entities(export_tariffs)
    _, prof_map = options_for_entities(list(profiles.values()))

    required_lists_empty = not (
        batteries and import_tariffs and export_tariffs and profiles
    )

    if not batteries:
        st.warning("Zuerst mindestens eine Batterie im Szenarieneditor anlegen.")
    if not pv_systems:
        st.warning("Optional: PV-Anlage im Hauskonfigurator anlegen.")
    if not import_tariffs or not export_tariffs:
        st.warning("Tarifkatalog leer — tariffs.json prüfen.")
    if not profiles:
        st.warning("Zuerst ein Hausprofil im Hauskonfigurator anlegen.")

    current_import_id = str(refs.get("import_tariff_id") or "").strip() or None
    current_export_id = str(refs.get("export_tariff_id") or "").strip() or None
    st.caption("Filter Bezugstarife")
    filtered_imports = render_tariff_filter_row(
        key_prefix="config_runtime_import_filter",
        tariffs=import_tariffs,
        kind="import",
        current_id=current_import_id,
        label_prefix="Bezug ",
    )
    st.caption("Filter Einspeisetarife")
    filtered_exports = render_tariff_filter_row(
        key_prefix="config_runtime_export_filter",
        tariffs=export_tariffs,
        kind="export",
        current_id=current_export_id,
        label_prefix="Einspeise ",
    )

    with st.form("runtime_entity_form"):
        battery_pick = render_entity_selectbox(
            "Batterie",
            batteries,
            key="config_runtime_battery",
            current_id=refs.get("battery_id"),
        )
        pv_picks = render_entity_multiselect(
            "PV-Anlagen",
            pv_systems,
            key="config_runtime_pv",
            current_ids=list(refs.get("pv_system_ids") or []),
        )
        imp_pick = render_entity_selectbox(
            "Bezugstarif",
            filtered_imports,
            key="config_runtime_import",
            current_id=current_import_id,
        )
        exp_pick = render_entity_selectbox(
            "Einspeisetarif",
            filtered_exports,
            key="config_runtime_export",
            current_id=current_export_id,
        )
        prof_pick = render_entity_selectbox(
            "Hausprofil",
            list(profiles.values()),
            key="config_runtime_profile",
            current_id=refs.get("house_profile_id"),
        )

        submit_btn = st.form_submit_button(
            "Entitäts-Referenzen speichern",
            disabled=required_lists_empty,
        )
        if submit_btn:
            battery_id = lookup_entity_id(bat_map, battery_pick)
            import_id = lookup_entity_id(imp_map, imp_pick)
            export_id = lookup_entity_id(exp_map, exp_pick)
            profile_id = lookup_entity_id(prof_map, prof_pick)
            if not battery_id:
                st.error("Batterie auswählen.")
            elif not import_id or not export_id:
                st.error("Bezugs- und Einspeisetarif auswählen.")
            elif not profile_id:
                st.error("Hausprofil auswählen.")
            else:
                save_runtime_scenario_refs(
                    battery_id=battery_id,
                    pv_system_ids=[
                        lookup_entity_id(pv_map, pick)
                        for pick in pv_picks
                        if lookup_entity_id(pv_map, pick)
                    ],
                    import_tariff_id=import_id,
                    export_tariff_id=export_id,
                    house_profile_id=profile_id,
                )
                invalidate_live_optimization_cache()
                st.success("Live-Szenario-Referenzen gespeichert.")
                st.rerun()

    selected_profile_id = refs.get("house_profile_id")
    if selected_profile_id:
        render_profile_geo_caption(profiles.get(selected_profile_id, {}))
        st.caption("Standort/Zeitzone im Hauskonfigurator bearbeiten.")

    if not config.is_runtime_params_deferred():
        try:
            resolved = config.get_resolved_runtime_settings()
            _render_resolved_snapshot(resolved)
        except ValueError as exc:
            st.error(str(exc))


def _render_live_scenario_id_picker() -> None:
    """Wählt live_scenario_id in config.json aus vorhandenen Szenarien."""
    from ui.house_config_io import load_backtesting_scenarios_raw, save_live_scenario_id

    scenarios_doc = load_backtesting_scenarios_raw()
    scenarios = [
        item
        for item in scenarios_doc.get("scenarios", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    ]
    if not scenarios:
        st.warning("Zuerst mindestens ein Szenario im Szenarieneditor anlegen.")
        return

    scenario_ids = [str(item["id"]).strip() for item in scenarios]
    labels = {
        str(item["id"]).strip(): str(item.get("label") or item["id"]).strip()
        for item in scenarios
    }
    current = config.get_live_scenario_id()
    pick = labeled_selectbox(
        "Live-Szenario",
        options=scenario_ids,
        index=scenario_ids.index(current) if current in scenario_ids else 0,
        format_func=lambda sid: labels.get(sid, sid),
        key="live_environment_scenario_picker",
    )
    if pick != current:
        if st.button("Als Live-Szenario übernehmen", type="primary"):
            save_live_scenario_id(pick)
            invalidate_live_optimization_cache()
            st.success("Live-Szenario übernommen.")
            st.rerun()
    else:
        st.caption("Aktives Live-Szenario (siehe Auswahl oben).")


def render_live_environment_section() -> None:
    """Echtzeit-Umgebung: Live-Szenario wählen, Entitäts-Referenzen, Auflösung read-only."""
    _render_live_scenario_id_picker()
    if config.is_runtime_params_deferred():
        st.info(
            "PV- und Batterie-Parameter werden nach Abschluss der Planungs-Konfiguration "
            "aus den gewählten Entitäten aufgelöst. Bitte Hauskonfigurator, Szenarieneditor "
            "und diese Seite nutzen."
        )
        render_runtime_entity_form_body()
        return

    st.markdown(
        "Entitäts-Referenzen für das Live-Szenario in "
        "`backtesting_scenarios.json`. Standort und Zeitzone kommen aus dem Hausprofil."
    )
    render_runtime_entity_form_body()


def render_system_parameter_section() -> None:
    """Alias für render_live_environment_section (API-Stabilität, z. B. page_config)."""
    render_live_environment_section()

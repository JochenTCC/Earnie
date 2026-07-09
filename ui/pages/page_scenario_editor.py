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
from ui.scenario_runtime_form import render_runtime_scenario_form

_HELP = (
    "Runtime-Szenario (Pflicht), Batterie-Entitäten und optionale weitere "
    "Backtesting-Varianten. Speichert Runtime nach `config.json`, "
    "weitere Szenarien nach `config/backtesting_scenarios.json`."
)


def _options(items: list[dict], *, allow_none: bool = True) -> tuple[list[str], dict[str, str]]:
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

    bat_labels, bat_map = _options(batteries)
    pv_labels, pv_map = _options(pv_systems)
    imp_labels, imp_map = _options(import_tariffs)
    exp_labels, exp_map = _options(export_tariffs)
    prof_labels, prof_map = _options(list(profiles.values()))

    battery_pick = st.selectbox(
        "Batterie",
        options=bat_labels,
        index=_default_label(bat_labels, settings.get("battery_id")),
        key="scenario_battery",
    )
    pv_pick = st.selectbox(
        "PV-Anlage",
        options=pv_labels,
        index=_default_label(pv_labels, settings.get("pv_system_id")),
        key="scenario_pv",
    )
    imp_pick = st.selectbox(
        "Bezugstarif",
        options=imp_labels,
        index=_default_label(imp_labels, settings.get("import_tariff_id")),
        key="scenario_import",
    )
    exp_pick = st.selectbox(
        "Einspeisetarif",
        options=exp_labels,
        index=_default_label(exp_labels, settings.get("export_tariff_id")),
        key="scenario_export",
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

    prof_pick = st.selectbox(
        "Hausprofil",
        options=prof_labels,
        index=_default_label(prof_labels, settings.get("house_profile_id")),
        key="scenario_profile",
    )

    runtime = config.CONFIG._raw_config.get("runtime_settings", {})
    col_a, col_b = st.columns(2)
    latitude = col_a.number_input(
        "Breitengrad",
        value=float(settings.get("latitude", runtime.get("latitude", 48.0))),
        key="scenario_lat",
    )
    longitude = col_b.number_input(
        "Längengrad",
        value=float(settings.get("longitude", runtime.get("longitude", 10.0))),
        key="scenario_lon",
    )

    if st.button("Auflösung testen", key="scenario_preview"):
        draft = _build_settings(
            battery_id=bat_map[battery_pick],
            pv_system_id=pv_map[pv_pick],
            import_tariff_id=imp_map[imp_pick],
            export_tariff_id=exp_map[exp_pick],
            house_profile_id=prof_map[prof_pick],
            latitude=latitude,
            longitude=longitude,
            netzentgelt_cent_kwh_override=netzentgelt_override,
        )
        try:
            resolved = config.CONFIG.resolve_scenario_settings_dict(draft)
            st.json({k: v for k, v in resolved.items() if not k.startswith("_")})
        except ValueError as exc:
            st.error(str(exc))

    if st.button("Szenario speichern", type="primary", key="scenario_save"):
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
                        battery_id=bat_map[battery_pick],
                        pv_system_id=pv_map[pv_pick],
                        import_tariff_id=imp_map[imp_pick],
                        export_tariff_id=exp_map[exp_pick],
                        house_profile_id=prof_map[prof_pick],
                        latitude=latitude,
                        longitude=longitude,
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
    latitude: float,
    longitude: float,
    netzentgelt_cent_kwh_override: float | None = None,
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

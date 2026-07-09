"""Szenarieneditor: Tarif-, PV-, Batterie- und Hausprofil-Auswahl für Backtesting."""
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
    upsert_scenario,
)

_HELP = (
    "Backtesting-Szenarien aus Entitäten zusammenstellen: "
    "Tarif (Bezug/Einspeise), PV, Batterie, optional Hausprofil. "
    "Speichert nach `config/backtesting_scenarios.json`."
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


def render() -> None:
    render_page_title_with_help("🧪 Szenarieneditor", _HELP, key="scenario_editor_help")

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

    def _default_label(options: list[str], item_id: str | None) -> int:
        if not item_id:
            return 0
        for index, opt in enumerate(options):
            if opt.endswith(f"({item_id})"):
                return index
        return 0

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
        )
        try:
            resolved = config.CONFIG.resolve_scenario_settings_dict(draft)
            st.json(
                {
                    k: v
                    for k, v in resolved.items()
                    if not k.startswith("_")
                }
            )
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

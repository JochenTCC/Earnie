"""Persistenz-Hilfen für Hauskonfigurator und Szenarienkonfigurator."""
from __future__ import annotations

import json
import os
from pathlib import Path

import config
from house_config.id_slug import slug_id
from house_config.profiles_store import (
    load_house_profiles_document,
    save_house_profiles_document,
)
from house_config.tariffs_store import append_monthly_rate, load_tariffs_document
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_components_json_path,
    resolve_config_json_path,
    resolve_house_profiles_json_path,
    resolve_tariffs_json_path,
    resolve_uploads_dir,
)
from settings.json_io import read_json_dict, write_json_dict

def read_json_document(path: str) -> dict:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return json.loads(Path(path).read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Datei '{path}' ist weder UTF-8 noch cp1252 lesbar.")

def write_json_document(path: str, data: dict) -> None:
    from runtime_store.data_model import stamp_data_model

    stamp_data_model(data)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, target)

def load_house_profiles() -> dict:
    return load_house_profiles_document(resolve_house_profiles_json_path())

def house_doc_for_save(doc: dict) -> dict:
    """Normalize in-memory house doc (profiles dict|list) for ``save_house_profiles_document``."""
    profiles = doc.get("profiles")
    if isinstance(profiles, dict):
        profile_list = list(profiles.values())
    elif isinstance(profiles, list):
        profile_list = list(profiles)
    else:
        profile_list = []
    from house_config.required_signal_activation import activate_plant_required

    out: dict = {"profiles": profile_list}
    plant = doc.get("plant")
    if isinstance(plant, dict) and plant:
        out["plant"] = activate_plant_required(dict(plant))
    if "earnie_data_model" in doc:
        out["earnie_data_model"] = doc["earnie_data_model"]
    return out

def save_house_profiles(doc: dict) -> None:
    payload = merge_inline_heating_systems(
        house_doc_for_save(doc), read_existing=resolve_house_profiles_json_path()
    )
    payload = route_ev_wallboxes_for_save(payload)
    save_house_profiles_document(resolve_house_profiles_json_path(), payload)


def route_ev_wallboxes_for_save(doc: dict) -> dict:
    """EVs as editors hand them back → file shape; their wallbox side saved to components.json."""
    from house_config.components_store import load_components_document
    from house_config.wallboxes import (
        WALLBOXES_KEY,
        normalize_wallboxes,
        route_evs_to_wallboxes,
    )

    components = load_components_document(resolve_components_json_path())
    before = list(components.get(WALLBOXES_KEY) or [])
    profiles, wallboxes = route_evs_to_wallboxes(list(doc.get("profiles") or []), before)
    if normalize_wallboxes(wallboxes) != normalize_wallboxes(before):
        _save_components_document({**components, WALLBOXES_KEY: wallboxes})
    return {**doc, "profiles": profiles}


def merge_inline_heating_systems(doc: dict, *, read_existing: str) -> dict:
    """Move inline heat generation of every profile into its catalog entry (saved here)."""
    from house_config.components_store import load_components_document
    from house_config.heating_systems import (
        HEATING_SYSTEMS_KEY,
        assert_reference_systems_unshared,
        merge_inline_reference_systems,
        reference_ids_by_profile,
    )

    existing_raw = read_json_document(read_existing) if os.path.isfile(read_existing) else {}
    existing_refs = reference_ids_by_profile(existing_raw)
    components = load_components_document(resolve_components_json_path())
    before = list(components.get(HEATING_SYSTEMS_KEY) or [])
    catalog = before
    profiles: list[dict] = []
    for profile in doc.get("profiles") or []:
        merged, catalog = merge_inline_reference_systems(
            profile,
            catalog,
            existing_refs=existing_refs.get(str(profile.get("id") or "")),
        )
        profiles.append(merged)
    assert_reference_systems_unshared({"profiles": profiles})
    if catalog != before:
        _save_components_document({**components, HEATING_SYSTEMS_KEY: catalog})
    return {**doc, "profiles": profiles}

def tariffs_json_path() -> str:
    return resolve_tariffs_json_path()

def load_tariffs() -> dict:
    return load_tariffs_document(tariffs_json_path())

def append_tariff_monthly_rate(
    *,
    side: str,
    tariff_id: str,
    year: int,
    month: int,
    tariff_cent_kwh: float,
) -> None:
    """Persist one monthly_rates row and reload live config."""
    append_monthly_rate(
        tariffs_json_path(),
        side=side,
        tariff_id=tariff_id,
        year=year,
        month=month,
        tariff_cent_kwh=tariff_cent_kwh,
    )
    config.reload_config()

def load_backtesting_scenarios_raw() -> dict:
    path = resolve_backtesting_scenarios_json_path()
    if not os.path.isfile(path):
        return {"scenarios": []}
    return read_json_document(path)

def save_backtesting_scenarios(doc: dict) -> None:
    write_json_document(resolve_backtesting_scenarios_json_path(), doc)
    config.reinit_config()

def list_batteries() -> list[dict]:
    return config.get_batteries()

def list_pv_systems() -> list[dict]:
    return config.get_pv_systems()

def list_inverters() -> list[dict]:
    return config.get_inverters()

def _selection_entries(tariffs: dict) -> list[dict]:
    """Tariffs for the selects; user tariffs (Edibert) carry a marker in the label."""
    from house_config.tariffs_store import tariff_display_label

    return [{**t, "label": tariff_display_label(t)} for t in tariffs.values()]

def list_import_tariffs() -> list[dict]:
    doc = load_tariffs()
    return _selection_entries(doc.get("import_tariffs", {}))

def list_export_tariffs() -> list[dict]:
    doc = load_tariffs()
    return _selection_entries(doc.get("export_tariffs", {}))

def load_tariffs_catalog_meta() -> dict:
    doc = load_tariffs()
    meta: dict = {}
    if doc.get("catalog_as_of"):
        meta["catalog_as_of"] = doc["catalog_as_of"]
    return meta

def _house_profiles_payload(profile: dict) -> dict:
    """Everything ``upsert_house_profile`` derives before it writes (no write, no side effect).

    Keys: ``path``, ``payload`` (the document to save), ``components``, ``catalog``,
    ``catalog_changed`` (components.json would be rewritten), ``consumers``.
    """
    from house_config.components_store import load_components_document
    from house_config.heating_systems import (
        HEATING_SYSTEMS_KEY,
        assert_reference_systems_unshared,
        heating_systems_by_id,
        merge_inline_reference_systems,
        normalize_heating_systems,
        reference_ids_by_profile,
    )
    from house_config.label_uniqueness import assert_unique_label, assert_unique_labels_in_list

    path = resolve_house_profiles_json_path()
    raw: dict = {}
    if os.path.isfile(path):
        raw = read_json_document(path)
        profiles = list(raw.get("profiles", []))
    else:
        profiles = []
    # Optional holiday region: absent rather than "" when not chosen.
    profile = {k: v for k, v in profile.items() if not (k == "region" and not v)}
    profile_id = str(profile.get("id", "")).strip()
    assert_unique_label(profile.get("label"), profiles, exclude_id=profile_id)
    consumers = list(profile.get("consumers") or [])
    assert_unique_labels_in_list(consumers)
    # The form edits the reference heating system in place (components.json catalog).
    components_path = resolve_components_json_path()
    components = load_components_document(components_path)
    profile, catalog = merge_inline_reference_systems(
        profile,
        list(components.get(HEATING_SYSTEMS_KEY) or []),
        existing_refs=reference_ids_by_profile(raw).get(profile_id),
    )
    from house_config.baseload import ensure_baseload_not_over_allocated
    from house_config.profiles_store import normalize_house_profiles_document
    from house_config.wallboxes import (
        WALLBOXES_KEY,
        normalize_wallboxes,
        route_evs_to_wallboxes,
        wallboxes_by_id,
    )

    # The EV form edits its fixed wallbox inline (components.json wallboxes[]).
    stored_wallboxes = list(components.get(WALLBOXES_KEY) or [])
    (profile,), wallboxes = route_evs_to_wallboxes([profile], stored_wallboxes)
    normalized = normalize_house_profiles_document(
        {"profiles": [profile]},
        heating_systems=heating_systems_by_id({HEATING_SYSTEMS_KEY: catalog}),
        wallboxes=wallboxes_by_id({WALLBOXES_KEY: wallboxes}),
    )
    ensure_baseload_not_over_allocated(normalized["profiles"][profile_id])
    profiles = [p for p in profiles if p.get("id") != profile["id"]]
    profiles.append(profile)
    # Checked again on save; here before the catalog is written.
    assert_reference_systems_unshared({"profiles": profiles})
    payload: dict = {"profiles": profiles}
    plant = raw.get("plant")
    if isinstance(plant, dict) and plant:
        payload["plant"] = dict(plant)
    if "earnie_data_model" in raw:
        payload["earnie_data_model"] = raw["earnie_data_model"]
    return {
        "path": path,
        "payload": payload,
        "components": components,
        "catalog": catalog,
        # Compared in the normalised form the save writes: the form leaves out keys the
        # save fills in (e.g. a rod part's internal_gain_factor), which is no change.
        "catalog_changed": normalize_heating_systems(catalog)
        != normalize_heating_systems(list(components.get(HEATING_SYSTEMS_KEY) or [])),
        "wallboxes": wallboxes,
        "wallboxes_changed": normalize_wallboxes(wallboxes)
        != normalize_wallboxes(stored_wallboxes),
        "consumers": consumers,
    }


def house_profile_write_pending(profile: dict) -> bool:
    """Would ``upsert_house_profile(profile)`` change a file? (dry run, nothing written)

    False when ``house_profiles.json`` already holds exactly what the save would
    write (normalised form) and the heating catalog is unchanged. Used on the
    first render of a profile so that opening the page does not rewrite the file.
    """
    from house_config.profiles_store import serialize_house_profiles_document

    built = _house_profiles_payload(profile)
    if (
        built["catalog_changed"]
        or built["wallboxes_changed"]
        or not os.path.isfile(built["path"])
    ):
        return True
    would_write = serialize_house_profiles_document(built["path"], built["payload"])
    return would_write != read_json_document(built["path"])


def upsert_house_profile(profile: dict) -> None:
    from house_config.heating_systems import HEATING_SYSTEMS_KEY
    from house_config.wallboxes import WALLBOXES_KEY

    built = _house_profiles_payload(profile)
    if built["catalog_changed"] or built["wallboxes_changed"]:
        _save_components_document(
            {
                **built["components"],
                HEATING_SYSTEMS_KEY: built["catalog"],
                WALLBOXES_KEY: built["wallboxes"],
            }
        )
    save_house_profiles_document(built["path"], built["payload"])
    from ui.house_config_entities_io import sync_powerstation_attached_from_consumers

    sync_powerstation_attached_from_consumers(built["consumers"])


def _scenario_ids_using_house_profile(profile_id: str) -> tuple[list[str], bool]:
    target = str(profile_id or "").strip()
    live_id = str(config.get_live_scenario_id() or "").strip()
    used_by: list[str] = []
    live_hit = False
    for item in load_backtesting_scenarios_raw().get("scenarios") or []:
        if not isinstance(item, dict):
            continue
        settings = item.get("settings") if isinstance(item.get("settings"), dict) else {}
        if str(settings.get("house_profile_id", "") or "").strip() != target:
            continue
        sid = str(item.get("id", "") or "").strip() or "?"
        used_by.append(sid)
        if live_id and sid == live_id:
            live_hit = True
    return used_by, live_hit


def delete_house_profile(profile_id: str) -> None:
    """Remove a house profile that no scenario still references."""
    target = str(profile_id or "").strip()
    if not target:
        raise ValueError("Profil-ID fehlt.")
    used_by, live_hit = _scenario_ids_using_house_profile(target)
    if live_hit:
        raise ValueError("Das Hausprofil des Live-Szenarios kann nicht entfernt werden.")
    if used_by:
        raise ValueError(
            "Hausprofil wird noch von Szenarien verwendet: " + ", ".join(used_by) + "."
        )
    path = resolve_house_profiles_json_path()
    if not os.path.isfile(path):
        raise ValueError(f"Unbekanntes Hausprofil '{target}'.")
    raw = read_json_document(path)
    profiles = list(raw.get("profiles", []))
    remaining = [p for p in profiles if str(p.get("id", "")).strip() != target]
    if len(remaining) == len(profiles):
        raise ValueError(f"Unbekanntes Hausprofil '{target}'.")
    payload: dict = {"profiles": remaining}
    plant = raw.get("plant")
    if isinstance(plant, dict) and plant:
        payload["plant"] = dict(plant)
    if "earnie_data_model" in raw:
        payload["earnie_data_model"] = raw["earnie_data_model"]
    save_house_profiles_document(path, payload)


from ui.house_config_csv_io import (  # noqa: E402
    _resampled_upload_csv_name,
    _stable_upload_csv_name,
    apply_csv_path_pending,
    csv_upload_widget_key,
    queue_csv_path_update,
    save_balance_total_from_component_paths,
    save_energiemonitor_balance_profile_csvs,
    save_energiemonitor_profile_csvs,
    save_profile_consumption_csv,
    single_csv_upload,
)
from ui.house_config_entities_io import (  # noqa: E402
    _live_scenario_settings,
    _load_components_document,
    _load_config_document,
    _save_components_document,
    _save_config_document,
    compute_baseload_kwh,
    delete_battery,
    delete_inverter,
    delete_pv_system,
    delete_scenario,
    get_live_scenario_refs,
    get_planning_tariff_selection,
    load_main_config,
    preview_baseload,
    reorder_scenarios,
    save_live_scenario_id,
    save_live_scenario_refs,
    save_main_config,
    save_planning_tariff_selection,
    upsert_battery,
    upsert_inverter,
    upsert_pv_system,
    upsert_scenario,
)

__all__ = [
    "_live_scenario_settings",
    "_load_components_document",
    "_load_config_document",
    "_resampled_upload_csv_name",
    "_save_components_document",
    "_save_config_document",
    "_stable_upload_csv_name",
    "append_tariff_monthly_rate",
    "apply_csv_path_pending",
    "compute_baseload_kwh",
    "csv_upload_widget_key",
    "delete_battery",
    "delete_house_profile",
    "delete_inverter",
    "delete_pv_system",
    "delete_scenario",
    "get_live_scenario_refs",
    "get_planning_tariff_selection",
    "house_doc_for_save",
    "list_batteries",
    "list_export_tariffs",
    "list_import_tariffs",
    "list_inverters",
    "list_pv_systems",
    "load_backtesting_scenarios_raw",
    "load_house_profiles",
    "load_main_config",
    "load_tariffs",
    "load_tariffs_catalog_meta",
    "preview_baseload",
    "queue_csv_path_update",
    "read_json_document",
    "reorder_scenarios",
    "save_backtesting_scenarios",
    "save_balance_total_from_component_paths",
    "save_energiemonitor_balance_profile_csvs",
    "save_energiemonitor_profile_csvs",
    "save_house_profiles",
    "save_live_scenario_id",
    "save_live_scenario_refs",
    "save_main_config",
    "save_planning_tariff_selection",
    "save_profile_consumption_csv",
    "single_csv_upload",
    "tariffs_json_path",
    "upsert_battery",
    "upsert_house_profile",
    "upsert_inverter",
    "upsert_pv_system",
    "upsert_scenario",
    "write_json_document",
]

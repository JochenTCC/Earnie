"""Persistenz-Hilfen für Hauskonfigurator und Szenarieneditor."""
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
from house_config.tariffs_store import load_tariffs_document
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


def save_house_profiles(doc: dict) -> None:
    save_house_profiles_document(resolve_house_profiles_json_path(), doc)


def tariffs_json_path() -> str:
    return resolve_tariffs_json_path()


def load_tariffs() -> dict:
    return load_tariffs_document(tariffs_json_path())


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


def list_import_tariffs() -> list[dict]:
    doc = load_tariffs()
    return list(doc.get("import_tariffs", {}).values())


def list_export_tariffs() -> list[dict]:
    doc = load_tariffs()
    return list(doc.get("export_tariffs", {}).values())


def load_tariffs_catalog_meta() -> dict:
    doc = load_tariffs()
    meta: dict = {}
    if doc.get("catalog_as_of"):
        meta["catalog_as_of"] = doc["catalog_as_of"]
    return meta


def upsert_house_profile(profile: dict) -> None:
    from house_config.label_uniqueness import assert_unique_label, assert_unique_labels_in_list

    path = resolve_house_profiles_json_path()
    if os.path.isfile(path):
        raw = read_json_document(path)
        profiles = list(raw.get("profiles", []))
    else:
        profiles = []
    profile_id = str(profile.get("id", "")).strip()
    assert_unique_label(profile.get("label"), profiles, exclude_id=profile_id)
    consumers = list(profile.get("consumers") or [])
    assert_unique_labels_in_list(consumers)
    profiles = [p for p in profiles if p.get("id") != profile["id"]]
    profiles.append(profile)
    save_house_profiles_document(path, {"profiles": profiles})
    from data import cons_data_store

    cons_data_store.invalidate_cons_data_meta()


def _stable_upload_csv_name(
    profile_id: str,
    *,
    consumer_id: str = "",
    role: str = "",
) -> str:
    """Fallback filename per profile role / consumer when upload name is missing."""
    prefix = str(profile_id or "profile").strip() or "profile"
    consumer = str(consumer_id or "").strip()
    role_part = str(role or "").strip()
    if consumer:
        return f"{prefix}_{consumer}.csv"
    if role_part:
        return f"{prefix}_{role_part}.csv"
    return f"{prefix}_verbrauch.csv"


def _resampled_upload_csv_name(filename: str, *, fallback: str) -> str:
    """Build ``{original_stem}_resampled.csv`` from the uploaded basename."""
    basename = Path(str(filename or "").strip()).name
    if not basename:
        return fallback
    stem = Path(basename).stem.strip()
    if not stem or stem in (".", ".."):
        return fallback
    if stem.lower().endswith("_resampled"):
        return f"{stem}.csv"
    return f"{stem}_resampled.csv"


def single_csv_upload(
    label: str,
    *,
    key: str,
    help: str | None = None,
):
    """Streamlit CSV uploader that accepts exactly one file.

    Returns the uploaded file, or None if empty / rejected (more than one file).
    """
    import streamlit as st

    upload = st.file_uploader(
        label,
        type=["csv"],
        accept_multiple_files=False,
        key=key,
        help=help or "Nur eine CSV-Datei erlaubt.",
    )
    if upload is None:
        return None
    if isinstance(upload, list):
        if len(upload) > 1:
            st.error("Nur eine CSV-Datei erlaubt.")
            return None
        return upload[0] if upload else None
    return upload


def apply_csv_path_pending(
    pending_key: str,
    path_key: str,
    input_key: str,
    *,
    use_key: str | None = None,
) -> None:
    """Apply queued path to canonical + text_input keys before widgets render."""
    import streamlit as st

    if pending_key not in st.session_state:
        return
    pending = str(st.session_state.pop(pending_key) or "")
    st.session_state[path_key] = pending
    st.session_state[input_key] = pending
    if use_key is not None and not pending:
        st.session_state[use_key] = False


def queue_csv_path_update(
    pending_key: str,
    path: str,
    *,
    upload_nonce_key: str | None = None,
    flash_key: str | None = None,
    flash_message: str | None = None,
) -> None:
    """Queue path/widget sync for next run; bump uploader nonce to drop sticky file."""
    import streamlit as st

    st.session_state[pending_key] = str(path or "")
    if upload_nonce_key is not None:
        st.session_state[upload_nonce_key] = int(
            st.session_state.get(upload_nonce_key, 0) or 0
        ) + 1
    if flash_key and flash_message:
        st.session_state[flash_key] = flash_message


def csv_upload_widget_key(base_key: str, nonce_key: str) -> str:
    """Stable base key + nonce so clearing/re-upload resets Streamlit file_uploader."""
    import streamlit as st

    nonce = int(st.session_state.get(nonce_key, 0) or 0)
    return f"{base_key}__n{nonce}"


def save_profile_consumption_csv(
    profile_id: str,
    content: bytes,
    filename: str,
    *,
    consumer_id: str = "",
    normalize: bool = True,
    min_hours: int = 8760,
    role: str = "",
) -> str:
    """Speichert Verbrauchs-CSV unter uploads/ neben der aktiven Config; optional normalisiert.

    Target name is ``{original_stem}_resampled.csv`` (basename only). If ``filename``
    is empty/invalid, falls back to a stable ``{profile}_{role|consumer}.csv`` name.
    Same original basename re-uploaded overwrites that resampled file.
    Returns a portable ``config/uploads/…`` path for storage in house profiles.
    """
    from house_config.consumption_csv import (
        MIN_HOURS_FULL_YEAR,
        normalize_profile_csv_file,
    )

    uploads_dir = Path(resolve_uploads_dir())
    uploads_dir.mkdir(parents=True, exist_ok=True)
    fallback = _stable_upload_csv_name(
        profile_id, consumer_id=consumer_id, role=role
    )
    target = uploads_dir / _resampled_upload_csv_name(filename, fallback=fallback)
    target.write_bytes(content)
    portable = f"config/uploads/{target.name}"
    if normalize:
        hours = min_hours if min_hours > 0 else MIN_HOURS_FULL_YEAR
        normalize_profile_csv_file(portable, min_hours=hours)
    return portable


def save_energiemonitor_profile_csvs(
    profile_id: str,
    content: bytes,
    filename: str,
    *,
    min_hours: int = 8760,
) -> dict[str, str]:
    """Import Energiemonitor upload → canonical Verbrauch (+ optional PV) under uploads/."""
    from house_config.consumption_csv import (
        MIN_HOURS_FULL_YEAR,
        import_energiemonitor_to_canonical,
    )

    uploads_dir = Path(resolve_uploads_dir())
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "energiemonitor.csv"
    if not safe_name.lower().endswith(".csv"):
        safe_name = f"{safe_name}.csv"
    raw_path = uploads_dir / f"{profile_id}_energiemonitor_raw_{safe_name}"
    raw_path.write_bytes(content)
    hours = min_hours if min_hours > 0 else MIN_HOURS_FULL_YEAR
    verbrauch_name = f"{profile_id}_energiemonitor_verbrauch.csv"
    produktion_name = f"{profile_id}_energiemonitor_produktion.csv"
    verbrauch_dest = f"config/uploads/{verbrauch_name}"
    produktion_dest = f"config/uploads/{produktion_name}"
    return import_energiemonitor_to_canonical(
        raw_path.as_posix(),
        verbrauch_dest=verbrauch_dest,
        produktion_dest=produktion_dest,
        min_hours=hours,
    )


def _load_config_document() -> dict:
    return read_json_dict(resolve_config_json_path())


def _save_config_document(data: dict) -> None:
    write_json_dict(resolve_config_json_path(), data)
    config.reinit_config()


def load_main_config() -> dict:
    """Public alias: load earnie_env config.json."""
    return _load_config_document()


def save_main_config(data: dict) -> None:
    """Public alias: persist config.json and reinit runtime config."""
    _save_config_document(data)


def _load_components_document() -> dict:
    from house_config.components_store import load_components_document

    return load_components_document(resolve_components_json_path())


def _save_components_document(data: dict) -> None:
    from house_config.components_store import save_components_document

    save_components_document(resolve_components_json_path(), data)
    config.reinit_config()


def upsert_pv_system(raw_spec: dict, *, stable_id: str = "") -> None:
    from house_config.entity_resolution import normalize_pv_system
    from house_config.label_uniqueness import assert_unique_label

    data = _load_components_document()
    systems = list(data.get("pv_systems") or [])
    taken = {str(item.get("id", "")) for item in systems if item.get("id")}
    if stable_id:
        taken.discard(stable_id)
    label = str(raw_spec.get("label", "")).strip()
    entity_id = stable_id.strip() or slug_id(label or "pv_anlage", existing=taken)
    assert_unique_label(label or entity_id, systems, exclude_id=entity_id)
    spec = {
        "id": entity_id,
        "label": label or entity_id,
        "kwp": float(raw_spec["kwp"]),
        "pv_tilt": float(raw_spec.get("pv_tilt", 25.0)),
        "pv_azimuth": float(raw_spec.get("pv_azimuth", 0.0)),
    }
    normalize_pv_system(spec, 0)
    systems = [item for item in systems if item.get("id") != entity_id]
    systems.append(spec)
    data["pv_systems"] = systems
    _save_components_document(data)


def delete_pv_system(entity_id: str) -> None:
    """Remove a PV system from components.json and scrub scenario references."""
    from house_config.entity_resolution import normalize_pv_system_ids

    target = str(entity_id or "").strip()
    if not target:
        raise ValueError("PV-Anlagen-ID fehlt.")
    data = _load_components_document()
    systems = list(data.get("pv_systems") or [])
    remaining = [item for item in systems if str(item.get("id", "")).strip() != target]
    if len(remaining) == len(systems):
        raise ValueError(f"Unbekannte PV-Anlage '{target}'.")
    data["pv_systems"] = remaining
    _save_components_document(data)

    doc = load_backtesting_scenarios_raw()
    changed = False
    for scenario in doc.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        settings = scenario.get("settings")
        if not isinstance(settings, dict):
            continue
        ids = normalize_pv_system_ids(settings)
        if target not in ids:
            continue
        cleaned = [pv_id for pv_id in ids if pv_id != target]
        settings.pop("pv_system_id", None)
        if cleaned:
            settings["pv_system_ids"] = cleaned
        else:
            settings.pop("pv_system_ids", None)
        changed = True
    if changed:
        save_backtesting_scenarios(doc)
        config.reinit_config()


def upsert_battery(raw_spec: dict, *, stable_id: str = "") -> None:
    from house_config.entity_resolution import normalize_battery
    from house_config.label_uniqueness import assert_unique_label

    data = _load_components_document()
    batteries = list(data.get("batteries") or [])
    taken = {str(item.get("id", "")) for item in batteries if item.get("id")}
    if stable_id:
        taken.discard(stable_id)
    label = str(raw_spec.get("label", "")).strip()
    entity_id = stable_id.strip() or slug_id(label or "batterie", existing=taken)
    assert_unique_label(label or entity_id, batteries, exclude_id=entity_id)
    spec = {
        "id": entity_id,
        "label": label or entity_id,
        "battery_capacity_kwh": float(raw_spec["battery_capacity_kwh"]),
        "battery_max_power_kw": float(raw_spec["battery_max_power_kw"]),
        "battery_efficiency": float(raw_spec["battery_efficiency"]),
        "battery_min_soc": float(raw_spec["battery_min_soc"]),
        "battery_max_soc": float(raw_spec["battery_max_soc"]),
        "threshold_power": float(raw_spec.get("threshold_power", 0.05)),
    }
    existing_wear = None
    if stable_id:
        for item in batteries:
            if str(item.get("id", "")).strip() == entity_id:
                existing_wear = item.get("battery_wear")
                break
    if raw_spec.get("battery_wear") is not None:
        spec["battery_wear"] = raw_spec["battery_wear"]
    elif existing_wear is not None:
        spec["battery_wear"] = existing_wear
    else:
        spec["battery_wear"] = {"enabled": False}
    normalize_battery(spec, 0)
    batteries = [item for item in batteries if item.get("id") != entity_id]
    batteries.append(spec)
    data["batteries"] = batteries
    _save_components_document(data)


def delete_battery(entity_id: str) -> None:
    """Remove a battery from components.json and scrub scenario references."""
    target = str(entity_id or "").strip()
    if not target:
        raise ValueError("Batterie-ID fehlt.")
    data = _load_components_document()
    batteries = list(data.get("batteries") or [])
    remaining = [item for item in batteries if str(item.get("id", "")).strip() != target]
    if len(remaining) == len(batteries):
        raise ValueError(f"Unbekannte Batterie '{target}'.")
    data["batteries"] = remaining
    _save_components_document(data)

    doc = load_backtesting_scenarios_raw()
    changed = False
    for scenario in doc.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        settings = scenario.get("settings")
        if not isinstance(settings, dict):
            continue
        if str(settings.get("battery_id", "") or "").strip() != target:
            continue
        settings["battery_id"] = ""
        changed = True
    if changed:
        save_backtesting_scenarios(doc)
        config.reinit_config()


def _live_scenario_settings() -> dict:
    from house_config.scenario_resolution import (
        find_scenario_settings,
        get_live_scenario_id,
    )

    raw_config = _load_config_document()
    live_id = get_live_scenario_id(raw_config)
    scenarios_path = config.CONFIG.backtesting_scenarios_path
    try:
        return find_scenario_settings(scenarios_path, live_id)
    except ValueError:
        return {}


def get_planning_tariff_selection() -> tuple[str, str]:
    settings = _live_scenario_settings()
    return (
        str(settings.get("import_tariff_id", "") or "").strip(),
        str(settings.get("export_tariff_id", "") or "").strip(),
    )


def save_planning_tariff_selection(import_tariff_id: str, export_tariff_id: str) -> None:
    config.update_live_scenario_settings(
        {
            "import_tariff_id": import_tariff_id.strip(),
            "export_tariff_id": export_tariff_id.strip(),
        }
    )


def get_live_scenario_refs() -> dict:
    """Entitäts-Referenzen des Live-Szenarios aus backtesting_scenarios.json."""
    from house_config.entity_resolution import normalize_pv_system_ids

    settings = _live_scenario_settings()
    return {
        "battery_id": str(settings.get("battery_id", "") or "").strip(),
        "pv_system_ids": normalize_pv_system_ids(settings),
        "import_tariff_id": str(settings.get("import_tariff_id", "") or "").strip(),
        "export_tariff_id": str(settings.get("export_tariff_id", "") or "").strip(),
        "house_profile_id": str(settings.get("house_profile_id", "") or "").strip(),
    }


def get_runtime_scenario_refs() -> dict:
    """Alias für get_live_scenario_refs (API-Stabilität)."""
    return get_live_scenario_refs()


def save_live_scenario_refs(
    *,
    battery_id: str,
    pv_system_ids: list[str],
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
) -> None:
    """Speichert Entitäts-Referenzen für das Live-Szenario."""
    cleaned = [str(item or "").strip() for item in pv_system_ids if str(item or "").strip()]
    config.update_live_scenario_settings(
        {
            "battery_id": battery_id.strip(),
            "pv_system_ids": cleaned,
            "import_tariff_id": import_tariff_id.strip(),
            "export_tariff_id": export_tariff_id.strip(),
            "house_profile_id": house_profile_id.strip(),
        }
    )


def save_live_scenario_id(scenario_id: str) -> None:
    """Setzt live_scenario_id in config.json."""
    config.set_live_scenario_id(scenario_id.strip())


def save_runtime_scenario_refs(
    *,
    battery_id: str,
    pv_system_ids: list[str],
    import_tariff_id: str,
    export_tariff_id: str,
    house_profile_id: str,
) -> None:
    """Alias für save_live_scenario_refs (API-Stabilität)."""
    save_live_scenario_refs(
        battery_id=battery_id,
        pv_system_ids=pv_system_ids,
        import_tariff_id=import_tariff_id,
        export_tariff_id=export_tariff_id,
        house_profile_id=house_profile_id,
    )


def upsert_scenario(scenario: dict) -> None:
    from house_config.label_uniqueness import assert_unique_label

    doc = load_backtesting_scenarios_raw()
    scenarios = list(doc.get("scenarios", []))
    scenario_id = str(scenario.get("id", "")).strip()
    live_id = str(config.get_live_scenario_id() or "").strip()
    payload = dict(scenario)
    if live_id and scenario_id == live_id:
        existing = next(
            (item for item in scenarios if str(item.get("id", "")).strip() == live_id),
            None,
        )
        if existing is not None:
            payload["label"] = str(
                existing.get("label") or existing.get("id") or live_id
            ).strip()
    assert_unique_label(payload.get("label"), scenarios, exclude_id=scenario_id)
    updated = [s for s in scenarios if s.get("id") != payload["id"]]
    updated.append(payload)
    doc["scenarios"] = updated
    save_backtesting_scenarios(doc)


def delete_scenario(scenario_id: str) -> None:
    """Remove a non-live scenario from backtesting_scenarios.json."""
    target = str(scenario_id or "").strip()
    if not target:
        raise ValueError("Szenario-ID fehlt.")
    live_id = str(config.get_live_scenario_id() or "").strip()
    if live_id and target == live_id:
        raise ValueError("Das Live-Szenario kann nicht entfernt werden.")
    doc = load_backtesting_scenarios_raw()
    scenarios = list(doc.get("scenarios", []))
    remaining = [
        item for item in scenarios if str(item.get("id", "")).strip() != target
    ]
    if len(remaining) == len(scenarios):
        raise ValueError(f"Unbekanntes Szenario '{target}'.")
    doc["scenarios"] = remaining
    save_backtesting_scenarios(doc)


def preview_baseload(annual_kwh: float, consumers: list[dict]) -> dict:
    return compute_baseload_kwh(annual_kwh, consumers)


def compute_baseload_kwh(annual_kwh: float, consumers: list[dict]) -> dict:
    from house_config.baseload import compute_baseload_kwh as _compute

    return _compute(annual_kwh, consumers)

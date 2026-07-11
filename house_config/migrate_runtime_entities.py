"""Migration flacher runtime_settings in Entitäts-Referenzen (1.26.0 P5)."""
from __future__ import annotations

import copy
import json
from typing import Any

from house_config.geo_timezone import lookup_timezone_name
from house_config.id_slug import slug_id
from house_config.tariffs_store import slugify_tariff_id

RUNTIME_ID_KEYS = frozenset(
    {
        "battery_id",
        "pv_system_id",
        "import_tariff_id",
        "export_tariff_id",
        "house_profile_id",
        "netzentgelt_cent_kwh_override",
    }
)
RUNTIME_FLAT_BATTERY = (
    "battery_capacity_kwh",
    "battery_max_power_kw",
    "battery_efficiency",
    "battery_min_soc",
    "battery_max_soc",
    "threshold_power",
)
RUNTIME_FLAT_PV = ("pv_kwp", "pv_tilt", "pv_azimuth")
RUNTIME_FLAT_GEO = ("latitude", "longitude", "timezone_name")
RUNTIME_FLAT_TARIFF = ("k_push_cent", "feed_in_mode")
RUNTIME_STRIP_KEYS = RUNTIME_FLAT_BATTERY + RUNTIME_FLAT_PV + RUNTIME_FLAT_GEO + RUNTIME_FLAT_TARIFF

_AWATTAR_IMPORT_KEYS = ("fix_aufschlag_cent", "netzverlust_faktor", "mwst_austria_faktor")
_AWATTAR_EXPORT_KEYS = ("feed_in_fee_factor", "feed_in_fix_cent")


def migrate_runtime_entities(
    config: dict,
    *,
    tariffs_doc: dict,
    house_profiles_doc: dict,
) -> tuple[dict, dict, dict, list[str]]:
    """
    Erzeugt Entwürfe für config.json, tariffs.json und house_profiles.json.

    Gibt Kopien zurück — Eingabedateien bleiben unverändert.
    """
    notes: list[str] = []
    config_out = copy.deepcopy(config)
    tariffs_out = _normalize_tariffs_lists(copy.deepcopy(tariffs_doc))
    profiles_out = _normalize_profiles_list(copy.deepcopy(house_profiles_doc))
    runtime = config_out.setdefault("runtime_settings", {})
    if not isinstance(runtime, dict):
        raise ValueError("runtime_settings muss ein Objekt sein.")

    battery_id = _migrate_battery(config_out, runtime, notes)
    pv_id = _migrate_pv(config_out, runtime, notes)
    import_id = _migrate_import_tariff(config_out, runtime, tariffs_out, notes)
    export_id = _migrate_export_tariff(config_out, runtime, tariffs_out, notes)
    profile_id = _migrate_house_profile_geo(runtime, profiles_out, notes)

    runtime["battery_id"] = battery_id
    runtime["pv_system_id"] = pv_id
    runtime["import_tariff_id"] = import_id
    runtime["export_tariff_id"] = export_id
    runtime["house_profile_id"] = profile_id
    _strip_runtime_flat_fields(runtime)
    return config_out, tariffs_out, profiles_out, notes


def effective_runtime_values(
    config: dict,
    *,
    tariffs_path: str,
    house_profiles_path: str,
) -> dict[str, Any]:
    """Flache Laufzeitwerte inkl. Legacy-Fallback aus runtime_settings."""
    from house_config.scenario_resolution import resolve_runtime_settings

    resolved = resolve_runtime_settings(
        config,
        tariffs_path=tariffs_path,
        house_profiles_path=house_profiles_path,
    )
    runtime = config.get("runtime_settings", {})
    if not isinstance(runtime, dict):
        runtime = {}
    keys = (
        *RUNTIME_FLAT_BATTERY,
        *RUNTIME_FLAT_PV,
        *RUNTIME_FLAT_GEO,
        *RUNTIME_FLAT_TARIFF,
    )
    return {key: resolved.get(key, runtime.get(key)) for key in keys}


def write_migration_draft(
    output_dir,
    *,
    config: dict,
    tariffs_doc: dict,
    house_profiles_doc: dict,
    notes: list[str],
) -> None:
    """Schreibt Entwurfsdateien und MIGRATION_REVIEW.md."""
    from pathlib import Path

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(
        json.dumps(config, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out / "tariffs.json").write_text(
        json.dumps(tariffs_doc, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out / "house_profiles.json").write_text(
        json.dumps(house_profiles_doc, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    review_lines = [
        "# Migration Review (1.26.0 P5)",
        "",
        "Manuelle Prüfung vor Deploy auf NAS.",
        "",
        "## Hinweise",
        "",
    ]
    if notes:
        review_lines.extend(f"- {note}" for note in notes)
    else:
        review_lines.append("- Keine automatischen Hinweise.")
    review_lines.extend(
        [
            "",
            "## Nächste Schritte",
            "",
            "1. Entwurf mit produktiver Konfiguration vergleichen.",
            "2. `tariffs.json` und `house_profiles.json` in `config/` übernehmen.",
            "3. `config.json` → `runtime_settings` nur noch IDs prüfen.",
            "4. Live-Optimierung und Backtesting-Baseline testen.",
            "5. Globale Blöcke `battery_wear` und `awattar` aus config.json entfernen (P6).",
            "",
        ]
    )
    (out / "MIGRATION_REVIEW.md").write_text("\n".join(review_lines), encoding="utf-8")


def _normalize_tariffs_lists(doc: dict) -> dict:
    if not isinstance(doc, dict):
        return {"import_tariffs": [], "export_tariffs": []}
    for key in ("import_tariffs", "export_tariffs"):
        items = doc.get(key, [])
        if not isinstance(items, list):
            items = []
        doc[key] = items
    return doc


def _normalize_profiles_list(doc: dict) -> dict:
    if not isinstance(doc, dict):
        return {"profiles": []}
    profiles = doc.get("profiles", [])
    if not isinstance(profiles, list):
        profiles = []
    doc["profiles"] = profiles
    return doc


def _strip_runtime_flat_fields(runtime: dict) -> None:
    for key in RUNTIME_STRIP_KEYS:
        runtime.pop(key, None)
    for key in list(runtime):
        if key not in RUNTIME_ID_KEYS:
            runtime.pop(key, None)


def _migrate_battery(config: dict, runtime: dict, notes: list[str]) -> str:
    batteries = config.setdefault("batteries", [])
    if not isinstance(batteries, list):
        raise ValueError("batteries muss ein Array sein.")
    existing_ids = {str(item.get("id", "")).strip() for item in batteries if isinstance(item, dict)}
    battery_id = str(runtime.get("battery_id", "") or "").strip()
    flat = _extract_battery_flat(runtime)
    global_wear = config.get("battery_wear")

    if battery_id and battery_id in existing_ids:
        _ensure_battery_wear_on_entry(config, batteries, battery_id, global_wear, notes)
        return battery_id

    if not flat:
        raise ValueError("Keine Batterie-Parameter in runtime_settings gefunden.")

    if not battery_id:
        label = f"{flat['battery_capacity_kwh']:.1f} kWh Speicher"
        battery_id = slug_id(label, existing=existing_ids)

    entry = {
        "id": battery_id,
        "label": f"Produktiv {flat['battery_capacity_kwh']:.1f} kWh",
        **flat,
    }
    if global_wear is not None:
        entry["battery_wear"] = copy.deepcopy(global_wear)
        notes.append(f"Globaler battery_wear → batteries[] '{battery_id}'.")
    elif not any(
        isinstance(item, dict) and str(item.get("id", "")).strip() == battery_id
        for item in batteries
    ):
        notes.append(f"Batterie '{battery_id}' ohne battery_wear — manuell prüfen.")

    _upsert_list_entry(batteries, entry)
    return battery_id


def _migrate_pv(config: dict, runtime: dict, notes: list[str]) -> str:
    pv_systems = config.setdefault("pv_systems", [])
    if not isinstance(pv_systems, list):
        raise ValueError("pv_systems muss ein Array sein.")
    existing_ids = {str(item.get("id", "")).strip() for item in pv_systems if isinstance(item, dict)}
    pv_id = str(runtime.get("pv_system_id", "") or "").strip()
    flat = _extract_pv_flat(runtime)

    if pv_id and pv_id in existing_ids:
        return pv_id

    if not flat:
        raise ValueError("Keine PV-Parameter in runtime_settings gefunden.")

    matched = _find_matching_pv(pv_systems, flat)
    if matched:
        return matched

    if not pv_id:
        label = f"PV {flat['pv_kwp']:.1f} kWp"
        pv_id = slug_id(label, existing=existing_ids)

    entry = {
        "id": pv_id,
        "label": f"Produktiv {flat['pv_kwp']:.1f} kWp",
        "kwp": flat["pv_kwp"],
        "pv_tilt": flat["pv_tilt"],
        "pv_azimuth": flat["pv_azimuth"],
    }
    _upsert_list_entry(pv_systems, entry)
    notes.append(f"PV-Entität '{pv_id}' aus flachen runtime_settings erzeugt.")
    return pv_id


def _migrate_import_tariff(
    config: dict,
    runtime: dict,
    tariffs_doc: dict,
    notes: list[str],
) -> str:
    import_id = str(runtime.get("import_tariff_id", "") or "").strip()
    if import_id:
        _merge_awattar_into_import(config, tariffs_doc, import_id, notes)
        return import_id

    provider = str(
        config.get("file_paths_battery_simulation", {}).get("price_provider", "awattar")
    ).strip()
    if provider == "awattar" or config.get("awattar"):
        import_id = "awattar_at"
    else:
        import_id = "awattar_at"
        notes.append(
            f"import_tariff_id fehlte — Fallback '{import_id}' gesetzt; manuell prüfen."
        )

    _ensure_import_tariff(tariffs_doc, import_id)
    _merge_awattar_into_import(config, tariffs_doc, import_id, notes)
    return import_id


def _migrate_export_tariff(
    config: dict,
    runtime: dict,
    tariffs_doc: dict,
    notes: list[str],
) -> str:
    export_id = str(runtime.get("export_tariff_id", "") or "").strip()
    if export_id:
        _merge_awattar_into_export(config, tariffs_doc, export_id, notes)
        return export_id

    feed_in_mode = str(runtime.get("feed_in_mode", "fixed") or "fixed").strip().lower()
    if feed_in_mode == "dynamic_epex":
        export_id = "dynamic_epex"
        _ensure_export_tariff(tariffs_doc, export_id, tariff_type="dynamic_epex")
        _merge_awattar_into_export(config, tariffs_doc, export_id, notes)
        return export_id

    k_push = float(runtime.get("k_push_cent", 0.0) or 0.0)
    export_id = _find_fixed_export_id(tariffs_doc, k_push)
    if not export_id:
        export_id = slugify_tariff_id("export_fixed", f"{k_push:.2f}ct")
        tariffs_doc.setdefault("export_tariffs", []).append(
            {
                "id": export_id,
                "label": f"Fix {k_push:.2f} ct/kWh (migriert)",
                "type": "fixed",
                "k_push_cent": k_push,
            }
        )
        notes.append(f"Export-Tarif '{export_id}' mit k_push_cent={k_push} angelegt.")
    return export_id


def _migrate_house_profile_geo(
    runtime: dict,
    profiles_doc: dict,
    notes: list[str],
) -> str:
    profiles = profiles_doc.setdefault("profiles", [])
    profile_id = str(runtime.get("house_profile_id", "") or "").strip()
    geo = _extract_geo_flat(runtime)

    if profile_id:
        profile = _find_profile(profiles, profile_id)
        if profile is None:
            raise ValueError(f"Unbekannte house_profile_id '{profile_id}'.")
        if geo:
            _apply_geo(profile, geo)
            notes.append(f"Geo/Zeitzone → Hausprofil '{profile_id}' übernommen.")
        return profile_id

    if geo:
        matched = _find_profile_by_geo(profiles, geo)
        if matched:
            profile = _find_profile(profiles, matched)
            if profile is not None:
                _apply_geo(profile, geo)
                notes.append(f"Geo → bestehendes Hausprofil '{matched}' zugeordnet.")
                return matched

    inferred = _infer_thermal_profile_id(profiles)
    if inferred:
        profile = _find_profile(profiles, inferred)
        if profile is not None and geo:
            _apply_geo(profile, geo)
            notes.append(f"house_profile_id '{inferred}' (thermal) mit Geo ergänzt.")
        return inferred

    if not geo:
        raise ValueError(
            "Weder house_profile_id noch Geo-Koordinaten in runtime_settings — "
            "Hausprofil manuell zuordnen."
        )

    profile_id = slug_id("migrated_home", existing={str(p.get("id", "")).strip() for p in profiles})
    profile = {
        "id": profile_id,
        "label": "Migriertes Hausprofil",
        "annual_kwh": 4000.0,
        **geo,
        "consumers": [],
    }
    profiles.append(profile)
    notes.append(f"Neues Hausprofil '{profile_id}' aus runtime_settings-Geo erzeugt.")
    return profile_id


def _extract_battery_flat(runtime: dict) -> dict | None:
    if "battery_capacity_kwh" not in runtime:
        return None
    return {
        key: runtime[key]
        for key in RUNTIME_FLAT_BATTERY
        if key in runtime
    }


def _extract_pv_flat(runtime: dict) -> dict | None:
    if "pv_kwp" not in runtime:
        return None
    return {key: runtime[key] for key in RUNTIME_FLAT_PV if key in runtime}


def _extract_geo_flat(runtime: dict) -> dict:
    geo: dict[str, Any] = {}
    if "latitude" in runtime:
        geo["latitude"] = float(runtime["latitude"])
    if "longitude" in runtime:
        geo["longitude"] = float(runtime["longitude"])
    if "timezone_name" in runtime and str(runtime["timezone_name"] or "").strip():
        geo["timezone_name"] = str(runtime["timezone_name"]).strip()
    elif "latitude" in geo and "longitude" in geo:
        geo["timezone_name"] = lookup_timezone_name(geo["latitude"], geo["longitude"])
    return geo


def _ensure_battery_wear_on_entry(
    config: dict,
    batteries: list,
    battery_id: str,
    global_wear: dict | None,
    notes: list[str],
) -> None:
    for item in batteries:
        if not isinstance(item, dict) or str(item.get("id", "")).strip() != battery_id:
            continue
        if item.get("battery_wear") is None and global_wear is not None:
            item["battery_wear"] = copy.deepcopy(global_wear)
            notes.append(f"Globaler battery_wear → batteries[] '{battery_id}'.")
        return


def _find_matching_pv(pv_systems: list, flat: dict) -> str | None:
    for item in pv_systems:
        if not isinstance(item, dict):
            continue
        if (
            float(item.get("kwp", -1)) == float(flat["pv_kwp"])
            and float(item.get("pv_tilt", item.get("tilt", -999))) == float(flat["pv_tilt"])
            and float(item.get("pv_azimuth", item.get("azimuth", -999)))
            == float(flat["pv_azimuth"])
        ):
            return str(item["id"]).strip()
    return None


def _find_fixed_export_id(tariffs_doc: dict, k_push: float) -> str | None:
    for item in tariffs_doc.get("export_tariffs", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "")).strip().lower() != "fixed":
            continue
        if abs(float(item.get("k_push_cent", -1)) - float(k_push)) < 1e-4:
            return str(item["id"]).strip()
    return None


def _ensure_import_tariff(tariffs_doc: dict, import_id: str) -> None:
    imports = tariffs_doc.setdefault("import_tariffs", [])
    if any(isinstance(item, dict) and str(item.get("id", "")).strip() == import_id for item in imports):
        return
    imports.append(
        {
            "id": import_id,
            "label": import_id,
            "type": "awattar",
            "land": "AT",
            "currency": "EUR",
        }
    )


def _ensure_export_tariff(tariffs_doc: dict, export_id: str, *, tariff_type: str) -> None:
    exports = tariffs_doc.setdefault("export_tariffs", [])
    if any(isinstance(item, dict) and str(item.get("id", "")).strip() == export_id for item in exports):
        return
    exports.append({"id": export_id, "label": export_id, "type": tariff_type, "land": "AT"})


def _merge_awattar_into_import(
    config: dict,
    tariffs_doc: dict,
    import_id: str,
    notes: list[str],
) -> None:
    awattar = config.get("awattar")
    if not isinstance(awattar, dict):
        return
    for item in tariffs_doc.get("import_tariffs", []):
        if not isinstance(item, dict) or str(item.get("id", "")).strip() != import_id:
            continue
        if str(item.get("type", "")).strip().lower() != "awattar":
            return
        changed = False
        for key in _AWATTAR_IMPORT_KEYS:
            if key in awattar and key not in item:
                item[key] = awattar[key]
                changed = True
        if changed:
            notes.append(f"aWATTar-Aufschläge → import_tariffs '{import_id}' übernommen.")
        return


def _merge_awattar_into_export(
    config: dict,
    tariffs_doc: dict,
    export_id: str,
    notes: list[str],
) -> None:
    awattar = config.get("awattar")
    if not isinstance(awattar, dict):
        return
    for item in tariffs_doc.get("export_tariffs", []):
        if not isinstance(item, dict) or str(item.get("id", "")).strip() != export_id:
            continue
        if str(item.get("type", "")).strip().lower() != "dynamic_epex":
            return
        changed = False
        for key in _AWATTAR_EXPORT_KEYS:
            if key in awattar and key not in item:
                item[key] = awattar[key]
                changed = True
        if changed:
            notes.append(f"aWATTar-Einspeise-Felder → export_tariffs '{export_id}' übernommen.")
        return


def _find_profile(profiles: list, profile_id: str) -> dict | None:
    for item in profiles:
        if isinstance(item, dict) and str(item.get("id", "")).strip() == profile_id:
            return item
    return None


def _find_profile_by_geo(profiles: list, geo: dict) -> str | None:
    lat = geo.get("latitude")
    lon = geo.get("longitude")
    if lat is None or lon is None:
        return None
    for item in profiles:
        if not isinstance(item, dict):
            continue
        if abs(float(item.get("latitude", 999)) - float(lat)) < 0.05 and abs(
            float(item.get("longitude", 999)) - float(lon)
        ) < 0.05:
            return str(item["id"]).strip()
    return None


def _infer_thermal_profile_id(profiles: list) -> str | None:
    for item in profiles:
        if not isinstance(item, dict):
            continue
        profile_id = str(item.get("id", "")).strip()
        if not profile_id:
            continue
        for consumer in item.get("consumers", []):
            if isinstance(consumer, dict) and consumer.get("type") == "thermal_annual":
                return profile_id
    return None


def _apply_geo(profile: dict, geo: dict) -> None:
    if "latitude" in geo:
        profile["latitude"] = geo["latitude"]
    if "longitude" in geo:
        profile["longitude"] = geo["longitude"]
    if "timezone_name" in geo:
        profile["timezone_name"] = geo["timezone_name"]


def _upsert_list_entry(items: list, entry: dict) -> None:
    entry_id = str(entry["id"]).strip()
    for index, item in enumerate(items):
        if isinstance(item, dict) and str(item.get("id", "")).strip() == entry_id:
            items[index] = entry
            return
    items.append(entry)

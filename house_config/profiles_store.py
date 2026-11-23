"""Hausprofile für Backtesting-Planung (Verbraucher, Jahresverbrauch, Grundlast)."""
from __future__ import annotations

import json
import os

from house_config.netznutzung import normalize_netznutzung_config
from house_config.consumption_csv import load_hourly_profile_csv
from data.solar_horizon import stored_horizon_fields
from house_config.house_cooling import COOLING_ENABLED_KEY
from house_config.house_gains import BASELOAD_GAIN_FACTOR_KEY, normalize_baseload_gain_factor
from house_config.house_thermal import (
    HEATING_ENABLED_KEY,
    HOUSE_THERMAL_KEY,
    INACTIVE_CONSUMERS_KEY,
    PERSONS_KEY,
    serialize_house_thermal,
)
from house_config.profiles_consumers import (  # noqa: F401  (re-exported)
    CONSUMER_TYPES,
    _attach_ehal_entity_fields,
    _clean_ehal_bindings,
    _copy_ehal_entity_fields,
    _copy_loxone_binding,
    _legacy_loxone_power_name,
    _loxone_power_name_from_raw,
    _normalize_consumer,
    _normalize_earnie_role,
    _normalize_ev_consumer,
    _normalize_schedule,
    _normalize_thermal_annual_consumer,
    _normalize_thermal_rc,
    _normalize_thermal_rc_consumer,
    _serialize_consumer,
    _set_generic_loxone_inputs,
    _thermal_rc_source,
)
# Profile / plant normalization lives in ``house_config.profiles_normalize``; re-exported.
from house_config.profiles_normalize import (  # noqa: F401
    _BALANCE_SIGN_PARTS,
    BALANCE_SIGN_INVERTS_KEY,
    VAT_DEDUCTIBLE_KEY,
    _attach_internal_gains,
    _float_field_or_default,
    _is_thermal_annual,
    _normalize_balance_sign_inverts,
    _normalize_grid_meter,
    _normalize_plant,
    _normalize_profile,
    _normalize_profile_consumers,
    _normalize_region,
    _plant_max_export_kw,
    _plant_nonneg_float,
    _profile_geo_and_csv_fields,
    normalize_vat_deductible,
)


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {"profiles": []}
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                return json.load(handle)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"house_profiles.json '{path}' ist weder UTF-8 noch cp1252 lesbar.")


def normalize_house_profiles_document(
    doc: dict,
    *,
    heating_systems: dict | None = None,
    wallboxes: dict | None = None,
) -> dict:
    """Normalize a house document; ``heating_systems`` is the catalog (id → entry).

    Required as soon as a profile has a ``thermal_annual`` consumer (its
    ``heating_system_id`` is resolved there, fail loud otherwise). ``wallboxes``
    (id → wallbox, ``components.json``) likewise as soon as a profile has an EV.
    """
    if not isinstance(doc, dict):
        raise ValueError("house_profiles.json muss ein Objekt sein.")
    raw_profiles = doc.get("profiles", [])
    if not isinstance(raw_profiles, list):
        raise ValueError("profiles muss ein Array sein.")
    profiles: dict[str, dict] = {}
    for index, item in enumerate(raw_profiles):
        spec = _normalize_profile(
            item, index, heating_systems=heating_systems, wallboxes=wallboxes
        )
        if spec["id"] in profiles:
            raise ValueError(f"profiles: doppelte id '{spec['id']}'.")
        profiles[spec["id"]] = spec
    out: dict = {"profiles": profiles}
    plant = _normalize_plant(doc.get("plant"))
    if plant:
        out["plant"] = plant
    if "earnie_data_model" in doc:
        out["earnie_data_model"] = doc["earnie_data_model"]
    return out


# Process-wide mtime memo: abs_path → ((file_mtime_ns, shadow, overlay_mtime_ns,
# components_mtime_ns), doc).
_house_profiles_doc_cache: dict[str, tuple[tuple, dict]] = {}


def clear_house_profiles_doc_cache() -> None:
    """Reset house_profiles document memo (tests / forced reload)."""
    _house_profiles_doc_cache.clear()


def _file_mtime_ns(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return -1


def _house_profiles_stamp(path: str, *, shadow: bool) -> tuple[int, bool, int]:
    overlay_mtime = -1
    if shadow:
        try:
            from runtime_store.shadow.hooks import overlay_path

            overlay_mtime = _file_mtime_ns(overlay_path())
        except Exception:  # noqa: BLE001 — overlay optional on load path
            overlay_mtime = -1
    return (_file_mtime_ns(path), shadow, overlay_mtime)


def _heating_catalog_for(path: str, raw: dict) -> dict | None:
    """Catalog next to the house file, read only when a thermal_annual consumer needs it."""
    from house_config.heating_systems import load_heating_systems_for_house

    if not _has_thermal_annual(raw):
        return None
    return load_heating_systems_for_house(path)


def _wallbox_catalog_for(path: str, raw: dict) -> dict | None:
    """Wallboxes next to the house file, read only when an EV consumer needs them."""
    from house_config.wallboxes import load_wallboxes_for_house

    if not _has_consumer_type(raw, "ev"):
        return None
    return load_wallboxes_for_house(path)


def _has_consumer_type(raw: dict, consumer_type: str) -> bool:
    profiles = raw.get("profiles") if isinstance(raw, dict) else None
    items = list(profiles.values()) if isinstance(profiles, dict) else profiles or []
    return any(
        isinstance(consumer, dict)
        and str(consumer.get("type") or "").strip().lower() == consumer_type
        for profile in items
        if isinstance(profile, dict)
        for consumer in [
            *(profile.get("consumers") or []),
            *(profile.get(INACTIVE_CONSUMERS_KEY) or []),
        ]
    )


def _has_thermal_annual(raw: dict) -> bool:
    profiles = raw.get("profiles") if isinstance(raw, dict) else None
    items = list(profiles.values()) if isinstance(profiles, dict) else profiles or []
    return any(
        _is_thermal_annual(consumer)
        for profile in items
        if isinstance(profile, dict)
        for consumer in [
            *(profile.get("consumers") or []),
            *(profile.get(INACTIVE_CONSUMERS_KEY) or []),
        ]
    )


def load_house_profiles_document(path: str) -> dict:
    from house_config.heating_systems import components_path_for_house
    from runtime_store.shadow.mode import is_shadow_config_readonly

    abs_path = os.path.abspath(path)
    shadow = is_shadow_config_readonly()
    # The heating-system catalog lives in components.json: its mtime is part of the stamp.
    stamp = (
        *_house_profiles_stamp(abs_path, shadow=shadow),
        _file_mtime_ns(components_path_for_house(abs_path)),
    )
    cached = _house_profiles_doc_cache.get(abs_path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    raw = _read_json(path)
    doc = normalize_house_profiles_document(
        raw,
        heating_systems=_heating_catalog_for(path, raw),
        wallboxes=_wallbox_catalog_for(path, raw),
    )
    if shadow:
        from runtime_store.shadow.hooks import apply_overlay_to_house

        doc = apply_overlay_to_house(doc)
    _house_profiles_doc_cache[abs_path] = (stamp, doc)
    return doc


def load_default_house_profiles_doc() -> dict | None:
    """Load configured house_profiles.json (plant ehal_bindings, absent, temps)."""
    import logging

    try:
        from runtime_store.persist_paths import resolve_house_profiles_json_path

        path = resolve_house_profiles_json_path()
        if not path or not os.path.isfile(path):
            return None
        return load_house_profiles_document(path)
    except Exception as exc:  # noqa: BLE001 — optional live binding context
        logging.getLogger(__name__).warning(
            "house_profiles für Plant-Bindings nicht geladen: %s", exc
        )
        return None


def _serialize_profile(profile: dict) -> dict:
    out: dict = {
        "id": profile["id"],
        "label": profile["label"],
        "annual_kwh": profile["annual_kwh"],
        "absent_mode": bool(profile.get("absent_mode", False)),
        "total_profile_csv": profile.get("total_profile_csv", ""),
        "pv_profile_csv": profile.get("pv_profile_csv", ""),
        "battery_profile_csv": profile.get("battery_profile_csv", ""),
        "grid_profile_csv": profile.get("grid_profile_csv", ""),
        "historical_csv_source": profile.get("historical_csv_source", "separate"),
        "baseload_distribution": profile.get("baseload_distribution", "equal"),
        # The heating consumer of a house with the switch off is written back after the others.
        "consumers": [
            _serialize_consumer(c)
            for c in [*profile["consumers"], *(profile.get(INACTIVE_CONSUMERS_KEY) or [])]
        ],
        HEATING_ENABLED_KEY: bool(profile[HEATING_ENABLED_KEY]),
        COOLING_ENABLED_KEY: bool(profile.get(COOLING_ENABLED_KEY, False)),
        PERSONS_KEY: int(profile[PERSONS_KEY]),
        VAT_DEDUCTIBLE_KEY: bool(profile[VAT_DEDUCTIBLE_KEY]),
        BASELOAD_GAIN_FACTOR_KEY: normalize_baseload_gain_factor(
            profile.get(BASELOAD_GAIN_FACTOR_KEY), label=f"profiles '{profile['id']}'"
        ),
    }
    if profile.get(HOUSE_THERMAL_KEY):
        out[HOUSE_THERMAL_KEY] = serialize_house_thermal(profile[HOUSE_THERMAL_KEY])
    if profile.get(BALANCE_SIGN_INVERTS_KEY) is not None:
        out[BALANCE_SIGN_INVERTS_KEY] = dict(profile[BALANCE_SIGN_INVERTS_KEY])
    land =str(profile.get("land") or "AT").strip().upper()
    out["land"] = land if land in {"AT", "DE", "CH"} else "AT"
    if profile.get("region"):
        out["region"] = profile["region"]
    if profile.get("latitude") is not None:
        out["latitude"] = profile["latitude"]
    if profile.get("longitude") is not None:
        out["longitude"] = profile["longitude"]
    if profile.get("timezone_name"):
        out["timezone_name"] = profile["timezone_name"]
    if profile.get("default_pv_tilt") is not None:
        out["default_pv_tilt"] = profile["default_pv_tilt"]
    if profile.get("default_pv_azimuth") is not None:
        out["default_pv_azimuth"] = profile["default_pv_azimuth"]
    out["netznutzung"] = normalize_netznutzung_config(profile.get("netznutzung"))
    out.update(stored_horizon_fields(profile))
    return out


def serialize_house_profiles_document(path: str, doc: dict) -> dict:
    """The JSON object ``save_house_profiles_document`` would write for ``doc`` (no write)."""
    from runtime_store.data_model import stamp_data_model

    normalized = normalize_house_profiles_document(
        doc,
        heating_systems=_heating_catalog_for(path, doc),
        wallboxes=_wallbox_catalog_for(path, doc),
    )
    from house_config.heating_systems import assert_reference_systems_unshared

    assert_reference_systems_unshared(normalized)
    serializable = {
        "profiles": [_serialize_profile(p) for p in normalized["profiles"].values()]
    }
    if normalized.get("plant"):
        serializable["plant"] = dict(normalized["plant"])
    stamp_data_model(serializable)
    return serializable


def save_house_profiles_document(path: str, doc: dict) -> None:
    from runtime_store.shadow.mode import is_shadow_config_readonly

    if is_shadow_config_readonly():
        _refuse_shadow_config_write(path)

    serializable = serialize_house_profiles_document(path, doc)
    target = os.path.abspath(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(serializable, handle, indent=4, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, target)
    clear_house_profiles_doc_cache()


def _refuse_shadow_config_write(path: str) -> None:
    """Raise when Shadow would mutate the shared config: a file under the config dir, or
    the active house profile wherever ``EARNIE_HOUSE_PROFILES_PATH`` puts it."""
    from pathlib import Path

    from runtime_store.persist_paths import config_dir, resolve_house_profiles_json_path
    from runtime_store.shadow.errors import ConfigReadOnlyError

    try:
        target = Path(path).resolve()
        cfg_root = Path(config_dir()).resolve()
        active_house = Path(resolve_house_profiles_json_path()).resolve()
        if target == cfg_root or cfg_root in target.parents or target == active_house:
            raise ConfigReadOnlyError(
                f"Shadow Mode: Konfiguration schreibgeschützt ({path})"
            )
    except ConfigReadOnlyError:
        raise
    except Exception:
        cfg = config_dir().replace("\\", "/").rstrip("/")
        norm = str(path).replace("\\", "/")
        if norm == cfg or norm.startswith(cfg + "/"):
            raise ConfigReadOnlyError(
                f"Shadow Mode: Konfiguration schreibgeschützt ({path})"
            ) from None


def profile_list(doc: dict) -> list[dict]:
    return list(doc.get("profiles", {}).values())


def load_profile_total_series(profile: dict) -> list[tuple[str, float]] | None:
    """Lädt Gesamtverbrauchs-CSV falls gesetzt."""
    csv_path = profile.get("total_profile_csv", "")
    if not csv_path:
        return None
    return load_hourly_profile_csv(csv_path)

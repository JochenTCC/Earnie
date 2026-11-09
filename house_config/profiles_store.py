"""Hausprofile für Backtesting-Planung (Verbraucher, Jahresverbrauch, Grundlast)."""
from __future__ import annotations

import json
import os

from house_config.wallboxes import reject_shared_fixed_wallboxes
from house_config.netznutzung import normalize_netznutzung_config
from house_config.baseload import normalize_baseload_distribution
from house_config.consumption_csv import load_hourly_profile_csv
from house_config.geo_timezone import timezone_for_land
from house_config.profile_schema_defaults import profile_default
from house_config.house_cooling import (
    COOLING_ENABLED_KEY,
    COOLING_KEY,
    normalize_cooling_enabled,
)
from house_config.house_gains import (
    BASELOAD_GAIN_FACTOR_KEY,
    INTERNAL_GAINS_KEY,
    internal_gain_descriptor,
    normalize_baseload_gain_factor,
)
from house_config.house_thermal import (
    HEATING_ENABLED_KEY,
    HOUSE_THERMAL_KEY,
    INACTIVE_CONSUMERS_KEY,
    PERSONS_KEY,
    heating_enabled,
    normalize_house_thermal,
    normalize_persons,
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

# D3a VAT flag; carried through load / save, read by the code only with the VAT model.
VAT_DEDUCTIBLE_KEY = "vat_deductible"


def normalize_vat_deductible(raw: object, *, label: str) -> bool:
    """House-level ``vat_deductible`` (missing = schema default ``false``)."""
    if raw is None:
        return bool(profile_default(VAT_DEDUCTIBLE_KEY))
    if not isinstance(raw, bool):
        raise ValueError(f"{label}: vat_deductible muss true oder false sein (ist {raw!r}).")
    return raw


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














def _normalize_profile_consumers(
    consumers_raw: list,
    *,
    profile_id: str,
    latitude: float,
    longitude: float,
    timezone_name: str,
    heating_systems: dict | None,
    house_thermal: dict | None,
    persons: int,
    wallboxes: dict | None,
) -> list[dict]:
    consumers: list[dict] = []
    seen: set[str] = set()
    thermal_consumer_indices: list[int] = []
    for c_index, item in enumerate(consumers_raw):
        consumer = _normalize_consumer(
            item,
            c_index,
            profile_id,
            heating_systems=heating_systems,
            house_thermal=house_thermal,
            persons=persons,
            wallboxes=wallboxes,
        )
        if consumer["type"] == "thermal_annual":
            thermal_consumer_indices.append(c_index)
        if consumer["type"] == "thermal_annual" and consumer.get("thermal"):
            consumer["thermal"]["latitude"] = latitude
            consumer["thermal"]["longitude"] = longitude
            consumer["thermal"]["timezone_name"] = timezone_name
        if consumer["type"] == "thermal_rc" and consumer.get("thermal_rc"):
            consumer["thermal_rc"]["latitude"] = latitude
            consumer["thermal_rc"]["longitude"] = longitude
            consumer["thermal_rc"]["timezone_name"] = timezone_name
        if consumer["id"] in seen:
            raise ValueError(
                f"profiles '{profile_id}': doppelte consumer id '{consumer['id']}'."
            )
        seen.add(consumer["id"])
        consumers.append(consumer)
    if len(thermal_consumer_indices) > 1:
        raise ValueError(
            f"profiles '{profile_id}': nur ein Verbraucher vom Typ "
            "'thermal_annual' (Haus Wärme) erlaubt."
        )
    reject_shared_fixed_wallboxes(consumers, profile_id=profile_id)
    return consumers


def _float_field_or_default(raw: dict, key: str, default: float) -> float:
    """``raw[key]`` as float; only a missing / ``None`` / empty value yields ``default``.

    A legitimate ``0`` (flat roof, longitude 0) is kept; a non-numeric value fails loud.
    """
    value = raw.get(key)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"profiles: {key} ungültig: {value!r}.") from exc


def _normalize_region(raw: dict, land: str) -> str:
    """Optional holiday region (Bundesland/Kanton) for Edibert; empty = none. Unknown = error."""
    region = str(raw.get("region", "") or "").strip()
    if not region:
        return ""
    from house_config.edibert_tariffs import holiday_regions

    if region not in holiday_regions(land):
        raise ValueError(
            f"profiles: region {region!r} ist für Land {land} unbekannt "
            "(Feiertagskalender, Bundesland/Kanton)."
        )
    return region


def _profile_geo_and_csv_fields(raw: dict) -> dict:
    annual_kwh = float(raw.get("annual_kwh", 0.0) or 0.0)
    total_profile_csv = str(raw.get("total_profile_csv", "") or "").strip()
    pv_profile_csv = str(raw.get("pv_profile_csv", "") or "").strip()
    battery_profile_csv = str(raw.get("battery_profile_csv", "") or "").strip()
    grid_profile_csv = str(raw.get("grid_profile_csv", "") or "").strip()
    historical_csv_source = str(raw.get("historical_csv_source", "") or "").strip().lower()
    if historical_csv_source not in ("separate", "energiemonitor", "balance"):
        historical_csv_source = "separate"
    land_raw = str(raw.get("land", "") or "").strip().upper()
    land = land_raw if land_raw in {"AT", "DE", "CH"} else "AT"
    latitude = _float_field_or_default(raw, "latitude", profile_default("latitude"))
    longitude = _float_field_or_default(raw, "longitude", profile_default("longitude"))
    if "netznutzung_arbeitspreis_cent_kwh" in raw:
        raise ValueError(
            "netznutzung_arbeitspreis_cent_kwh wird nicht mehr unterstützt "
            "(ersetzt durch das Objekt 'netznutzung'). Konfiguration migrieren: "
            "Streamlit-Seite „Konfigurations-Migration“ oder "
            "python -m scripts.migrate_config --config-dir <config>"
        )
    profile_id = str(raw.get("id", "") or "").strip() or "?"
    netznutzung = normalize_netznutzung_config(
        raw.get("netznutzung"), label=f"profiles '{profile_id}': netznutzung"
    )
    region = _normalize_region(raw, land)
    return {
        "region": region,
        "annual_kwh": annual_kwh,
        "total_profile_csv": total_profile_csv,
        "pv_profile_csv": pv_profile_csv,
        "battery_profile_csv": battery_profile_csv,
        "grid_profile_csv": grid_profile_csv,
        "historical_csv_source": historical_csv_source or "separate",
        "land": land,
        "latitude": latitude,
        "longitude": longitude,
        "timezone_name": timezone_for_land(land),
        "default_pv_tilt": _float_field_or_default(
            raw, "default_pv_tilt", profile_default("default_pv_tilt")
        ),
        "default_pv_azimuth": _float_field_or_default(
            raw, "default_pv_azimuth", profile_default("default_pv_azimuth")
        ),
        "netznutzung": netznutzung,
    }


def _normalize_profile(
    raw: dict,
    index: int,
    *,
    heating_systems: dict | None,
    wallboxes: dict | None = None,
) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"profiles[{index}] muss ein Objekt sein.")
    profile_id = str(raw.get("id", "")).strip()
    if not profile_id:
        raise ValueError(f"profiles[{index}]: id fehlt.")
    label = str(raw.get("label", profile_id)).strip() or profile_id
    consumers_raw = raw.get("consumers", [])
    if not isinstance(consumers_raw, list):
        raise ValueError(f"profiles '{profile_id}': consumers muss ein Array sein.")
    # A normalized profile handed back for saving parks the heating consumer of a house with
    # „Heizung betrachten“ off here; the switch decides where it goes.
    inactive_raw = raw.get(INACTIVE_CONSUMERS_KEY) or []
    if not isinstance(inactive_raw, list):
        raise ValueError(
            f"profiles '{profile_id}': {INACTIVE_CONSUMERS_KEY} muss ein Array sein."
        )
    consumers_raw = [*consumers_raw, *inactive_raw]
    has_thermal = any(
        _is_thermal_annual(item) for item in consumers_raw
    )
    where = f"profiles '{profile_id}'"
    heating_on = heating_enabled(raw, label=where, has_thermal_consumer=has_thermal)
    thermal_raw = raw.get(HOUSE_THERMAL_KEY)
    house_thermal = (
        None if thermal_raw is None else normalize_house_thermal(thermal_raw, label=where)
    )
    if heating_on and house_thermal is None:
        raise ValueError(
            f"{where}: heating_enabled ist true, aber die Gebäude-Wärmedaten (thermal) "
            "fehlen. Im Hauskonfigurator den Abschnitt „Gebäude / Wärmebedarf“ ausfüllen."
        )
    cooling_on = normalize_cooling_enabled(raw, label=where)
    persons = normalize_persons(raw.get(PERSONS_KEY), label=where)
    vat_deductible = normalize_vat_deductible(raw.get(VAT_DEDUCTIBLE_KEY), label=where)
    baseload_gain = normalize_baseload_gain_factor(
        raw.get(BASELOAD_GAIN_FACTOR_KEY), label=where
    )
    if has_thermal and (raw.get("latitude") is None or raw.get("longitude") is None):
        raise ValueError(
            f"profiles '{profile_id}': latitude und longitude sind bei "
            "thermal_annual-Verbraucher erforderlich."
        )
    fields = _profile_geo_and_csv_fields(raw)
    region = fields.pop("region")
    normalized_consumers = _normalize_profile_consumers(
        consumers_raw,
        profile_id=profile_id,
        latitude=fields["latitude"],
        longitude=fields["longitude"],
        timezone_name=fields["timezone_name"],
        heating_systems=heating_systems,
        house_thermal=house_thermal,
        persons=persons,
        wallboxes=wallboxes,
    )
    # Switch off: the heating consumer is kept for the file but not planned.
    consumers = [
        c for c in normalized_consumers if heating_on or c["type"] != "thermal_annual"
    ]
    inactive = [
        c for c in normalized_consumers if not heating_on and c["type"] == "thermal_annual"
    ]
    _attach_internal_gains(
        consumers, inactive, annual_kwh=fields["annual_kwh"], factor=baseload_gain
    )
    if cooling_on and not any(
        c["type"] == "thermal_annual" and c.get(COOLING_KEY) for c in normalized_consumers
    ):
        raise ValueError(
            f"{where}: cooling_enabled ist true, aber der Haus-Wärme-Verbraucher (thermal_annual) "
            "hat keine Klimaanlage (cooling). Im Hauskonfigurator unter „Kühlung“ eintragen."
        )
    # Grundlast (baseload_kwh / consumer_kwh / baseload_min_kwh) is NOT derived here:
    # it needs Open-Meteo weather and thus a built Config. Resolve at the point of use
    # via house_config.baseload.resolve_profile_baseload / profile_baseload_kwh.
    spec = {
        "id": profile_id,
        "label": label,
        "annual_kwh": fields["annual_kwh"],
        "absent_mode": bool(raw.get("absent_mode", False)),
        "land": fields["land"],
        "latitude": fields["latitude"],
        "longitude": fields["longitude"],
        "timezone_name": fields["timezone_name"],
        "default_pv_tilt": fields["default_pv_tilt"],
        "default_pv_azimuth": fields["default_pv_azimuth"],
        "netznutzung": fields["netznutzung"],
        "total_profile_csv": fields["total_profile_csv"],
        "pv_profile_csv": fields["pv_profile_csv"],
        "battery_profile_csv": fields["battery_profile_csv"],
        "grid_profile_csv": fields["grid_profile_csv"],
        "historical_csv_source": fields["historical_csv_source"],
        "baseload_distribution": normalize_baseload_distribution(
            raw.get("baseload_distribution")
        ),
        "consumers": consumers,
        HEATING_ENABLED_KEY: heating_on,
        COOLING_ENABLED_KEY: cooling_on,
        PERSONS_KEY: persons,
        VAT_DEDUCTIBLE_KEY: vat_deductible,
        BASELOAD_GAIN_FACTOR_KEY: baseload_gain,
    }
    if house_thermal is not None:
        spec[HOUSE_THERMAL_KEY] = house_thermal
    if inactive:
        spec[INACTIVE_CONSUMERS_KEY] = inactive
    # Only when set, so profiles without a region keep their exact normalized shape.
    if region:
        spec["region"] = region
    return spec


def _attach_internal_gains(
    consumers: list[dict], inactive: list[dict], *, annual_kwh: float, factor: float
) -> None:
    """Internal-gain inputs of the year model on the heating consumer (SUSI P2).

    The heating consumer's ``thermal`` gets the Jahresverbrauch, the Grundlast factor and the
    other planned consumers: the year model derives the Grundlast (fixed point with its own
    electric draw) and the hourly internal gains from them. A parked heating consumer (switch
    „Heizung betrachten“ off) gets them too: the cooling run reads the same block.
    """
    others = [c for c in consumers if c["type"] != "thermal_annual"]
    for consumer in [*consumers, *inactive]:
        if consumer["type"] == "thermal_annual" and consumer.get("thermal"):
            consumer["thermal"][INTERNAL_GAINS_KEY] = internal_gain_descriptor(
                annual_kwh=annual_kwh, baseload_factor=factor, consumers=others
            )


def _is_thermal_annual(item: object) -> bool:
    return (
        isinstance(item, dict)
        and str(item.get("type", "")).strip().lower() == "thermal_annual"
    )


def _plant_max_export_kw(raw: dict) -> float | None:
    """Validated ``plant.max_export_power_kw`` (> 0), or None when absent/empty."""
    max_export = raw.get("max_export_power_kw")
    if max_export is None or max_export == "":
        return None
    try:
        export_kw = float(max_export)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"plant.max_export_power_kw ungültig: {max_export!r}."
        ) from exc
    if export_kw <= 0.0:
        raise ValueError(
            "plant.max_export_power_kw muss > 0 sein "
            "(Feld weglassen = keine HK-Einspeisegrenze)."
        )
    return export_kw


def _plant_nonneg_float(raw: dict, key: str) -> float | None:
    """Validated ``plant.<key>`` (>= 0), or None when absent/empty."""
    value = raw.get(key)
    if key not in raw or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"plant.{key} ungültig: {value!r}.") from exc
    if number < 0.0:
        raise ValueError(f"plant.{key} muss >= 0 sein.")
    return number


def _normalize_plant(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    export_kw = _plant_max_export_kw(raw)
    if export_kw is not None:
        out["max_export_power_kw"] = export_kw
    bindings = raw.get("ehal_bindings")
    if isinstance(bindings, dict) and bindings:
        cleaned = _clean_ehal_bindings(bindings)
        if cleaned:
            out["ehal_bindings"] = cleaned
    from house_config.ha_ess_force import normalize_ha_ess_force

    force = normalize_ha_ess_force(raw.get("ha_ess_force"))
    if force:
        out["ha_ess_force"] = force
    from house_config.ha_fail_safe import FAIL_SAFE_VALUES_KEY, normalize_ha_fail_safe_values

    fail_safe = normalize_ha_fail_safe_values(raw.get(FAIL_SAFE_VALUES_KEY))
    if fail_safe:
        out[FAIL_SAFE_VALUES_KEY] = fail_safe
    grid_meter = _normalize_grid_meter(raw.get("grid_meter"))
    if grid_meter is not None:
        out["grid_meter"] = grid_meter
    # Retired: multi-inv plant PV is always Σ inv/pv · η_inv (key dropped on load).
    for key in ("balance_tolerance_pct", "balance_tolerance_w"):
        tolerance = _plant_nonneg_float(raw, key)
        if tolerance is not None:
            out[key] = tolerance
    return out


def _normalize_grid_meter(raw: object) -> dict | None:
    """Optional plant.grid_meter assertion (Topology P1). Absent stays absent."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("plant.grid_meter muss ein Objekt sein.")
    if "at_house_connection" not in raw or "single_tariff" not in raw:
        raise ValueError(
            "plant.grid_meter benötigt at_house_connection und single_tariff "
            "(beide boolean)."
        )
    at_house = raw["at_house_connection"]
    single = raw["single_tariff"]
    if not isinstance(at_house, bool) or not isinstance(single, bool):
        raise ValueError(
            "plant.grid_meter.at_house_connection und single_tariff müssen "
            "boolean sein."
        )
    return {
        "at_house_connection": at_house,
        "single_tariff": single,
    }


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
    land = str(profile.get("land") or "AT").strip().upper()
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
    """Raise when Shadow would mutate files under the shared config dir."""
    from pathlib import Path

    from runtime_store.persist_paths import config_dir
    from runtime_store.shadow.errors import ConfigReadOnlyError

    try:
        target = Path(path).resolve()
        cfg_root = Path(config_dir()).resolve()
        if target == cfg_root or cfg_root in target.parents:
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

"""House profile normalization: one profile (geo, CSV, heating, consumers) and the plant block.

Split from ``house_config.profiles_store`` (KPI refactor); that module re-exports these names.
"""
from __future__ import annotations

from ehal.flex_fields import flex_ehal_slug
from ehal.qualified_ids import consumer_namespace
from house_config.wallboxes import reject_shared_fixed_wallboxes
from house_config.netznutzung import normalize_netznutzung_config
from house_config.baseload import normalize_baseload_distribution
from house_config.geo_timezone import timezone_for_land
from house_config.profile_schema_defaults import profile_default
from data.solar_horizon import (
    copy_horizon_fields,
    normalize_horizon_fields,
    stored_horizon_fields,
)
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
)
from house_config.profiles_consumers import _clean_ehal_bindings, _normalize_consumer


# D3a VAT flag; carried through load / save, read by the code only with the VAT model.
VAT_DEDUCTIBLE_KEY = "vat_deductible"


def normalize_vat_deductible(raw: object, *, label: str) -> bool:
    """House-level ``vat_deductible`` (missing = schema default ``false``)."""
    if raw is None:
        return bool(profile_default(VAT_DEDUCTIBLE_KEY))
    if not isinstance(raw, bool):
        raise ValueError(f"{label}: vat_deductible muss true oder false sein (ist {raw!r}).")
    return raw


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
    horizon_fields: dict | None = None,
) -> list[dict]:
    consumers: list[dict] = []
    seen: set[str] = set()
    seen_kennung: dict[tuple[str, str], str] = {}
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
            # The horizon shades collector and windows of the year model (SUSI P3a).
            copy_horizon_fields(horizon_fields, consumer["thermal"])
        if consumer["type"] == "thermal_rc" and consumer.get("thermal_rc"):
            consumer["thermal_rc"]["latitude"] = latitude
            consumer["thermal_rc"]["longitude"] = longitude
            consumer["thermal_rc"]["timezone_name"] = timezone_name
        if consumer["id"] in seen:
            raise ValueError(
                f"profiles '{profile_id}': doppelte consumer id '{consumer['id']}'."
            )
        seen.add(consumer["id"])
        # ``zaehler_<slug>`` and ``<slug>`` share one EHAL Kennung: one qualified ID would
        # carry the values of two consumers.
        kennung = (
            consumer_namespace(consumer["id"], consumer["type"]),
            flex_ehal_slug(consumer["id"]),
        )
        other = seen_kennung.get(kennung)
        if other is not None:
            raise ValueError(
                f"profiles '{profile_id}': die Verbraucher '{other}' und '{consumer['id']}' "
                f"haben dieselbe EHAL-Kennung '{kennung[0]}.{kennung[1]}' (das Präfix "
                "'zaehler_' zählt nicht zur Kennung) — eine der beiden ids umbenennen."
            )
        seen_kennung[kennung] = consumer["id"]
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
    profile_label = str(raw.get("id", "") or "").strip() or "?"
    if not historical_csv_source:
        historical_csv_source = "separate"
    elif historical_csv_source not in ("separate", "energiemonitor", "balance"):
        raise ValueError(
            f"profiles '{profile_label}': historical_csv_source "
            f"{raw.get('historical_csv_source')!r} ist unbekannt "
            "(erlaubt: separate, energiemonitor, balance)."
        )
    land_raw = str(raw.get("land", "") or "").strip().upper()
    if land_raw and land_raw not in {"AT", "DE", "CH"}:
        raise ValueError(
            f"profiles '{profile_label}': land {raw.get('land')!r} ist unbekannt "
            "(erlaubt: AT, DE, CH)."
        )
    land = land_raw or "AT"
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
    profile_id, label, consumers_raw = _profile_id_label_consumers(raw, index)
    has_thermal = any(
        _is_thermal_annual(item) for item in consumers_raw
    )
    where = f"profiles '{profile_id}'"
    house = _house_switches(raw, profile_id, where, has_thermal=has_thermal)
    fields = _profile_geo_and_csv_fields(raw)
    region = fields.pop("region")
    horizon_fields = normalize_horizon_fields(raw, label=where)
    normalized_consumers = _normalize_profile_consumers(
        consumers_raw,
        profile_id=profile_id,
        latitude=fields["latitude"],
        longitude=fields["longitude"],
        timezone_name=fields["timezone_name"],
        heating_systems=heating_systems,
        house_thermal=house["house_thermal"],
        persons=house[PERSONS_KEY],
        wallboxes=wallboxes,
        horizon_fields=horizon_fields,
    )
    heating_on = house[HEATING_ENABLED_KEY]
    # Switch off: the heating consumer is kept for the file but not planned.
    consumers = [
        c for c in normalized_consumers if heating_on or c["type"] != "thermal_annual"
    ]
    inactive = [
        c for c in normalized_consumers if not heating_on and c["type"] == "thermal_annual"
    ]
    _attach_internal_gains(
        consumers, inactive, annual_kwh=fields["annual_kwh"], factor=house[BASELOAD_GAIN_FACTOR_KEY]
    )
    _require_cooling_consumer(house[COOLING_ENABLED_KEY], normalized_consumers, where)
    spec = _profile_spec(raw, profile_id, label, fields, consumers, house)
    if inactive:
        spec[INACTIVE_CONSUMERS_KEY] = inactive
    signs = _normalize_balance_sign_inverts(raw, where)
    if signs is not None:
        spec[BALANCE_SIGN_INVERTS_KEY] = signs
    # Only when set, so profiles without a region keep their exact normalized shape.
    if region:
        spec["region"] = region
    # Only with a stored horizon (SUSI P3a): no field means no horizon, as before.
    spec.update(stored_horizon_fields(horizon_fields))
    return spec


def _profile_id_label_consumers(raw: dict, index: int) -> tuple[str, str, list]:
    """``(id, label, consumers incl. parked ones)`` of a raw profile; fails loud on a bad shape."""
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
    return profile_id, label, [*consumers_raw, *inactive_raw]


def _house_switches(raw: dict, profile_id: str, where: str, *, has_thermal: bool) -> dict:
    """Heating / cooling switches, building thermal data, persons, VAT flag and gain factor.

    Keys: the profile keys of the values, plus ``house_thermal`` (None without the block).
    """
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
    return {
        HEATING_ENABLED_KEY: heating_on,
        "house_thermal": house_thermal,
        COOLING_ENABLED_KEY: cooling_on,
        PERSONS_KEY: persons,
        VAT_DEDUCTIBLE_KEY: vat_deductible,
        BASELOAD_GAIN_FACTOR_KEY: baseload_gain,
    }


def _require_cooling_consumer(cooling_on: bool, consumers: list[dict], where: str) -> None:
    if cooling_on and not any(
        c["type"] == "thermal_annual" and c.get(COOLING_KEY) for c in consumers
    ):
        raise ValueError(
            f"{where}: cooling_enabled ist true, aber der Haus-Wärme-Verbraucher (thermal_annual) "
            "hat keine Klimaanlage (cooling). Im Hauskonfigurator unter „Kühlung“ eintragen."
        )


def _profile_spec(
    raw: dict, profile_id: str, label: str, fields: dict, consumers: list[dict], house: dict
) -> dict:
    """Normalized profile without the optional trailing keys (parked consumers, signs, region, horizon)."""
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
        HEATING_ENABLED_KEY: house[HEATING_ENABLED_KEY],
        COOLING_ENABLED_KEY: house[COOLING_ENABLED_KEY],
        PERSONS_KEY: house[PERSONS_KEY],
        VAT_DEDUCTIBLE_KEY: house[VAT_DEDUCTIBLE_KEY],
        BASELOAD_GAIN_FACTOR_KEY: house[BASELOAD_GAIN_FACTOR_KEY],
    }
    if house["house_thermal"] is not None:
        spec[HOUSE_THERMAL_KEY] = house["house_thermal"]
    return spec


BALANCE_SIGN_INVERTS_KEY = "balance_sign_inverts"


_BALANCE_SIGN_PARTS = ("pv", "battery", "grid")


def _normalize_balance_sign_inverts(raw: dict, where: str) -> dict[str, bool] | None:
    """Sign flags the Bilanz load was derived with (optional; absent = unknown)."""
    value = raw.get(BALANCE_SIGN_INVERTS_KEY)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{where}: {BALANCE_SIGN_INVERTS_KEY} muss ein Objekt sein.")
    unknown = sorted(set(value) - set(_BALANCE_SIGN_PARTS))
    if unknown:
        raise ValueError(
            f"{where}: {BALANCE_SIGN_INVERTS_KEY} hat unbekannte Felder {unknown} "
            f"(erlaubt: {', '.join(_BALANCE_SIGN_PARTS)})."
        )
    out: dict[str, bool] = {}
    for part in _BALANCE_SIGN_PARTS:
        flag = value.get(part, False)
        if not isinstance(flag, bool):
            raise ValueError(
                f"{where}: {BALANCE_SIGN_INVERTS_KEY}.{part} muss true oder false sein."
            )
        out[part] = flag
    return out


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
    from house_config.pv_forecast_source import (
        PV_FORECAST_SOURCE_KEY,
        normalize_pv_forecast_source,
    )

    pv_source = normalize_pv_forecast_source(raw.get(PV_FORECAST_SOURCE_KEY))
    if pv_source is not None:
        out[PV_FORECAST_SOURCE_KEY] = pv_source
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

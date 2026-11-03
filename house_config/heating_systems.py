"""Heating-system catalog ``heating_systems[]`` in components.json (SUSI P1 follow-up).

Design: ``docs/dev/heating-system-variants.md``. One entry holds the heat generation of a
``thermal_annual`` consumer::

    {"id": "heating_haus", "label": "Wärmepumpe Luft",
     "heat_source": {"type": "heat_pump", "heat_pump_type": "luft"},
     "nominal_power_kw": 3.5, "min_on_quarterhours": 4,
     "heat_storage": {...}, "parts": [{"id": "heating_rod", ...}]}

The consumer keeps the building demand and stores only ``heating_system_id`` (its reference
system = the installed one, used by Live and for the baseload). The house-profile loader
places the resolved system into the normalized consumer (``thermal.heat_source``,
``thermal.heat_storage``, ``parts``, ``nominal_power_kw``, ``min_on_quarterhours``), so the
calculation core reads the same fields as before. Scenarios may select another entry per
consumer (``heating_system_ids``); see ``apply_heating_system``.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Iterable

from house_config.heat_source import normalize_heat_source, normalize_parts
from house_config.id_slug import slug_id

HEATING_SYSTEMS_KEY = "heating_systems"
HEATING_SYSTEM_ID_KEY = "heating_system_id"
SCENARIO_HEATING_SYSTEM_IDS_KEY = "heating_system_ids"
# Fields of an entry that the loader places into the normalized consumer.
SYSTEM_FIELDS: tuple[str, ...] = (
    "heat_source",
    "nominal_power_kw",
    "min_on_quarterhours",
    "heat_storage",
    "parts",
)
_ENTRY_KEYS = frozenset({"id", "label", *SYSTEM_FIELDS})
_MIGRATE_HINT = (
    "Konfiguration migrieren (Streamlit-Seite „Konfigurations-Migration“ oder "
    "python -m scripts.migrate_config --config-dir <config>)"
)


def _min_on_default() -> int:
    from house_config.profile_schema_defaults import consumer_default

    return int(consumer_default("min_on_quarterhours", consumer_type="thermal_annual"))


def normalize_heating_system(raw: Any, index: int) -> dict[str, Any]:
    """Validated catalog entry (fail loud on unknown keys, rod without storage, …)."""
    from optimizer.thermal_coupled import normalize_heat_storage

    where = f"heating_systems[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{where} muss ein Objekt sein.")
    system_id = str(raw.get("id") or "").strip()
    if not system_id:
        raise ValueError(f"{where}: id fehlt.")
    label = f"Heizsystem '{system_id}'"
    extra = sorted(set(raw) - _ENTRY_KEYS)
    if extra:
        raise ValueError(f"{label}: unbekannte Felder {', '.join(extra)}.")
    nominal = float(raw.get("nominal_power_kw", 0.0) or 0.0)
    if nominal < 0.0:
        raise ValueError(f"{label}: nominal_power_kw muss >= 0 sein (ist {nominal}).")
    min_on_default = _min_on_default()
    spec: dict[str, Any] = {
        "id": system_id,
        "label": str(raw.get("label") or system_id).strip() or system_id,
        "heat_source": normalize_heat_source(raw.get("heat_source"), label=label),
        "nominal_power_kw": nominal,
        "min_on_quarterhours": max(
            1, int(raw.get("min_on_quarterhours", min_on_default) or min_on_default)
        ),
    }
    storage = normalize_heat_storage(raw.get("heat_storage"))
    if storage is not None:
        spec["heat_storage"] = storage
    spec["parts"] = normalize_parts(
        raw.get("parts"), label=label, has_heat_storage=storage is not None
    )
    return spec


def normalize_heating_systems(raw_list: Any) -> list[dict[str, Any]]:
    if raw_list is None:
        return []
    if not isinstance(raw_list, list):
        raise ValueError("heating_systems muss ein Array sein.")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_list):
        spec = normalize_heating_system(item, index)
        if spec["id"] in seen:
            raise ValueError(f"heating_systems: doppelte id '{spec['id']}'.")
        seen.add(spec["id"])
        out.append(spec)
    return out


def serialize_heating_system(spec: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": spec["id"],
        "label": spec["label"],
        "heat_source": dict(spec["heat_source"]),
        "nominal_power_kw": spec["nominal_power_kw"],
        "min_on_quarterhours": spec["min_on_quarterhours"],
    }
    if spec.get("heat_storage"):
        out["heat_storage"] = dict(spec["heat_storage"])
    if spec.get("parts"):
        out["parts"] = [dict(part) for part in spec["parts"]]
    return out


def heating_systems_by_id(components_doc: dict | None) -> dict[str, dict[str, Any]]:
    """Normalized catalog of a components document (raw or normalized) by id."""
    raw = (components_doc or {}).get(HEATING_SYSTEMS_KEY)
    return {spec["id"]: spec for spec in normalize_heating_systems(raw)}


def load_heating_systems_for_house(house_profiles_path: str) -> dict[str, dict[str, Any]]:
    """Catalog from ``components.json`` in the same config directory as the house file."""
    from house_config.components_store import load_components_document

    path = components_path_for_house(house_profiles_path)
    if not os.path.isfile(path):
        return {}
    return heating_systems_by_id(load_components_document(path))


def components_path_for_house(house_profiles_path: str) -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(house_profiles_path)), "components.json"
    )


def resolve_heating_system(
    heating_systems: dict[str, dict[str, Any]] | None,
    system_id: Any,
    *,
    label: str,
) -> dict[str, Any]:
    sid = str(system_id or "").strip()
    if not sid:
        raise ValueError(f"{label}: heating_system_id fehlt — {_MIGRATE_HINT}.")
    if heating_systems is None:
        raise ValueError(
            f"{label}: Heizsystem-Katalog (components.json heating_systems) nicht übergeben."
        )
    if sid not in heating_systems:
        raise ValueError(
            f"{label}: heating_system_id '{sid}' fehlt in components.json heating_systems."
        )
    return heating_systems[sid]


def reject_inline_heating_fields(raw: dict[str, Any], *, label: str) -> None:
    """Raw consumers carry only ``heating_system_id``; inline generation fields need migration.

    ``heat_source`` / ``heat_storage`` at the top level exist only in the old file shape (the
    normalized consumer nests them under ``thermal``). Without ``heating_system_id`` the
    consumer is in the old shape anyway.
    """
    if HEATING_SYSTEM_ID_KEY not in raw or "heat_source" in raw or "heat_storage" in raw:
        raise ValueError(
            f"{label}: Wärmeerzeugung gehört in den Heizsystem-Katalog "
            f"(components.json heating_systems, Verweis heating_system_id) — {_MIGRATE_HINT}."
        )


def apply_heating_system(consumer: dict[str, Any], system: dict[str, Any]) -> None:
    """Place a normalized catalog entry into a normalized ``thermal_annual`` consumer (in place)."""
    thermal = consumer.setdefault("thermal", {})
    thermal["heat_source"] = dict(system["heat_source"])
    thermal.pop("heat_storage", None)
    if system.get("heat_storage"):
        thermal["heat_storage"] = dict(system["heat_storage"])
    consumer["parts"] = [dict(part) for part in system.get("parts") or []]
    consumer["nominal_power_kw"] = float(system["nominal_power_kw"])
    consumer["min_on_quarterhours"] = int(system["min_on_quarterhours"])


def split_inline_heating_system(
    consumer: dict[str, Any], *, system_id: str, label: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """House-configurator save: consumer with inline generation fields → (consumer, entry).

    The consumer keeps the building demand plus ``heating_system_id``; the entry holds the
    generation fields (validated by ``normalize_heating_system`` on save).
    """
    item = copy.deepcopy(consumer)
    thermal = item.pop("thermal", None)
    if isinstance(thermal, dict):
        for key, value in thermal.items():
            item.setdefault(key, value)
    entry: dict[str, Any] = {"id": system_id, "label": label}
    for key in SYSTEM_FIELDS:
        if key in item:
            entry[key] = item.pop(key)
    item[HEATING_SYSTEM_ID_KEY] = system_id
    return item, entry


def unique_system_id(base: str, taken: Iterable[str]) -> str:
    taken_set = set(taken)
    candidate = base
    suffix = 2
    while candidate in taken_set:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def reference_system_id(profile_id: str, taken: Iterable[str]) -> str:
    """ID of a reference entry written by the migration or the house configurator."""
    return unique_system_id(f"heating_{str(profile_id).strip()}", taken)


def variant_system_id(label: str, taken: Iterable[str]) -> str:
    return slug_id(label, existing=set(taken))


def _iter_raw_profiles(house_doc: Any) -> list[dict[str, Any]]:
    profiles = house_doc.get("profiles") if isinstance(house_doc, dict) else None
    if isinstance(profiles, dict):
        items = list(profiles.values())
    else:
        items = profiles if isinstance(profiles, list) else []
    return [p for p in items if isinstance(p, dict)]


def reference_ids_by_profile(house_doc: Any) -> dict[str, dict[str, str]]:
    """profile_id → {consumer_id: heating_system_id} (raw or normalized house document)."""
    out: dict[str, dict[str, str]] = {}
    for profile in _iter_raw_profiles(house_doc):
        refs: dict[str, str] = {}
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict) or consumer.get("type") != "thermal_annual":
                continue
            sid = str(consumer.get(HEATING_SYSTEM_ID_KEY) or "").strip()
            if sid:
                refs[str(consumer.get("id") or "")] = sid
        if refs:
            out[str(profile.get("id") or "")] = refs
    return out


def heating_system_usage(
    system_id: str,
    *,
    house_doc: Any,
    scenarios_doc: Any,
) -> list[str]:
    """German descriptions of every house profile / scenario that references ``system_id``."""
    target = str(system_id or "").strip()
    used: list[str] = []
    for profile_id, refs in reference_ids_by_profile(house_doc).items():
        if target in refs.values():
            used.append(f"Hausprofil '{profile_id}' (Referenzsystem)")
    scenarios = scenarios_doc.get("scenarios") if isinstance(scenarios_doc, dict) else None
    for item in scenarios or []:
        if not isinstance(item, dict):
            continue
        settings = item.get("settings") if isinstance(item.get("settings"), dict) else {}
        picks = settings.get(SCENARIO_HEATING_SYSTEM_IDS_KEY)
        if isinstance(picks, dict) and target in {str(v).strip() for v in picks.values()}:
            used.append(f"Szenario '{item.get('id') or '?'}'")
    return used


def normalize_scenario_heating_system_ids(raw: Any, *, label: str) -> dict[str, str]:
    """Scenario ``heating_system_ids`` (consumer_id → heating_system_id); absent = {}."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label}: heating_system_ids muss ein Objekt sein.")
    out: dict[str, str] = {}
    for consumer_id, system_id in raw.items():
        cid = str(consumer_id or "").strip()
        sid = str(system_id or "").strip()
        if not cid or not sid:
            raise ValueError(
                f"{label}: heating_system_ids braucht Verbraucher-ID und Heizsystem-ID "
                f"(ist {consumer_id!r}: {system_id!r})."
            )
        out[cid] = sid
    return out


def read_raw_json(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def merge_inline_reference_systems(
    profile: dict[str, Any],
    catalog: list[dict[str, Any]],
    *,
    existing_refs: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """House-configurator save: move inline generation fields into the reference entry.

    A ``thermal_annual`` consumer edited in the form carries ``heat_source`` & co. inline.
    Its reference entry (the consumer's ``heating_system_id``, else the one stored for this
    consumer in the house file, else a new ``heating_<profile_id>``) is replaced in place by
    the form values; its label is kept. Returns the profile and the updated raw catalog.
    """
    out_profile = copy.deepcopy(profile)
    out_catalog = [copy.deepcopy(item) for item in catalog]
    taken = {str(item.get("id") or "") for item in out_catalog if isinstance(item, dict)}
    refs = existing_refs or {}
    profile_id = str(out_profile.get("id") or "").strip()
    profile_label = str(out_profile.get("label") or profile_id).strip() or profile_id
    consumers = out_profile.get("consumers") or []
    for index, consumer in enumerate(consumers):
        if not isinstance(consumer, dict) or consumer.get("type") != "thermal_annual":
            continue
        flat = dict(consumer)
        thermal = flat.get("thermal")
        if "heat_source" not in flat and not (
            isinstance(thermal, dict) and "heat_source" in thermal
        ):
            continue
        consumer_id = str(consumer.get("id") or "")
        system_id = str(
            consumer.get(HEATING_SYSTEM_ID_KEY) or refs.get(consumer_id) or ""
        ).strip() or reference_system_id(profile_id, taken)
        taken.add(system_id)
        previous = next(
            (item for item in out_catalog if isinstance(item, dict) and item.get("id") == system_id),
            None,
        )
        label = str((previous or {}).get("label") or f"Heizsystem {profile_label}")
        item, entry = split_inline_heating_system(consumer, system_id=system_id, label=label)
        consumers[index] = item
        if previous is None:
            out_catalog.append(entry)
        else:
            out_catalog[out_catalog.index(previous)] = entry
    return out_profile, out_catalog


# --- Scenario variants ---------------------------------------------------------------------
# A scenario profile with a swapped heating system keeps the reference consumers here: every
# baseload derivation (annual, monthly and hourly residual) reads them, the heat load and the
# MILP read ``consumers``. Order guard: the baseload never sees the scenario's system.
BASELOAD_REFERENCE_CONSUMERS_KEY = "baseload_reference_consumers"
HEATING_VARIANTS_KEY = "heating_variants"


def baseload_reference_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """The profile as the baseload sees it (reference heating systems)."""
    reference = profile.get(BASELOAD_REFERENCE_CONSUMERS_KEY)
    if reference is None:
        return profile
    return {**profile, "consumers": reference}


def apply_scenario_heating_systems(
    profile: dict[str, Any],
    picks: dict[str, str],
    heating_systems: dict[str, dict[str, Any]],
    *,
    label: str,
) -> dict[str, Any]:
    """Scenario copy of a normalized house profile with the selected heating systems.

    ``picks`` maps thermal_annual consumer ids to catalog ids; a consumer without a pick keeps
    its reference system. Unknown consumers or systems fail loud. Picking the reference
    system itself changes nothing.
    """
    thermal_ids = {
        str(c.get("id") or ""): c
        for c in profile.get("consumers") or []
        if c.get("type") == "thermal_annual"
    }
    for consumer_id, system_id in picks.items():
        if consumer_id not in thermal_ids:
            raise ValueError(
                f"{label}: heating_system_ids nennt '{consumer_id}', das ist kein "
                f"thermal_annual-Verbraucher des Hausprofils '{profile.get('id')}'."
            )
        if system_id not in heating_systems:
            raise ValueError(
                f"{label}: heating_system_ids['{consumer_id}'] = '{system_id}' fehlt in "
                "components.json heating_systems."
            )
    effective = {
        cid: sid
        for cid, sid in picks.items()
        if sid != thermal_ids[cid].get(HEATING_SYSTEM_ID_KEY)
    }
    if not effective:
        return profile
    out = copy.deepcopy(profile)
    out[BASELOAD_REFERENCE_CONSUMERS_KEY] = copy.deepcopy(profile["consumers"])
    variants: list[dict[str, Any]] = []
    for consumer in out["consumers"]:
        consumer_id = str(consumer.get("id") or "")
        if consumer_id not in effective:
            continue
        reference_id = consumer[HEATING_SYSTEM_ID_KEY]
        apply_heating_system(consumer, heating_systems[effective[consumer_id]])
        consumer[HEATING_SYSTEM_ID_KEY] = effective[consumer_id]
        # A heat-pump meter CSV measures the reference system: the variant is modeled.
        consumer["use_profile_csv"] = False
        variants.append(
            {
                "consumer_id": consumer_id,
                "reference_system_id": reference_id,
                "system_id": effective[consumer_id],
                "measured_heat_meter": _reference_has_own_meter(profile, consumer_id),
            }
        )
    out[HEATING_VARIANTS_KEY] = variants
    return out


def _reference_has_own_meter(profile: dict[str, Any], consumer_id: str) -> bool | None:
    """With measured data: does the reference system have its own meter (exact subtraction)?

    ``None`` without measured data (``profile_spec`` house: nothing is subtracted).
    """
    from house_config.consumption_csv import consumer_uses_profile_csv

    if not str(profile.get("total_profile_csv") or "").strip():
        return None
    consumer = next(c for c in profile["consumers"] if str(c.get("id") or "") == consumer_id)
    return bool(consumer_uses_profile_csv(consumer))


def assert_heating_system_deletable(system_id: str, *, house_doc: Any, scenarios_doc: Any) -> None:
    used = heating_system_usage(system_id, house_doc=house_doc, scenarios_doc=scenarios_doc)
    if used:
        raise ValueError(
            f"Heizsystem '{system_id}' wird noch verwendet: " + ", ".join(used) + "."
        )


# --- Measured heating-rod consumption of the real house (SE baseload) --------------------
# Measured data of the house, not of a heating system: stored on the thermal_annual consumer,
# subtracted in the baseload step only (reference system), whatever variant a scenario picks.
ROD_PROFILE_CSV_KEY = "heating_rod_profile_csv"
ROD_ANNUAL_KWH_KEY = "heating_rod_annual_kwh"


def normalize_measured_rod(raw: dict[str, Any], spec: dict[str, Any], *, label: str) -> None:
    """Copy the optional measured rod fields onto the normalized consumer (fail loud)."""
    csv_path = str(raw.get(ROD_PROFILE_CSV_KEY) or "").strip()
    annual_raw = raw.get(ROD_ANNUAL_KWH_KEY)
    has_annual = annual_raw not in (None, "")
    if not csv_path and not has_annual:
        return
    if csv_path and has_annual:
        raise ValueError(
            f"{label}: {ROD_PROFILE_CSV_KEY} und {ROD_ANNUAL_KWH_KEY} schließen sich aus "
            "(gemessene Heizstab-CSV oder Jahres-kWh, nicht beides)."
        )
    from house_config.heat_source import heating_rod_part

    if heating_rod_part(spec) is None:
        raise ValueError(
            f"{label}: gemessener Heizstab-Verbrauch nur, wenn das Referenz-Heizsystem "
            f"'{spec.get(HEATING_SYSTEM_ID_KEY)}' einen Heizstab hat."
        )
    if csv_path:
        spec[ROD_PROFILE_CSV_KEY] = csv_path
        return
    annual = float(annual_raw)
    if annual <= 0.0:
        raise ValueError(f"{label}: {ROD_ANNUAL_KWH_KEY} muss > 0 sein (ist {annual}).")
    spec[ROD_ANNUAL_KWH_KEY] = annual


def measured_rod_annual_kwh(consumer: dict[str, Any]) -> float:
    """Measured annual rod kWh of a reference consumer (0 without measured rod data)."""
    if consumer.get(ROD_ANNUAL_KWH_KEY) is not None:
        return float(consumer[ROD_ANNUAL_KWH_KEY])
    path = str(consumer.get(ROD_PROFILE_CSV_KEY) or "").strip()
    if not path:
        return 0.0
    from house_config.consumption_csv import estimate_annual_kwh_from_profile_csv

    return estimate_annual_kwh_from_profile_csv(path)


def measured_rod_kw_at(consumer: dict[str, Any], slot_dt: Any) -> float:
    """Measured rod kW at the calendar hour; the annual kWh is spread evenly (lump sum)."""
    path = str(consumer.get(ROD_PROFILE_CSV_KEY) or "").strip()
    if path:
        from data.consumption_profiles import csv_kw_at_datetime

        return csv_kw_at_datetime(path, slot_dt)
    if consumer.get(ROD_ANNUAL_KWH_KEY) is not None:
        return float(consumer[ROD_ANNUAL_KWH_KEY]) / 8760.0
    return 0.0


def profile_measured_rod_kw_at(profile: dict[str, Any], slot_dt: Any) -> float:
    return sum(
        measured_rod_kw_at(consumer, slot_dt)
        for consumer in baseload_reference_profile(profile).get("consumers") or []
        if consumer.get("type") == "thermal_annual"
    )


def heating_rod_double_count_hint(profile: dict[str, Any]) -> str | None:
    """German hint when measured data may contain a real rod the MILP plans again."""
    if not str(profile.get("total_profile_csv") or "").strip():
        return None
    from house_config.heat_source import heating_rod_part

    for consumer in baseload_reference_profile(profile).get("consumers") or []:
        if consumer.get("type") != "thermal_annual" or heating_rod_part(consumer) is None:
            continue
        if consumer.get(ROD_PROFILE_CSV_KEY) or consumer.get(ROD_ANNUAL_KWH_KEY) is not None:
            continue
        return (
            f"Heizstab von „{consumer.get('label') or consumer.get('id')}“: Ohne gemessenen "
            "Heizstab-Verbrauch (CSV oder Jahres-kWh im Hauskonfigurator) steckt ein real "
            "betriebener Heizstab in der Grundlast und wird im Szenario zusätzlich geplant. "
            "Er kann doppelt gezählt sein."
        )
    return None


def heating_variant_hints(profile: dict[str, Any]) -> list[str]:
    """German result hints for swapped heating systems with measured data."""
    hints: list[str] = []
    for variant in profile.get(HEATING_VARIANTS_KEY) or []:
        meter = variant.get("measured_heat_meter")
        if meter is None:
            continue
        if meter:
            hints.append(
                f"Heizsystem-Variante „{variant['system_id']}“: Der gemessene Verbrauch des "
                f"Referenzsystems „{variant['reference_system_id']}“ (eigener Zähler) wurde "
                "exakt abgezogen."
            )
        else:
            hints.append(
                f"Heizsystem-Variante „{variant['system_id']}“: Ohne eigenen Zähler wurde das "
                f"modellierte Profil des Referenzsystems „{variant['reference_system_id']}“ "
                "abgezogen; dessen Modellfehler steckt in der Grundlast."
            )
    return hints


def heating_result_hints_by_scenario(scenarios: dict[str, dict]) -> dict[str, list[str]]:
    """Scenario id → German result hints (variant subtraction, rod double count)."""
    out: dict[str, list[str]] = {}
    for scenario_id, params in scenarios.items():
        profile = params.get("_house_profile") if isinstance(params, dict) else None
        if not isinstance(profile, dict):
            continue
        hints = heating_variant_hints(profile)
        rod = heating_rod_double_count_hint(profile)
        if rod:
            hints.append(rod)
        if hints:
            out[str(scenario_id)] = hints
    return out

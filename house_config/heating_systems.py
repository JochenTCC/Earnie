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
    """Raw consumers carry only ``heating_system_id``; inline generation fields fail loud.

    Every one of the five ``SYSTEM_FIELDS`` on a raw consumer is rejected, also next to a
    ``heating_system_id`` (never overwritten silently by the catalog entry). Without
    ``heating_system_id`` the consumer is in the old file shape and needs the migration.
    """
    if HEATING_SYSTEM_ID_KEY not in raw:
        raise ValueError(
            f"{label}: Wärmeerzeugung gehört in den Heizsystem-Katalog "
            f"(components.json heating_systems, Verweis heating_system_id) — {_MIGRATE_HINT}."
        )
    inline = [key for key in SYSTEM_FIELDS if key in raw]
    if inline:
        raise ValueError(
            f"{label}: {', '.join(inline)} gehört in den Heizsystem-Katalog "
            f"(components.json heating_systems, Eintrag '{raw[HEATING_SYSTEM_ID_KEY]}'), nicht "
            "an den Verbraucher. Feld(er) am Verbraucher entfernen und den Wert im "
            "Hauskonfigurator (Heizsystem) bzw. im Bereich „Heizsysteme“ pflegen."
        )


# Measured heating-rod fields of the earlier design (never released; decided 2026-11-03).
REMOVED_ROD_FIELDS: tuple[str, ...] = ("heating_rod_profile_csv", "heating_rod_annual_kwh")


def reject_measured_rod_fields(raw: dict[str, Any], *, label: str) -> None:
    """Earnie keeps no measured heating-rod consumption (no CSV, no annual kWh)."""
    present = [key for key in REMOVED_ROD_FIELDS if key in raw]
    if present:
        raise ValueError(
            f"{label}: {', '.join(present)} wird nicht mehr unterstützt — Feld entfernen. "
            "Earnie führt keinen gemessenen Heizstab-Verbrauch; der Optimierer plant den "
            "Heizstab allein (siehe docs/konfiguration/flexible-verbraucher.md)."
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


def assert_reference_systems_unshared(house_doc: Any) -> None:
    """An entry is the reference system of at most one house (fail loud otherwise).

    The house configurator edits the reference entry in place; a shared entry would move the
    other house's baseload with it.
    """
    owner: dict[str, str] = {}
    for profile_id, refs in reference_ids_by_profile(house_doc).items():
        for system_id in refs.values():
            if system_id in owner and owner[system_id] != profile_id:
                raise ValueError(
                    f"Heizsystem '{system_id}' ist Referenzsystem von Hausprofil "
                    f"'{owner[system_id]}' und '{profile_id}'. Ein Heizsystem gehört zu "
                    "höchstens einem Haus — für das zweite Haus ein eigenes Heizsystem anlegen "
                    "(Hauskonfigurator, Abschnitt Heizsystem)."
                )
            owner[system_id] = profile_id


def foreign_reference_ids(house_doc: Any, profile_id: str) -> set[str]:
    """Reference systems of every house except ``profile_id``."""
    target = str(profile_id or "").strip()
    return {
        system_id
        for pid, refs in reference_ids_by_profile(house_doc).items()
        if pid != target
        for system_id in refs.values()
    }


def scenario_heating_choices(
    catalog_ids: Iterable[str],
    *,
    house_doc: Any,
    profile_id: str,
    consumer_id: str,
) -> list[str]:
    """Scenario select box: the house's own reference system first, then the variants.

    Variants are entries that are no house's reference system; another house's reference
    system is not offered.
    """
    own = reference_ids_by_profile(house_doc).get(str(profile_id or "").strip(), {})
    own_id = own.get(str(consumer_id or ""))
    references = foreign_reference_ids(house_doc, "") | set(own.values())
    variants = [sid for sid in catalog_ids if sid not in references]
    return ([own_id] if own_id else []) + variants


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


# --- Reference-system change in the house configurator --------------------------------
# Only a change of ``heat_source.type`` of the referenced entry counts, compared with the
# saved house file; heat-pump type, efficiency, power, storage and rod are calibration.


def _inline_heat_source(consumer: dict[str, Any]) -> dict[str, Any] | None:
    source = consumer.get("heat_source")
    if not isinstance(source, dict):
        thermal = consumer.get("thermal")
        source = thermal.get("heat_source") if isinstance(thermal, dict) else None
    return source if isinstance(source, dict) else None


def reference_heat_source_changes(
    edited_consumers: Iterable[dict[str, Any]],
    *,
    saved_house_doc: Any,
    heating_systems: dict[str, dict[str, Any]],
    profile_id: str,
) -> list[dict[str, Any]]:
    """Form consumers whose heat-source type differs from their saved reference entry.

    Each item: ``index``, ``consumer_id``, ``system_id``, ``old_heat_source`` (saved entry)
    and ``new_type``. A house or consumer not yet in the saved file has no change.
    """
    refs = reference_ids_by_profile(saved_house_doc).get(str(profile_id or "").strip(), {})
    out: list[dict[str, Any]] = []
    for index, consumer in enumerate(edited_consumers):
        if not isinstance(consumer, dict) or consumer.get("type") != "thermal_annual":
            continue
        consumer_id = str(consumer.get("id") or "")
        system_id = refs.get(consumer_id)
        new_source = _inline_heat_source(consumer)
        if not system_id or new_source is None:
            continue
        saved = resolve_heating_system(
            heating_systems, system_id, label=f"thermal_annual '{consumer_id}'"
        )
        old_source = saved["heat_source"]
        if str(new_source.get("type")) == str(old_source.get("type")):
            continue
        out.append(
            {
                "index": index,
                "consumer_id": consumer_id,
                "system_id": system_id,
                "old_heat_source": dict(old_source),
                "new_type": str(new_source.get("type")),
            }
        )
    return out


def consumption_data_kind(profile: dict[str, Any], consumer_id: str) -> str | None:
    """Consumption data a heating-system change invalidates: ``csv``, ``annual`` or None.

    ``csv``: measured house data (``total_profile_csv``) or a meter CSV of the heating
    consumer itself; ``annual``: only ``annual_kwh``.
    """
    if str(profile.get("total_profile_csv") or "").strip():
        return "csv"
    consumer = next(
        (
            c
            for c in profile.get("consumers") or []
            if isinstance(c, dict) and str(c.get("id") or "") == consumer_id
        ),
        {},
    )
    if consumer.get("use_profile_csv") and str(consumer.get("profile_csv") or "").strip():
        return "csv"
    if float(profile.get("annual_kwh") or 0.0) > 0.0:
        return "annual"
    return None


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
    foreign_references: Iterable[str] = (),
) -> dict[str, Any]:
    """Scenario copy of a normalized house profile with the selected heating systems.

    ``picks`` maps thermal_annual consumer ids to catalog ids; a consumer without a pick keeps
    its reference system. Unknown consumers or systems and the reference system of another
    house (``foreign_references``, see ``foreign_reference_ids``) fail loud. Picking the
    reference system itself changes nothing.
    """
    foreign = set(foreign_references)
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
        if system_id in foreign and system_id != thermal_ids[consumer_id].get(HEATING_SYSTEM_ID_KEY):
            raise ValueError(
                f"{label}: heating_system_ids['{consumer_id}'] = '{system_id}' ist das "
                "Referenzsystem eines anderen Hauses. Im Szenario sind nur das eigene "
                "Referenzsystem und Varianten wählbar (Variante im Bereich „Heizsysteme“ "
                "anlegen, z. B. als Kopie)."
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
    """Scenario id → German result hints (variant subtraction)."""
    out: dict[str, list[str]] = {}
    for scenario_id, params in scenarios.items():
        profile = params.get("_house_profile") if isinstance(params, dict) else None
        if not isinstance(profile, dict):
            continue
        hints = heating_variant_hints(profile)
        if hints:
            out[str(scenario_id)] = hints
    return out

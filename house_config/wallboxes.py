"""Wallboxes ``components.wallboxes[]`` and the EV ↔ wallbox pair (multi-EV M1, D1–D3).

A wallbox is plant hardware next to the batteries: Kennung, voltage, phases, current range and
the charger bindings (``EVCS_KINDS``). The EV stays a consumer in the house profile with its own
phases and current range and ``wallbox_assignment``.

:func:`resolve_ev_pair` builds the view the runtime code reads from the EV and its fixed
wallbox: ``nominal_power_kw`` / ``min_power_kw`` of the pair, voltage and phases in
``charging_schedule``, ``charger_id`` = the wallbox and the wallbox's charger bindings under its
own Kennung (``evcs.<Wallbox>.*``, M4) merged into the EV's ``ehal_bindings``. Only the
new shape is stored; the view is never written back (:func:`split_ev_view`).

A ``dynamic`` EV (multi-EV M3) has no wallbox of its own: the loader gives it the limits of
the pair with the smallest maximum power among the wallboxes it may use (D8) and no charger
bindings (:func:`resolve_dynamic_ev_view`). The live daemon replaces that view per cycle by the
pair with the wallbox it was assigned to, or by the pool view of the free wallboxes while it is
not assigned (:func:`pool_dynamic_ev_view`, ``runtime_store.ev_assignments``, M4).
"""
from __future__ import annotations

import os
from typing import Any

from ehal.qualified_ids import EVCS_KINDS, NS_EVCS, field_kind

WALLBOXES_KEY = "wallboxes"
WALLBOX_ASSIGNMENT_KEY = "wallbox_assignment"
ASSIGNMENT_FIXED = "fixed"
ASSIGNMENT_DYNAMIC = "dynamic"

# Wallbox policy for a car Earnie has not identified (D6, M3).
UNKNOWN_VEHICLE_KEY = "unknown_vehicle"
UNKNOWN_VEHICLE_OFF = "off"
UNKNOWN_VEHICLE_PV_ONLY = "pv_only"
UNKNOWN_VEHICLE_IMMEDIATE = "immediate"
UNKNOWN_VEHICLE_POLICIES = (UNKNOWN_VEHICLE_OFF, UNKNOWN_VEHICLE_PV_ONLY, UNKNOWN_VEHICLE_IMMEDIATE)

# EV consumer fields of the current model (D2).
EV_PHASES_KEY = "phases"
EV_MIN_CURRENT_KEY = "min_current_a"
EV_MAX_CURRENT_KEY = "max_current_a"

# Fields of the pre-dm6 EV consumer; a pack that still has them must be migrated.
LEGACY_EV_POWER_KEYS = ("nominal_power_kw", "min_power_kw")
LEGACY_SCHEDULE_CONVERSION_KEYS = ("nominal_power_voltage_v", "nominal_power_phases")

# Resolved view keys (runtime only, never stored on the EV).
VIEW_SCHEDULE_VOLTAGE = "nominal_power_voltage_v"
VIEW_SCHEDULE_PHASES = "nominal_power_phases"
VIEW_WALLBOX_KEY = "wallbox"
# Dynamic EV view: the wallboxes it may use (normalized), runtime only.
VIEW_DYNAMIC_KEY = "dynamic_wallboxes"
# Charger Kennung of the view (``evcs.<charger_id>.*``): the wallbox of the pair (M4: fixed
# pairs too; migrated packs have wallbox Kennung = EV Kennung).
VIEW_CHARGER_ID_KEY = "charger_id"
# Live view of a dynamic EV that is not assigned (multi-EV M4, D8): the wallboxes it may use
# that are free at the start of the horizon. The MILP plans these EVs as one pool per slot.
VIEW_POOL_KEY = "pool_wallbox_ids"

# kW of a pair = A × V × phases / 1000; the round trip kW → A → kW of a migrated pack must
# give back the stored kW, so float noise below this precision is cut (not a unit rounding).
_KW_DIGITS = 9

_MIGRATE_HINT = (
    "Konfiguration migrieren (Streamlit-Seite „Konfigurations-Migration“ oder "
    "python -m scripts.migrate_config --config-dir <config>)"
)


def is_charger_binding_key(key: str) -> bool:
    """Binding key of a charger field: bare ``<kind>`` or ``evcs.<Kennung>.<kind>``."""
    name = str(key or "").strip()
    if field_kind(name) not in EVCS_KINDS:
        return False
    return "." not in name or name.startswith(f"{NS_EVCS}.")


def _positive_float(raw: Any, *, label: str, field: str, allow_zero: bool = False) -> float:
    if raw is None or isinstance(raw, bool):
        raise ValueError(f"{label}: {field} fehlt.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: {field} muss eine Zahl sein (ist {raw!r}).") from None
    if value < 0.0 or (value == 0.0 and not allow_zero):
        raise ValueError(f"{label}: {field} muss {'>= 0' if allow_zero else '> 0'} sein.")
    return value


def _phases(raw: Any, *, label: str) -> int:
    if isinstance(raw, bool) or raw not in (1, 2, 3, 1.0, 2.0, 3.0):
        raise ValueError(f"{label}: phases muss 1, 2 oder 3 sein (ist {raw!r}).")
    return int(raw)


def _current_range(raw: dict, *, label: str) -> tuple[float, float]:
    low = _positive_float(raw.get(EV_MIN_CURRENT_KEY), label=label, field=EV_MIN_CURRENT_KEY,
                          allow_zero=True)
    high = _positive_float(raw.get(EV_MAX_CURRENT_KEY), label=label, field=EV_MAX_CURRENT_KEY,
                           allow_zero=True)
    if low > high:
        raise ValueError(
            f"{label}: {EV_MIN_CURRENT_KEY} ({low}) darf nicht größer als "
            f"{EV_MAX_CURRENT_KEY} ({high}) sein."
        )
    return low, high


def normalize_wallbox(raw: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"wallboxes[{index}] muss ein Objekt sein.")
    wallbox_id = str(raw.get("id") or "").strip()
    if not wallbox_id:
        raise ValueError(f"wallboxes[{index}]: id fehlt.")
    label = f"wallboxes '{wallbox_id}'"
    low, high = _current_range(raw, label=label)
    bindings = raw.get("ehal_bindings") or {}
    if not isinstance(bindings, dict):
        raise ValueError(f"{label}: ehal_bindings muss ein Objekt sein.")
    foreign = sorted(k for k in bindings if not is_charger_binding_key(k))
    if foreign:
        raise ValueError(
            f"{label}: ehal_bindings enthält Felder, die nicht zur Wallbox gehören: {foreign}."
        )
    out = {
        "id": wallbox_id,
        "label": str(raw.get("label") or wallbox_id).strip() or wallbox_id,
        "voltage_v": _positive_float(raw.get("voltage_v"), label=label, field="voltage_v"),
        "phases": _phases(raw.get("phases"), label=label),
        EV_MIN_CURRENT_KEY: low,
        EV_MAX_CURRENT_KEY: high,
        "ehal_bindings": {str(k).strip(): str(v or "").strip() for k, v in bindings.items()},
    }
    if raw.get(UNKNOWN_VEHICLE_KEY) is not None:
        out[UNKNOWN_VEHICLE_KEY] = _unknown_vehicle_policy(raw, out, label=label)
    return out


def _unknown_vehicle_policy(raw: dict, wallbox: dict[str, Any], *, label: str) -> str:
    policy = str(raw.get(UNKNOWN_VEHICLE_KEY) or "").strip()
    if policy not in UNKNOWN_VEHICLE_POLICIES:
        raise ValueError(
            f"{label}: {UNKNOWN_VEHICLE_KEY} muss {', '.join(UNKNOWN_VEHICLE_POLICIES)} sein "
            f"(ist {policy!r})."
        )
    if policy == UNKNOWN_VEHICLE_PV_ONLY and not wallbox_binding_key(wallbox, "set_evcs_mode"):
        raise ValueError(
            f"{label}: {UNKNOWN_VEHICLE_KEY} 'pv_only' braucht ein Binding set_evcs_mode an "
            "der Wallbox (PV-Modus des Herstellers)."
        )
    return policy


def wallbox_binding_key(wallbox: dict[str, Any], kind: str) -> str:
    """The wallbox's binding key of ``kind`` (bare or qualified), or ``""``."""
    for key in wallbox.get("ehal_bindings") or {}:
        if field_kind(key) == kind:
            return str(key)
    return ""


def normalize_wallboxes(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("wallboxes muss ein Array sein.")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        spec = normalize_wallbox(item, index=index)
        if spec["id"] in seen:
            raise ValueError(f"wallboxes: doppelte id '{spec['id']}'.")
        seen.add(spec["id"])
        out.append(spec)
    return out


def serialize_wallbox(spec: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": spec["id"],
        "label": spec["label"],
        "voltage_v": float(spec["voltage_v"]),
        "phases": int(spec["phases"]),
        EV_MIN_CURRENT_KEY: float(spec[EV_MIN_CURRENT_KEY]),
        EV_MAX_CURRENT_KEY: float(spec[EV_MAX_CURRENT_KEY]),
        "ehal_bindings": dict(spec.get("ehal_bindings") or {}),
    }
    if spec.get(UNKNOWN_VEHICLE_KEY):
        out[UNKNOWN_VEHICLE_KEY] = str(spec[UNKNOWN_VEHICLE_KEY])
    return out


def wallboxes_by_id(components: dict | None) -> dict[str, dict[str, Any]]:
    """Catalog id → normalized wallbox from a ``components.json`` document."""
    if not isinstance(components, dict):
        return {}
    return {w["id"]: w for w in normalize_wallboxes(components.get(WALLBOXES_KEY))}


def load_wallboxes_for_house(house_profiles_path: str) -> dict[str, dict[str, Any]]:
    """Wallboxes from ``components.json`` in the same config directory as the house file."""
    from house_config.components_store import load_components_document
    from house_config.heating_systems import components_path_for_house

    path = components_path_for_house(house_profiles_path)
    if not os.path.isfile(path):
        return {}
    return wallboxes_by_id(load_components_document(path))


def normalize_wallbox_assignment(raw: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label}: {WALLBOX_ASSIGNMENT_KEY} fehlt — {_MIGRATE_HINT}.")
    mode = str(raw.get("mode") or "").strip()
    if mode == ASSIGNMENT_FIXED:
        wallbox_id = str(raw.get("wallbox_id") or "").strip()
        if not wallbox_id:
            raise ValueError(f"{label}: {WALLBOX_ASSIGNMENT_KEY}.wallbox_id fehlt.")
        return {"mode": ASSIGNMENT_FIXED, "wallbox_id": wallbox_id}
    if mode == ASSIGNMENT_DYNAMIC:
        raw_ids = raw.get("wallbox_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValueError(
                f"{label}: {WALLBOX_ASSIGNMENT_KEY}.wallbox_ids muss mindestens eine Wallbox "
                "nennen."
            )
        ids = [str(i or "").strip() for i in raw_ids]
        if any(not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError(
                f"{label}: {WALLBOX_ASSIGNMENT_KEY}.wallbox_ids enthält leere oder doppelte "
                f"Einträge ({raw_ids!r})."
            )
        return {"mode": ASSIGNMENT_DYNAMIC, "wallbox_ids": ids}
    raise ValueError(
        f"{label}: {WALLBOX_ASSIGNMENT_KEY}.mode muss 'fixed' oder 'dynamic' sein (ist {mode!r})."
    )


def reject_legacy_ev_fields(raw: dict, *, label: str) -> None:
    """A pre-dm6 EV consumer (kW limits, conversion fields, charger bindings) fails loud."""
    legacy = [k for k in LEGACY_EV_POWER_KEYS if k in raw]
    sched = raw.get("charging_schedule")
    if isinstance(sched, dict):
        legacy += [f"charging_schedule.{k}" for k in LEGACY_SCHEDULE_CONVERSION_KEYS if k in sched]
        lox = sched.get("loxone")
        if isinstance(lox, dict):
            legacy += [
                f"charging_schedule.loxone.{k}"
                for k in LEGACY_SCHEDULE_CONVERSION_KEYS
                if k in lox
            ]
    bindings = raw.get("ehal_bindings")
    if isinstance(bindings, dict):
        legacy += [f"ehal_bindings.{k}" for k in bindings if is_charger_binding_key(k)]
    if legacy:
        raise ValueError(
            f"{label}: Felder aus Datenmodell 5 ({', '.join(sorted(legacy))}) gehören jetzt "
            f"an die Wallbox — {_MIGRATE_HINT}."
        )


def normalize_ev_current_fields(raw: dict, *, label: str) -> dict[str, Any]:
    low, high = _current_range(raw, label=label)
    return {
        EV_PHASES_KEY: _phases(raw.get(EV_PHASES_KEY), label=label),
        EV_MIN_CURRENT_KEY: low,
        EV_MAX_CURRENT_KEY: high,
        WALLBOX_ASSIGNMENT_KEY: normalize_wallbox_assignment(
            raw.get(WALLBOX_ASSIGNMENT_KEY), label=label
        ),
    }


def reject_shared_fixed_wallboxes(consumers: list[dict[str, Any]], *, profile_id: str) -> None:
    """Two EVs of one house profile at the same fixed wallbox raise (D3).

    A fixed pair is planned on its own: two cars on one wallbox would be planned as charging
    at the same time. Sharing a wallbox is ``mode: dynamic``. A wallbox is either fixed to one
    EV or open to dynamic EVs within one profile (M3). The same EV in several profiles
    (copied profiles) is no conflict.
    """
    by_wallbox: dict[str, str] = {}
    dynamic: dict[str, str] = {}
    for consumer in consumers:
        if str(consumer.get("type") or "") != "ev":
            continue
        for wallbox_id in dynamic_wallbox_ids(consumer):
            dynamic.setdefault(wallbox_id, str(consumer.get("id") or ""))
    for consumer in consumers:
        if str(consumer.get("type") or "") != "ev":
            continue
        wallbox_id = assigned_wallbox_id(consumer)
        if not wallbox_id:
            continue
        if wallbox_id in dynamic:
            raise ValueError(
                f"profiles '{profile_id}': Wallbox '{wallbox_id}' ist dem E-Auto "
                f"'{consumer.get('id')}' fest zugeordnet und zugleich für das dynamische "
                f"E-Auto '{dynamic[wallbox_id]}' freigegeben. Eine Wallbox ist entweder fest "
                "oder dynamisch."
            )
        other = by_wallbox.get(wallbox_id)
        if other is not None:
            raise ValueError(
                f"profiles '{profile_id}': E-Autos '{other}' und '{consumer.get('id')}' sind "
                f"beide fest der Wallbox '{wallbox_id}' zugeordnet. Eine Wallbox lädt in "
                "dieser Version ein E-Auto je Hausprofil; geteilte Wallboxen folgen mit der "
                "dynamischen Zuordnung."
            )
        by_wallbox[wallbox_id] = str(consumer.get("id") or "")


def pair_limits(ev: dict[str, Any], wallbox: dict[str, Any], *, label: str) -> dict[str, Any]:
    """Current range, phases and voltage of an (EV, wallbox) pair (D2); never clamped."""
    low = max(float(ev[EV_MIN_CURRENT_KEY]), float(wallbox[EV_MIN_CURRENT_KEY]))
    high = min(float(ev[EV_MAX_CURRENT_KEY]), float(wallbox[EV_MAX_CURRENT_KEY]))
    if low > high:
        raise ValueError(
            f"{label}: E-Auto und Wallbox '{wallbox['id']}' haben keinen gemeinsamen Ladestrom "
            f"(Mindeststrom {low} A > Höchststrom {high} A)."
        )
    phases = min(int(ev[EV_PHASES_KEY]), int(wallbox["phases"]))
    voltage = float(wallbox["voltage_v"])
    return {
        "min_current_a": low,
        "max_current_a": high,
        "phases": phases,
        "voltage_v": voltage,
        "min_power_kw": round(low * voltage * phases / 1000.0, _KW_DIGITS),
        "max_power_kw": round(high * voltage * phases / 1000.0, _KW_DIGITS),
    }


def _charger_bindings_of(wallbox: dict[str, Any]) -> dict[str, str]:
    """Charger bindings of a wallbox under its own Kennung (``evcs.<Wallbox>.<kind>``, M4).

    A bare key (``set_evcs_max_current``) is qualified with the wallbox: on an EV's view it
    would otherwise read as the EV's own (``evcs.<EV>.*``).
    """
    return {
        f"{NS_EVCS}.{wallbox['id']}.{field_kind(key)}": value
        for key, value in (wallbox.get("ehal_bindings") or {}).items()
    }


def resolve_ev_pair(
    spec: dict[str, Any],
    wallboxes: dict[str, dict[str, Any]] | None,
    *,
    label: str,
) -> None:
    """Fill the runtime view of the fixed pair into the normalized EV ``spec`` (in place).

    A dynamic EV gets the view of :func:`resolve_dynamic_ev_view` instead.
    """
    if is_dynamic_ev(spec):
        resolve_dynamic_ev_view(spec, wallboxes, label=label)
        return
    wallbox_id = spec[WALLBOX_ASSIGNMENT_KEY]["wallbox_id"]
    wallbox = (wallboxes or {}).get(wallbox_id)
    if wallbox is None:
        raise ValueError(
            f"{label}: Wallbox '{wallbox_id}' fehlt in components.json (wallboxes)."
        )
    _apply_pair_limits(spec, pair_limits(spec, wallbox, label=label))
    spec[VIEW_WALLBOX_KEY] = dict(wallbox)
    spec[VIEW_CHARGER_ID_KEY] = wallbox_id
    merged = _charger_bindings_of(wallbox)
    merged.update(spec.get("ehal_bindings") or {})
    if merged:
        spec["ehal_bindings"] = merged


def _apply_pair_limits(spec: dict[str, Any], limits: dict[str, Any]) -> None:
    spec["nominal_power_kw"] = limits["max_power_kw"]
    spec["min_power_kw"] = limits["min_power_kw"]
    sched = spec["charging_schedule"]
    sched[VIEW_SCHEDULE_VOLTAGE] = limits["voltage_v"]
    sched[VIEW_SCHEDULE_PHASES] = limits["phases"]


def resolve_dynamic_ev_view(
    spec: dict[str, Any],
    wallboxes: dict[str, dict[str, Any]] | None,
    *,
    label: str,
) -> None:
    """Loader view of a dynamic EV (in place): no wallbox of its own, no charger bindings.

    Every wallbox it may use must exist, share a current range with the car and carry an
    ``unknown_vehicle`` policy (D6). The limits are those of the pair with the smallest
    maximum power (D8: a car that is not plugged in; ties by wallbox Kennung). The live
    daemon replaces this view by :func:`assigned_dynamic_ev_view` or :func:`pool_dynamic_ev_view`.
    """
    bindings = spec.get("ehal_bindings") or {}
    charger = sorted(k for k in bindings if is_charger_binding_key(k))
    if charger:
        raise ValueError(
            f"{label}: ein dynamisch zugeordnetes E-Auto hat keine Lade-Bindings "
            f"({', '.join(charger)}); sie gehören an die Wallboxen."
        )
    resolved: list[dict[str, Any]] = []
    for wallbox_id in dynamic_wallbox_ids(spec):
        wallbox = (wallboxes or {}).get(wallbox_id)
        if wallbox is None:
            raise ValueError(
                f"{label}: Wallbox '{wallbox_id}' fehlt in components.json (wallboxes)."
            )
        if not wallbox.get(UNKNOWN_VEHICLE_KEY):
            raise ValueError(
                f"wallboxes '{wallbox_id}': {UNKNOWN_VEHICLE_KEY} fehlt — Pflicht an jeder "
                "Wallbox, die ein dynamisch zugeordnetes E-Auto nutzen darf "
                f"({', '.join(UNKNOWN_VEHICLE_POLICIES)})."
            )
        if not wallbox_binding_key(wallbox, "sens_evcs_connected"):
            raise ValueError(
                f"wallboxes '{wallbox_id}': Binding sens_evcs_connected fehlt — ohne "
                "Stecker-Signal erkennt Earnie kein angestecktes Auto (EHAL-Com)."
            )
        resolved.append(dict(wallbox))
    smallest = min(
        resolved,
        key=lambda w: (pair_limits(spec, w, label=label)["max_power_kw"], w["id"]),
    )
    _apply_pair_limits(spec, pair_limits(spec, smallest, label=label))
    spec[VIEW_DYNAMIC_KEY] = resolved


def assigned_dynamic_ev_view(consumer: dict[str, Any], wallbox_id: str) -> dict[str, Any]:
    """Live view of a dynamic EV assigned to ``wallbox_id`` (a copy; M3).

    Limits of that pair (D2), the wallbox's charger bindings under their own Kennung
    (``evcs.<Wallbox>.*``: the binding stays with the box while the car moves) and
    ``charger_id`` = the wallbox.
    """
    by_id = {w["id"]: w for w in consumer.get(VIEW_DYNAMIC_KEY) or []}
    wallbox = by_id.get(wallbox_id)
    if wallbox is None:
        raise ValueError(
            f"E-Auto '{consumer['id']}' darf Wallbox '{wallbox_id}' nicht nutzen "
            f"(wallbox_ids: {sorted(by_id)})."
        )
    out = dict(consumer)
    out["charging_schedule"] = dict(consumer["charging_schedule"])
    _apply_pair_limits(out, pair_limits(out, wallbox, label=f"E-Auto '{consumer['id']}'"))
    if not out["min_power_kw"]:
        out["min_power_kw"] = None  # MILP shape: no minimum (planning_ev_to_milp)
    out[VIEW_CHARGER_ID_KEY] = wallbox_id
    merged = _charger_bindings_of(wallbox)
    merged.update(consumer.get("ehal_bindings") or {})
    out["ehal_bindings"] = merged
    return out


def wallbox_max_power_kw(wallbox: dict[str, Any]) -> float:
    """Maximum power of a wallbox on its own (max current × voltage × phases)."""
    kw = float(wallbox[EV_MAX_CURRENT_KEY]) * float(wallbox["voltage_v"]) * int(wallbox["phases"])
    return round(kw / 1000.0, _KW_DIGITS)


def pool_dynamic_ev_view(consumer: dict[str, Any], free_wallbox_ids) -> dict[str, Any]:
    """Live view of a dynamic EV that is not assigned (a copy; M4, D8).

    :data:`VIEW_POOL_KEY` lists the wallboxes it may use that are free; the limits are those
    of the pair with the smallest maximum power among them (ties by wallbox Kennung). With no
    free wallbox the list is empty and the loader limits stay: the charging context makes the
    EV inactive (``optimizer.charging_resolve``). No charger: the EV is never written.
    """
    free = {str(w) for w in free_wallbox_ids}
    usable = [dict(w) for w in consumer.get(VIEW_DYNAMIC_KEY) or [] if w["id"] in free]
    out = dict(consumer)
    out["charging_schedule"] = dict(consumer["charging_schedule"])
    out[VIEW_POOL_KEY] = [w["id"] for w in usable]
    if not usable:
        return out
    label = f"E-Auto '{consumer['id']}'"
    smallest = min(usable, key=lambda w: (pair_limits(out, w, label=label)["max_power_kw"], w["id"]))
    _apply_pair_limits(out, pair_limits(out, smallest, label=label))
    if not out["min_power_kw"]:
        out["min_power_kw"] = None  # MILP shape: no minimum (planning_ev_to_milp)
    return out


def is_pool_ev(consumer: dict[str, Any]) -> bool:
    """True for the live view of a dynamic EV that is not assigned (:func:`pool_dynamic_ev_view`)."""
    return VIEW_POOL_KEY in consumer


def split_ev_view(consumer: dict[str, Any], out: dict[str, Any]) -> None:
    """Stored EV fields from a resolved consumer; the pair view is dropped, never written.

    A charger binding on the EV that differs from its wallbox's was edited on the view:
    that edit belongs to the wallbox (Komponenten), so it fails loud instead of being lost.
    """
    out.pop("nominal_power_kw", None)
    out.pop("min_power_kw", None)
    out.pop(VIEW_DYNAMIC_KEY, None)
    out.pop(VIEW_CHARGER_ID_KEY, None)
    out.pop(VIEW_POOL_KEY, None)
    for key in (EV_PHASES_KEY, EV_MIN_CURRENT_KEY, EV_MAX_CURRENT_KEY):
        out[key] = consumer[key]
    out[WALLBOX_ASSIGNMENT_KEY] = dict(consumer[WALLBOX_ASSIGNMENT_KEY])
    sched = dict(out.get("charging_schedule") or {})
    for key in LEGACY_SCHEDULE_CONVERSION_KEYS:
        sched.pop(key, None)
    out["charging_schedule"] = sched
    bindings = out.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return
    wallbox = consumer.get(VIEW_WALLBOX_KEY) or {}
    expected = _charger_bindings_of(wallbox) if wallbox else {}
    kept: dict[str, str] = {}
    for key, value in bindings.items():
        if not is_charger_binding_key(key):
            kept[key] = value
            continue
        if expected.get(key) != value:
            raise ValueError(
                f"E-Auto '{consumer['id']}': Lade-Binding '{key}' gehört an die Wallbox "
                f"'{wallbox.get('id', '?')}' (Komponenten), nicht an das E-Auto."
            )
    if kept:
        out["ehal_bindings"] = kept
    else:
        out.pop("ehal_bindings", None)


# Import key: the voltage of a wallbox an importer creates together with its EV (one set of
# limits for car and wallbox). The save writes it to ``components.json``
# (:func:`route_evs_to_wallboxes`) and drops the key from the EV. The Hauskonfigurator edits
# wallboxes on their own tab and never sends it.
WALLBOX_VOLTAGE_FORM_KEY = "wallbox_voltage_v"


def iter_house_evs(house: Any):
    """(profile id, EV consumer) for every EV of a house document (file or view shape)."""
    profiles = house.get("profiles") if isinstance(house, dict) else None
    items = list(profiles.values()) if isinstance(profiles, dict) else profiles or []
    for profile in items:
        if not isinstance(profile, dict):
            continue
        for key in ("consumers", "inactive_consumers"):
            for consumer in profile.get(key) or []:
                if isinstance(consumer, dict) and str(consumer.get("type") or "") == "ev":
                    yield str(profile.get("id") or ""), consumer


def assigned_wallbox_id(consumer: dict[str, Any]) -> str:
    """Fixed wallbox of an EV; ``""`` for a dynamic EV or without an assignment."""
    raw = consumer.get(WALLBOX_ASSIGNMENT_KEY)
    if not isinstance(raw, dict) or raw.get("mode") == ASSIGNMENT_DYNAMIC:
        return ""
    return str(raw.get("wallbox_id") or "").strip()


def is_dynamic_ev(consumer: dict[str, Any]) -> bool:
    raw = consumer.get(WALLBOX_ASSIGNMENT_KEY)
    return isinstance(raw, dict) and raw.get("mode") == ASSIGNMENT_DYNAMIC


def dynamic_wallbox_ids(consumer: dict[str, Any]) -> list[str]:
    """Wallboxes a dynamic EV may use; ``[]`` for a fixed EV."""
    if not is_dynamic_ev(consumer):
        return []
    raw = consumer[WALLBOX_ASSIGNMENT_KEY].get("wallbox_ids") or []
    return [str(i or "").strip() for i in raw]


def evs_at_wallbox(house: Any, wallbox_id: str) -> list[tuple[str, dict[str, Any]]]:
    """(profile id, EV) of every EV whose fixed wallbox is ``wallbox_id`` or that may use it."""
    target = str(wallbox_id or "").strip()
    return [
        (pid, ev)
        for pid, ev in iter_house_evs(house)
        if assigned_wallbox_id(ev) == target or target in dynamic_wallbox_ids(ev)
    ]


def dynamic_charger_consumers(
    house: Any, components: dict | None = None
) -> list[dict[str, Any]]:
    """One charger entry per wallbox open to dynamic EVs (multi-EV M3), file or view shape.

    ``{"id": <Wallbox>, "type": "ev", "ehal_bindings": <wallbox bindings>}``: binding and
    push code treats it like an EV consumer, so its IDs are ``evcs.<Wallbox>.*``. The
    wallboxes come from ``components["wallboxes"]`` when given, else from the dynamic EVs'
    view (:data:`VIEW_DYNAMIC_KEY`). A wallbox named by a dynamic EV but missing raises.
    """
    catalog: dict[str, dict[str, Any]] = {}
    if isinstance(components, dict) and components.get(WALLBOXES_KEY) is not None:
        catalog = wallboxes_by_id(components)
    wanted: list[str] = []
    for _pid, ev in iter_house_evs(house):
        for wallbox in ev.get(VIEW_DYNAMIC_KEY) or []:
            catalog.setdefault(wallbox["id"], wallbox)
        for wallbox_id in dynamic_wallbox_ids(ev):
            if wallbox_id not in wanted:
                wanted.append(wallbox_id)
    out: list[dict[str, Any]] = []
    for wallbox_id in wanted:
        wallbox = catalog.get(wallbox_id)
        if wallbox is None:
            raise ValueError(f"Wallbox '{wallbox_id}' fehlt in components.json (wallboxes).")
        out.append(
            {
                "id": wallbox_id,
                "type": "ev",
                "ehal_bindings": dict(wallbox.get("ehal_bindings") or {}),
                VIEW_WALLBOX_KEY: dict(wallbox),
            }
        )
    return out


def check_wallbox_pairs(house: Any, wallbox: dict[str, Any]) -> None:
    """Every EV at ``wallbox`` (normalized) keeps a common current with it, else ValueError."""
    for profile_id, ev in evs_at_wallbox(house, wallbox["id"]):
        label = f"Hausprofil '{profile_id}', E-Auto '{ev.get('label') or ev.get('id')}'"
        pair_limits(normalize_ev_current_fields(ev, label=label), wallbox, label=label)


def _wallbox_key(key: str, *, ev_id: str, wallbox_id: str) -> str:
    """EV key ``evcs.<EV>.<kind>`` (an importer's or a pre-M4 editor's) → ``evcs.<Wallbox>.<kind>``."""
    prefix = f"{NS_EVCS}.{ev_id}."
    if key.startswith(prefix):
        return f"{NS_EVCS}.{wallbox_id}.{key[len(prefix):]}"
    return key


def _drop_kind(bindings: dict[str, str], kind: str) -> None:
    for key in [k for k in bindings if field_kind(k) == kind]:
        bindings.pop(key)


def _route_one_ev(
    consumer: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    order: list[str],
) -> dict[str, Any]:
    from house_config.required_signal_activation import activate_wallbox_required

    item = dict(consumer)
    ev_id = str(item.get("id") or "").strip()
    if is_dynamic_ev(item):
        return _route_dynamic_ev(item)
    is_view = VIEW_WALLBOX_KEY in item
    # The view's wallbox limits are edited on the wallbox, never written back from here;
    # its bindings are what the view showed (the base of the binding diff below).
    view_wallbox = item.pop(VIEW_WALLBOX_KEY, None) or {}
    item.pop(VIEW_CHARGER_ID_KEY, None)
    voltage = item.pop(WALLBOX_VOLTAGE_FORM_KEY, None)
    if is_view:
        # Pair view keys (resolve_ev_pair); the stored EV has currents only.
        for key in LEGACY_EV_POWER_KEYS:
            item.pop(key, None)
        sched = item.get("charging_schedule")
        if isinstance(sched, dict):
            item["charging_schedule"] = {
                k: v for k, v in sched.items() if k not in LEGACY_SCHEDULE_CONVERSION_KEYS
            }
    if WALLBOX_ASSIGNMENT_KEY not in item:
        item[WALLBOX_ASSIGNMENT_KEY] = {"mode": ASSIGNMENT_FIXED, "wallbox_id": ev_id}
    wallbox_id = str(item[WALLBOX_ASSIGNMENT_KEY].get("wallbox_id") or "").strip()
    bindings = item.get("ehal_bindings") if isinstance(item.get("ehal_bindings"), dict) else {}
    charger = {
        _wallbox_key(k, ev_id=ev_id, wallbox_id=wallbox_id): v
        for k, v in bindings.items()
        if is_charger_binding_key(k)
    }
    entry = by_id.get(wallbox_id)
    if entry is None and (voltage is not None or charger):
        if voltage is None:
            raise ValueError(
                f"E-Auto '{ev_id}': Wallbox '{wallbox_id}' fehlt in components.json und das "
                "Formular nennt keine Spannung."
            )
        label = str(item.get("label") or ev_id).strip() or ev_id
        entry = {"id": wallbox_id, "label": f"Wallbox {label}", "ehal_bindings": {}}
        order.append(wallbox_id)
    if entry is not None:
        entry = dict(entry)
        if voltage is not None:
            entry.update(
                voltage_v=float(voltage),
                phases=int(item[EV_PHASES_KEY]),
                min_current_a=float(item[EV_MIN_CURRENT_KEY]),
                max_current_a=float(item[EV_MAX_CURRENT_KEY]),
            )
        stored = dict(entry.get("ehal_bindings") or {})
        if is_view:
            # Only what the editor changed against the view is written: several EVs at one
            # wallbox each show its bindings, an unchanged view must not undo another's edit.
            if view_wallbox.get("id") != wallbox_id:
                raise ValueError(
                    f"E-Auto '{ev_id}': die Lade-Bindings stammen von Wallbox "
                    f"'{view_wallbox.get('id')}', das E-Auto ist aber Wallbox '{wallbox_id}' "
                    "zugeordnet."
                )
            # The view shows them qualified (``evcs.<Wallbox>.*``); a stored bare key of the
            # same kind stays as it is unless its value changed.
            shown = _charger_bindings_of(view_wallbox)
            for key, value in charger.items():
                if shown.get(key) != value:
                    _drop_kind(stored, field_kind(key))
                    stored[key] = value
            for key in shown:
                if key not in charger:
                    _drop_kind(stored, field_kind(key))
        else:
            stored.update(charger)
        entry["ehal_bindings"] = stored
        by_id[wallbox_id] = activate_wallbox_required(entry)
    kept = {k: v for k, v in bindings.items() if not is_charger_binding_key(k)}
    if kept:
        item["ehal_bindings"] = kept
    else:
        item.pop("ehal_bindings", None)
    return item


def _route_dynamic_ev(item: dict[str, Any]) -> dict[str, Any]:
    """Stored shape of a dynamic EV: view keys dropped; it has no wallbox side to write."""
    ev_id = str(item.get("id") or "").strip()
    is_view = VIEW_DYNAMIC_KEY in item
    item.pop(VIEW_DYNAMIC_KEY, None)
    item.pop(VIEW_CHARGER_ID_KEY, None)
    if item.pop(WALLBOX_VOLTAGE_FORM_KEY, None) is not None:
        raise ValueError(
            f"E-Auto '{ev_id}': ein dynamisch zugeordnetes E-Auto legt keine Wallbox an."
        )
    if is_view:
        for key in LEGACY_EV_POWER_KEYS:
            item.pop(key, None)
        sched = item.get("charging_schedule")
        if isinstance(sched, dict):
            item["charging_schedule"] = {
                k: v for k, v in sched.items() if k not in LEGACY_SCHEDULE_CONVERSION_KEYS
            }
    bindings = item.get("ehal_bindings") if isinstance(item.get("ehal_bindings"), dict) else {}
    charger = sorted(k for k in bindings if is_charger_binding_key(k))
    if charger:
        raise ValueError(
            f"E-Auto '{ev_id}': Lade-Bindings ({', '.join(charger)}) gehören an die Wallboxen "
            "eines dynamisch zugeordneten E-Autos (Komponenten)."
        )
    return item


def route_evs_to_wallboxes(
    profiles: list[dict[str, Any]], wallboxes: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(profiles in file shape, wallboxes) for a house save.

    Editors hand back EVs as the loader showed them (pair view: kW limits, voltage / phases,
    the wallbox's charger bindings merged in) or as the form / an import built them. The save
    writes the wallbox side to ``components.json``:

    - an import's pair limits (``wallbox_voltage_v`` + the EV's phases and currents) to the
      EV's wallbox; without an assignment the EV gets its own fixed wallbox with its Kennung.
      The view's wallbox limits are never written back (the car limits are the EV's own, D2);
    - charger bindings on the EV to the wallbox (a view's changes against what it showed, an
      import's keys are added);
    - the view keys are dropped from the EV.
    """
    by_id = {str(w.get("id")): dict(w) for w in wallboxes if isinstance(w, dict)}
    order = [str(w.get("id")) for w in wallboxes if isinstance(w, dict)]
    out_profiles: list[dict[str, Any]] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            out_profiles.append(profile)
            continue
        out = dict(profile)
        for key in ("consumers", "inactive_consumers"):
            if key not in out:
                continue
            out[key] = [
                _route_one_ev(c, by_id, order)
                if isinstance(c, dict) and str(c.get("type") or "") == "ev"
                else c
                for c in out.get(key) or []
            ]
        out_profiles.append(out)
    return out_profiles, [by_id[i] for i in order]

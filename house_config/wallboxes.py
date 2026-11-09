"""Wallboxes ``components.wallboxes[]`` and the EV ↔ wallbox pair (multi-EV M1, D1–D3).

A wallbox is plant hardware next to the batteries: Kennung, voltage, phases, current range and
the charger bindings (``EVCS_KINDS``). The EV stays a consumer in the house profile with its own
phases and current range and ``wallbox_assignment``.

Until M2 the runtime handles fixed pairs only. :func:`resolve_ev_pair` builds the view the
runtime code reads today from the EV and its fixed wallbox: ``nominal_power_kw`` /
``min_power_kw`` of the pair, voltage and phases in ``charging_schedule`` and the charger
bindings merged into the EV's ``ehal_bindings``. Only the new shape is stored; the view is
never written back (:func:`split_ev_view`).
"""
from __future__ import annotations

import os
from typing import Any

from ehal.qualified_ids import EVCS_KINDS, NS_EVCS, field_kind

WALLBOXES_KEY = "wallboxes"
WALLBOX_ASSIGNMENT_KEY = "wallbox_assignment"
ASSIGNMENT_FIXED = "fixed"
ASSIGNMENT_DYNAMIC = "dynamic"

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
    return {
        "id": wallbox_id,
        "label": str(raw.get("label") or wallbox_id).strip() or wallbox_id,
        "voltage_v": _positive_float(raw.get("voltage_v"), label=label, field="voltage_v"),
        "phases": _phases(raw.get("phases"), label=label),
        EV_MIN_CURRENT_KEY: low,
        EV_MAX_CURRENT_KEY: high,
        "ehal_bindings": {str(k).strip(): str(v or "").strip() for k, v in bindings.items()},
    }


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
    return {
        "id": spec["id"],
        "label": spec["label"],
        "voltage_v": float(spec["voltage_v"]),
        "phases": int(spec["phases"]),
        EV_MIN_CURRENT_KEY: float(spec[EV_MIN_CURRENT_KEY]),
        EV_MAX_CURRENT_KEY: float(spec[EV_MAX_CURRENT_KEY]),
        "ehal_bindings": dict(spec.get("ehal_bindings") or {}),
    }


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
        # D3: dynamic assignment comes with the assignment engine (M3).
        raise ValueError(
            f"{label}: {WALLBOX_ASSIGNMENT_KEY}.mode 'dynamic' wird von dieser Version noch "
            "nicht unterstützt."
        )
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


def _charger_bindings_for_ev(wallbox: dict[str, Any], ev_id: str) -> dict[str, str]:
    """Wallbox charger bindings keyed as the EV consumer's ``evcs.<EV>.*`` today."""
    prefix = f"{NS_EVCS}.{wallbox['id']}."
    out: dict[str, str] = {}
    for key, value in (wallbox.get("ehal_bindings") or {}).items():
        if key.startswith(prefix):
            key = f"{NS_EVCS}.{ev_id}.{key[len(prefix):]}"
        out[key] = value
    return out


def resolve_ev_pair(
    spec: dict[str, Any],
    wallboxes: dict[str, dict[str, Any]] | None,
    *,
    label: str,
) -> None:
    """Fill the runtime view of the fixed pair into the normalized EV ``spec`` (in place)."""
    wallbox_id = spec[WALLBOX_ASSIGNMENT_KEY]["wallbox_id"]
    wallbox = (wallboxes or {}).get(wallbox_id)
    if wallbox is None:
        raise ValueError(
            f"{label}: Wallbox '{wallbox_id}' fehlt in components.json (wallboxes)."
        )
    limits = pair_limits(spec, wallbox, label=label)
    spec["nominal_power_kw"] = limits["max_power_kw"]
    spec["min_power_kw"] = limits["min_power_kw"]
    sched = spec["charging_schedule"]
    sched[VIEW_SCHEDULE_VOLTAGE] = limits["voltage_v"]
    sched[VIEW_SCHEDULE_PHASES] = limits["phases"]
    spec[VIEW_WALLBOX_KEY] = dict(wallbox)
    merged = _charger_bindings_for_ev(wallbox, spec["id"])
    merged.update(spec.get("ehal_bindings") or {})
    if merged:
        spec["ehal_bindings"] = merged


def split_ev_view(consumer: dict[str, Any], out: dict[str, Any]) -> None:
    """Stored EV fields from a resolved consumer; the pair view is dropped, never written.

    A charger binding on the EV that differs from its wallbox's was edited on the view:
    that edit belongs to the wallbox (Komponenten), so it fails loud instead of being lost.
    """
    out.pop("nominal_power_kw", None)
    out.pop("min_power_kw", None)
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
    expected = _charger_bindings_for_ev(wallbox, consumer["id"]) if wallbox else {}
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


# Hauskonfigurator form key: the voltage of the EV's fixed wallbox. The form edits the pair
# inline (one set of limits for car and wallbox, as dm6 wrote them); the save writes it to
# ``components.json`` (:func:`route_evs_to_wallboxes`) and drops the key from the EV.
WALLBOX_VOLTAGE_FORM_KEY = "wallbox_voltage_v"


def _wallbox_key(key: str, *, ev_id: str, wallbox_id: str) -> str:
    """EV view key ``evcs.<EV>.<kind>`` → the wallbox's ``evcs.<Wallbox>.<kind>``."""
    prefix = f"{NS_EVCS}.{ev_id}."
    if key.startswith(prefix):
        return f"{NS_EVCS}.{wallbox_id}.{key[len(prefix):]}"
    return key


def _route_one_ev(
    consumer: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    order: list[str],
) -> dict[str, Any]:
    from house_config.required_signal_activation import activate_wallbox_required

    item = dict(consumer)
    ev_id = str(item.get("id") or "").strip()
    is_view = VIEW_WALLBOX_KEY in item
    view_wallbox = item.pop(VIEW_WALLBOX_KEY, None)
    voltage = item.pop(WALLBOX_VOLTAGE_FORM_KEY, None)
    if voltage is None and isinstance(view_wallbox, dict):
        voltage = view_wallbox.get("voltage_v")
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
            # The view showed every charger key of the wallbox: what the editor left is it.
            stored = charger
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


def route_evs_to_wallboxes(
    profiles: list[dict[str, Any]], wallboxes: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(profiles in file shape, wallboxes) for a house save.

    Editors hand back EVs as the loader showed them (pair view: kW limits, voltage / phases,
    the wallbox's charger bindings merged in) or as the form / an import built them. The save
    writes the wallbox side to ``components.json``:

    - the form's pair limits (``wallbox_voltage_v`` + the EV's phases and currents) to the
      EV's wallbox, a new EV gets its own fixed wallbox with its Kennung;
    - charger bindings on the EV to the wallbox (a view's set replaces the wallbox's, an
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

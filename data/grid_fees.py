"""Zeitabhängiges Netznutzungsentgelt (Arbeitspreis): Katalog, Auflösung, Auswertung.

Modell (siehe ``docs/konfiguration/preise.md``):

* Katalog ``share/config/grid_fees.json``: Netzbereiche mit Basis-Arbeitspreis
  (nicht gemessene / gemessene Leistung) und Verweis auf einen Regelsatz.
* Regelsatz: Liste zeitgebundener Regeln (z. B. SNAP, WiNAP). Eine Regel ändert den
  Basis-Arbeitspreis in einem Zeitfenster (``percent_off``, ``absolute_cent``,
  ``add_cent``).
* Hausprofil (``netznutzung``): wählt Netzbereich und optional eigenen Basiswert.
  Messart is always unmetered household (``unmetered_power``). :func:`resolve_grid_fee_spec`
  erzeugt daraus die aufgelöste Spec, die :func:`grid_fee_work_cent` pro Slot auswertet.

Alle Preise netto (ohne USt), Cent/kWh. Fehlkonfiguration schlägt laut fehl.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

STATUS_VERORDNET = "verordnet"
STATUS_ENTWURF = "entwurf"
STATUS_ILLUSTRATIV = "illustrativ"
VALID_STATUS = frozenset({STATUS_VERORDNET, STATUS_ENTWURF, STATUS_ILLUSTRATIV})

MODE_PERCENT_OFF = "percent_off"
MODE_ABSOLUTE_CENT = "absolute_cent"
MODE_ADD_CENT = "add_cent"
VALID_MODES = frozenset({MODE_PERCENT_OFF, MODE_ABSOLUTE_CENT, MODE_ADD_CENT})

REQUIRES_QUARTER_HOUR_METER = "quarter_hour_meter"
VALID_REQUIRES = frozenset({REQUIRES_QUARTER_HOUR_METER})

METERING_UNMETERED = "unmetered_power"
METERING_METERED = "metered_power"  # catalog key only; profile always uses unmetered

DEFAULT_INCLUDE_STATUS = (STATUS_VERORDNET,)

_MINUTES_PER_DAY = 24 * 60


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #

def _parse_hhmm(raw: Any, *, label: str) -> int:
    text = str(raw or "").strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"{label}: Uhrzeit '{raw}' muss 'HH:MM' sein.")
    hour, minute = int(parts[0]), int(parts[1])
    if hour == 24 and minute == 0:
        return _MINUTES_PER_DAY
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{label}: Uhrzeit '{raw}' außerhalb 00:00–24:00.")
    return hour * 60 + minute


def _parse_iso_date(raw: Any, *, label: str) -> str | None:
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw)).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label}: Datum '{raw}' muss ISO (YYYY-MM-DD) sein.") from exc


def _int_list(raw: Any, *, label: str, low: int, high: int) -> list[int] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{label} muss eine nicht-leere Liste oder null sein.")
    out: list[int] = []
    for item in raw:
        try:
            value = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}: '{item}' ist keine ganze Zahl.") from exc
        if not (low <= value <= high):
            raise ValueError(f"{label}: {value} außerhalb {low}–{high}.")
        out.append(value)
    return sorted(set(out))


def _normalize_effect(raw: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label}: effect muss ein Objekt sein.")
    mode = str(raw.get("mode", "")).strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(
            f"{label}: effect.mode '{mode}' ungültig. Erlaubt: {', '.join(sorted(VALID_MODES))}."
        )
    value = raw.get("value")
    if value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}: effect.value '{value}' ist keine Zahl.") from exc
        if mode == MODE_PERCENT_OFF and not (0.0 <= value <= 100.0):
            raise ValueError(f"{label}: percent_off muss 0–100 sein.")
        if mode == MODE_ABSOLUTE_CENT and value < 0.0:
            raise ValueError(f"{label}: absolute_cent muss >= 0 sein.")
    return {"mode": mode, "value": value}


def normalize_rule(raw: Any, *, label: str) -> dict[str, Any]:
    """Validiert eine Regel des Katalogs und gibt die kanonische Form zurück."""
    if not isinstance(raw, dict):
        raise ValueError(f"{label}: Regel muss ein Objekt sein.")
    rule_id = str(raw.get("id", "")).strip()
    if not rule_id:
        raise ValueError(f"{label}: id fehlt.")
    label = f"{label} '{rule_id}'"
    status = str(raw.get("status", "")).strip().lower()
    if status not in VALID_STATUS:
        raise ValueError(
            f"{label}: status '{status}' ungültig. Erlaubt: {', '.join(sorted(VALID_STATUS))}."
        )
    time_raw = raw.get("time")
    if time_raw is None:
        from_min, to_min = 0, _MINUTES_PER_DAY
    else:
        if not isinstance(time_raw, dict):
            raise ValueError(f"{label}: time muss ein Objekt {{from,to}} oder null sein.")
        from_min = _parse_hhmm(time_raw.get("from"), label=f"{label}: time.from")
        to_min = _parse_hhmm(time_raw.get("to"), label=f"{label}: time.to")
        if from_min == to_min:
            raise ValueError(f"{label}: time.from und time.to dürfen nicht gleich sein.")
    requires_raw = raw.get("requires") or []
    if not isinstance(requires_raw, list):
        raise ValueError(f"{label}: requires muss eine Liste sein.")
    requires = [str(item).strip() for item in requires_raw]
    for item in requires:
        if item not in VALID_REQUIRES:
            raise ValueError(
                f"{label}: requires '{item}' unbekannt. Erlaubt: {', '.join(sorted(VALID_REQUIRES))}."
            )
    valid_from = _parse_iso_date(raw.get("valid_from"), label=f"{label}: valid_from")
    valid_to = _parse_iso_date(raw.get("valid_to"), label=f"{label}: valid_to")
    if valid_from and valid_to and valid_to < valid_from:
        raise ValueError(f"{label}: valid_to liegt vor valid_from.")
    return {
        "id": rule_id,
        "label": str(raw.get("label") or rule_id).strip() or rule_id,
        "status": status,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "months": _int_list(raw.get("months"), label=f"{label}: months", low=1, high=12),
        "weekdays": _int_list(raw.get("weekdays"), label=f"{label}: weekdays", low=0, high=6),
        "from_min": from_min,
        "to_min": to_min,
        "effect": _normalize_effect(raw.get("effect"), label=label),
        "requires": requires,
        "source": str(raw.get("source", "") or "").strip(),
        "note": str(raw.get("note", "") or "").strip(),
    }


# --------------------------------------------------------------------------- #
# Katalog
# --------------------------------------------------------------------------- #

def normalize_grid_fee_catalog(doc: Any) -> dict[str, Any]:
    """Validiert ``grid_fees.json`` und liefert ``{"rule_sets": {...}, "areas": {...}}``."""
    if not isinstance(doc, dict):
        raise ValueError("grid_fees.json muss ein Objekt sein.")
    rule_sets_raw = doc.get("rule_sets", {})
    if not isinstance(rule_sets_raw, dict):
        raise ValueError("grid_fees: rule_sets muss ein Objekt sein.")
    rule_sets: dict[str, list[dict[str, Any]]] = {}
    for set_id, rules_raw in rule_sets_raw.items():
        if not isinstance(rules_raw, list):
            raise ValueError(f"grid_fees: rule_sets['{set_id}'] muss eine Liste sein.")
        rules = [
            normalize_rule(item, label=f"grid_fees rule_sets['{set_id}']")
            for item in rules_raw
        ]
        ids = [rule["id"] for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError(f"grid_fees: rule_sets['{set_id}'] hat doppelte Regel-IDs.")
        rule_sets[str(set_id)] = rules
    areas_raw = doc.get("areas", [])
    if not isinstance(areas_raw, list):
        raise ValueError("grid_fees: areas muss eine Liste sein.")
    areas: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(areas_raw):
        if not isinstance(item, dict):
            raise ValueError(f"grid_fees: areas[{index}] muss ein Objekt sein.")
        area_id = str(item.get("id", "")).strip()
        if not area_id:
            raise ValueError(f"grid_fees: areas[{index}]: id fehlt.")
        if area_id in areas:
            raise ValueError(f"grid_fees: Netzbereich '{area_id}' doppelt.")
        base = item.get("base_cent_kwh")
        if not isinstance(base, dict):
            raise ValueError(f"grid_fees: Netzbereich '{area_id}': base_cent_kwh fehlt.")
        base_norm: dict[str, float] = {}
        for key in (METERING_UNMETERED, METERING_METERED):
            value = float(base.get(key))
            if value < 0.0:
                raise ValueError(f"grid_fees: Netzbereich '{area_id}': {key} muss >= 0 sein.")
            base_norm[key] = value
        set_id = item.get("rule_set")
        if set_id is not None and str(set_id) not in rule_sets:
            raise ValueError(
                f"grid_fees: Netzbereich '{area_id}' verweist auf unbekannten rule_set '{set_id}'."
            )
        areas[area_id] = {
            "id": area_id,
            "label": str(item.get("label") or area_id).strip() or area_id,
            "land": str(item.get("land", "AT")).strip().upper(),
            "base_cent_kwh": base_norm,
            "rule_set": str(set_id) if set_id is not None else None,
            "source": str(item.get("source", "") or "").strip(),
        }
    return {"rule_sets": rule_sets, "areas": areas}


def load_grid_fee_catalog(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return normalize_grid_fee_catalog(json.load(handle))


# --------------------------------------------------------------------------- #
# Profil-Konfiguration (Hausprofil-Feld ``netznutzung``)
# --------------------------------------------------------------------------- #

def default_netznutzung_config() -> dict[str, Any]:
    return {
        "area_id": None,
        "power_metering": METERING_UNMETERED,
        # Assumed present — not an Earnie configuration (SNAP/WiNAP catalog requires).
        "quarter_hour_meter": True,
        "base_cent_kwh": 0.0,
        "include_status": list(DEFAULT_INCLUDE_STATUS),
    }


def normalize_netznutzung_config(raw: Any, *, label: str = "netznutzung") -> dict[str, Any]:
    """Validiert das Profilfeld ``netznutzung`` (kein Legacy-Skalar)."""
    if raw is None:
        return default_netznutzung_config()
    if not isinstance(raw, dict):
        raise ValueError(f"{label} muss ein Objekt sein.")
    area_raw = raw.get("area_id")
    area_id = str(area_raw).strip() if area_raw not in (None, "") else None
    # Assumed household unmetered — not an Earnie configuration.
    metering = METERING_UNMETERED
    base_raw = raw.get("base_cent_kwh")
    base = float(base_raw) if base_raw is not None else 0.0
    if base < 0.0:
        raise ValueError(f"{label}.base_cent_kwh muss >= 0 sein.")
    include_raw = raw.get("include_status", list(DEFAULT_INCLUDE_STATUS))
    if not isinstance(include_raw, list):
        raise ValueError(f"{label}.include_status muss eine Liste sein.")
    include = [str(item).strip().lower() for item in include_raw]
    for item in include:
        if item not in VALID_STATUS:
            raise ValueError(
                f"{label}.include_status '{item}' ungültig. "
                f"Erlaubt: {', '.join(sorted(VALID_STATUS))}."
            )
    return {
        "area_id": area_id,
        "power_metering": metering,
        "quarter_hour_meter": True,
        "base_cent_kwh": base,
        "include_status": include,
    }


# --------------------------------------------------------------------------- #
# Auflösung
# --------------------------------------------------------------------------- #

def resolve_grid_fee_spec(
    netznutzung: dict[str, Any] | None,
    catalog: dict[str, Any] | None,
    *,
    timezone_name: str,
) -> dict[str, Any]:
    """Löst Profilfeld + Katalog zur auswertbaren Spec auf.

    Ist ein Netzbereich gewählt, kommt der Basiswert aus dem Katalog
    (``unmetered_power``); ``base_cent_kwh`` am Profil wird dann ignoriert. Ohne
    Netzbereich gilt der Profilwert ohne Regeln. Regeln mit ``status`` außerhalb
    ``include_status`` werden mit Grund in ``skipped`` vermerkt. Eine einbezogene
    Regel ohne Wert (``effect.value`` null) ist ein Fehler.
    """
    cfg = normalize_netznutzung_config(netznutzung)
    area_id = cfg["area_id"]
    rules: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    if area_id is None:
        base = cfg["base_cent_kwh"]
        area_label = None
    else:
        if catalog is None:
            raise ValueError(
                f"Netzbereich '{area_id}' gewählt, aber kein Netzentgelt-Katalog geladen."
            )
        areas = catalog["areas"]
        if area_id not in areas:
            raise ValueError(
                f"Unbekannter Netzbereich '{area_id}' im Netzentgelt-Katalog."
            )
        area = areas[area_id]
        base = area["base_cent_kwh"][cfg["power_metering"]]
        area_label = area["label"]
        set_id = area["rule_set"]
        for rule in catalog["rule_sets"].get(set_id, []) if set_id else []:
            if rule["status"] not in cfg["include_status"]:
                skipped.append({"id": rule["id"], "reason": f"status={rule['status']}"})
                continue
            # Catalog may list REQUIRES_QUARTER_HOUR_METER; Earnie assumes it exists.
            if rule["effect"]["value"] is None:
                raise ValueError(
                    f"Regel '{rule['id']}' (status={rule['status']}) ist einbezogen, "
                    "hat aber keinen Wert (effect.value). Status aus include_status "
                    "entfernen oder Wert im Katalog ergänzen."
                )
            rules.append(rule)
    return {
        "area_id": area_id,
        "area_label": area_label,
        "timezone_name": str(timezone_name),
        "base_cent_kwh": float(base),
        "rules": rules,
        "skipped": skipped,
    }


def flat_grid_fee_spec(base_cent_kwh: float, *, timezone_name: str = "Europe/Vienna") -> dict[str, Any]:
    """Konstante Spec ohne Regeln (Tests, einfache Fälle)."""
    return {
        "area_id": None,
        "area_label": None,
        "timezone_name": timezone_name,
        "base_cent_kwh": float(base_cent_kwh),
        "rules": [],
        "skipped": [],
    }


# --------------------------------------------------------------------------- #
# Auswertung
# --------------------------------------------------------------------------- #

def _rule_matches(rule: dict[str, Any], local: datetime) -> bool:
    day_iso = local.date().isoformat()
    if rule["valid_from"] and day_iso < rule["valid_from"]:
        return False
    if rule["valid_to"] and day_iso > rule["valid_to"]:
        return False
    if rule["months"] is not None and local.month not in rule["months"]:
        return False
    if rule["weekdays"] is not None and local.weekday() not in rule["weekdays"]:
        return False
    minute = local.hour * 60 + local.minute
    start, end = rule["from_min"], rule["to_min"]
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def _apply_effect(base: float, effect: dict[str, Any]) -> float:
    value = float(effect["value"])
    mode = effect["mode"]
    if mode == MODE_PERCENT_OFF:
        return base * (1.0 - value / 100.0)
    if mode == MODE_ABSOLUTE_CENT:
        return value
    return base + value


def matching_rule(spec: dict[str, Any], slot_datetime: datetime) -> dict[str, Any] | None:
    """Erste passende Regel für den Slot (Reihenfolge im Regelsatz) oder ``None``."""
    if not spec["rules"]:
        return None
    local = _to_local(slot_datetime, spec["timezone_name"])
    for rule in spec["rules"]:
        if _rule_matches(rule, local):
            return rule
    return None


def _to_local(slot_datetime: datetime, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    if slot_datetime.tzinfo is None:
        return slot_datetime.replace(tzinfo=tz)
    return slot_datetime.astimezone(tz)


def grid_fee_work_cent(spec: dict[str, Any], slot_datetime: datetime | None) -> float:
    """Netto-Arbeitspreis (Cent/kWh) für den Slot. Erste passende Regel gewinnt."""
    if not spec["rules"]:
        return float(spec["base_cent_kwh"])
    if slot_datetime is None:
        raise ValueError(
            "Netzentgelt mit Zeitregeln erfordert slot_datetime (Preis ist zeitabhängig)."
        )
    rule = matching_rule(spec, slot_datetime)
    if rule is None:
        return float(spec["base_cent_kwh"])
    return _apply_effect(float(spec["base_cent_kwh"]), rule["effect"])

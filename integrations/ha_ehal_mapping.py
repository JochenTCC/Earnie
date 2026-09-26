"""HA entity → EHAL field heuristic propose (2.6.b / 2.6.c). No LLM."""
from __future__ import annotations

from typing import Any

from integrations.ha_adapter import (
    SETPOINT_FIELDS,
    TELEMETRY_ENERGY_OPTIONAL,
    TELEMETRY_OPTIONAL,
    TELEMETRY_REQUIRED,
    WRITE_DOMAINS,
)
from integrations.ha_units import describe_conversion, field_quantity, unit_check

EHAL_HA_FIELDS = (
    TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL + TELEMETRY_ENERGY_OPTIONAL + SETPOINT_FIELDS
)

_SENSOR_DOMAINS = frozenset({"sensor"})
_WRITE_DOMAINS = WRITE_DOMAINS
_ENERGY_EXCLUDE = ("energy", "ertrag", "kwh", "wh ")

# Per-field: name hints, allowed domains, optional device_class / unit boosts.
_FIELD_RULES: dict[str, dict[str, Any]] = {
    "sens_grid_power_active": {
        "hints": ("grid", "netz", "bezug", "energieversorger"),
        "domains": _SENSOR_DOMAINS,
        "device_classes": ("power",),
        "units": ("w", "kw", "watt", "kilowatt", "kilowatts"),
        "exclude_hints": _ENERGY_EXCLUDE,
    },
    "sens_pv_production_active": {
        "hints": ("pv", "solar", "produktion", "erzeug"),
        "domains": _SENSOR_DOMAINS,
        "device_classes": ("power",),
        "units": ("w", "kw", "watt", "kilowatt", "kilowatts"),
        "exclude_hints": _ENERGY_EXCLUDE,
    },
    "sens_ess_soc": {
        "hints": ("soc", "ladezustand", "battery_soc", "batterie_soc"),
        "domains": _SENSOR_DOMAINS,
        "device_classes": ("battery",),
        "units": ("%", "percent"),
    },
    "sens_ess_power": {
        "hints": ("battery_power", "batterie", "speicher", "akku", "ess_power"),
        "domains": _SENSOR_DOMAINS,
        "device_classes": ("power",),
        "units": ("w", "kw", "watt", "kilowatt", "kilowatts"),
        "exclude_hints": ("soc", "grid", "pv", "loadpoint", "charge_power")
        + _ENERGY_EXCLUDE,
    },
    "sens_evcs_active_power": {
        "hints": (
            "loadpoint",
            "charge_power",
            "wallbox",
            "evcs",
            "e-auto",
            "eauto",
        ),
        "domains": _SENSOR_DOMAINS,
        "device_classes": ("power",),
        "units": ("w", "kw", "watt", "kilowatt", "kilowatts"),
        "exclude_hints": _ENERGY_EXCLUDE,
    },
    "sens_power_consumers": {
        "hints": ("hauslast", "house_load", "house load", "verbraucher", "home_power"),
        "domains": _SENSOR_DOMAINS,
        "device_classes": ("power",),
        "units": ("w", "kw", "watt", "kilowatt", "kilowatts"),
        "exclude_hints": _ENERGY_EXCLUDE,
    },
    "sens_pv_energy": {
        "hints": ("pv_energy", "pv energy", "solar energy", "solar_energy", "ertrag"),
        "domains": _SENSOR_DOMAINS,
        "device_classes": ("energy",),
        "state_classes": ("total_increasing",),
        "units": ("kwh", "wh", "kilowatt-hour", "kilowatt-hours", "watt-hour", "watt-hours"),
        "exclude_hints": ("grid", "import", "export", "battery", "loadpoint"),
    },
    "sens_grid_energy_import": {
        "hints": (
            "grid_import",
            "import_energy",
            "grid import",
            "netzbezug",
            "bezug_energy",
            "energy_from_grid",
        ),
        "domains": _SENSOR_DOMAINS,
        "device_classes": ("energy",),
        "state_classes": ("total_increasing",),
        "units": ("kwh", "wh", "kilowatt-hour", "kilowatt-hours", "watt-hour", "watt-hours"),
        "exclude_hints": ("export", "einspeis", "pv", "solar", "battery"),
    },
    "sens_grid_energy_export": {
        "hints": (
            "grid_export",
            "export_energy",
            "grid export",
            "einspeis",
            "feed_in",
            "energy_to_grid",
        ),
        "domains": _SENSOR_DOMAINS,
        "device_classes": ("energy",),
        "state_classes": ("total_increasing",),
        "units": ("kwh", "wh", "kilowatt-hour", "kilowatt-hours", "watt-hour", "watt-hours"),
        "exclude_hints": ("import", "bezug", "pv", "solar", "battery"),
    },
    "set_ess_active_power": {
        "hints": ("active_power", "sollleistung", "ess setpoint", "ziel leistung"),
        "domains": _WRITE_DOMAINS,
        "units": ("w", "kw", "watt", "kilowatt", "kilowatts"),
        "exclude_hints": ("charge_limit", "discharge_limit", "max_current", "mode"),
    },
    "set_ess_charge_power_limit": {
        "hints": ("charge_limit", "ladegrenze", "charge limit", "max lade"),
        "domains": _WRITE_DOMAINS,
        "units": ("w", "kw", "watt", "kilowatt", "kilowatts"),
    },
    "set_ess_discharge_power_limit": {
        "hints": ("discharge_limit", "entladegrenze", "discharge limit", "max entlade"),
        "domains": _WRITE_DOMAINS,
        "units": ("w", "kw", "watt", "kilowatt", "kilowatts"),
    },
    "set_ess_mode": {
        "hints": ("ess_mode", "mode_hint", "steuerbefehl", "ess mode", "control_cmd"),
        "domains": _WRITE_DOMAINS,
    },
    "set_evcs_max_current": {
        "hints": (
            "max_current",
            "maxstrom",
            "max current",
            "ladestrom",
            "sollstrom",
            "set current",
        ),
        "domains": _WRITE_DOMAINS,
        "units": ("a", "amp", "ampere"),
    },
    "set_evcs_mode": {
        "hints": ("evcs_mode", "ev mode", "pv_follow", "charge_immediate", "sofort"),
        "domains": _WRITE_DOMAINS,
    },
}

_MIN_SCORE = 0.35


def compatible_entity_ids(field: str, rows: list[dict[str, Any]]) -> list[str]:
    """Scan rows that may be bound to ``field`` (drops other physical quantities)."""
    out: list[str] = []
    for row in rows:
        entity_id = str(row.get("entity_id") or "").strip()
        if not entity_id:
            continue
        check = unit_check(field, row.get("unit"), device_class=row.get("device_class"))
        if check != "mismatch":
            out.append(entity_id)
    return out


def binding_unit_issues(
    ehal_map: dict[str, str], rows: list[dict[str, Any]]
) -> list[str]:
    """Human-readable problems for bindings whose unit contradicts the field."""
    by_id = {str(r.get("entity_id") or ""): r for r in rows}
    issues: list[str] = []
    for field, entity_id in ehal_map.items():
        row = by_id.get(str(entity_id))
        if row is None:
            continue
        check = unit_check(field, row.get("unit"), device_class=row.get("device_class"))
        if check == "mismatch":
            unit = row.get("unit") or row.get("device_class") or "?"
            issues.append(
                f"{field} braucht {field_quantity(field)}, `{entity_id}` liefert {unit}"
            )
    return issues


def binding_conversion_hint(field: str, entity_id: str, rows: list[dict[str, Any]]) -> str:
    """Automatic conversion shown next to a binding, e.g. ``kW → W (×1000)``."""
    for row in rows:
        if str(row.get("entity_id") or "") == entity_id:
            return describe_conversion(field, row.get("unit"))
    return ""


def resolve_field_select_default(existing: str, proposed: str) -> str:
    """Prefer saved binding; use heuristic proposal only when unbound."""
    return str(existing or proposed or "")


def heuristic_propose(
    entities: list[dict[str, Any]],
    *,
    fields: tuple[str, ...] = EHAL_HA_FIELDS,
) -> dict[str, dict[str, Any]]:
    """Score HA scan rows for EHAL fields; confidence 0.35–0.75. No LLM."""
    rows = [_normalize_row(row) for row in entities if isinstance(row, dict)]
    rows = [row for row in rows if row["entity_id"]]
    proposals: dict[str, dict[str, Any]] = {}
    for field in fields:
        rules = _FIELD_RULES.get(field)
        if not rules:
            continue
        best_id = ""
        best_score = 0.0
        for row in rows:
            score = _score_row(row, rules, field)
            if score > best_score:
                best_score = score
                best_id = row["entity_id"]
        if best_id and best_score >= _MIN_SCORE:
            proposals[field] = {
                "entity_id": best_id,
                "confidence": round(min(0.75, best_score), 2),
                "source": "heuristic",
            }
    return proposals


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    entity_id = str(row.get("entity_id") or "").strip()
    domain = str(row.get("domain") or "").strip().lower()
    if not domain and "." in entity_id:
        domain = entity_id.split(".", 1)[0].lower()
    unit = str(row.get("unit") or "").strip().lower()
    device_class = str(row.get("device_class") or "").strip().lower()
    state_class = str(row.get("state_class") or "").strip().lower()
    friendly = str(row.get("friendly_name") or entity_id).strip()
    name_blob = f"{entity_id} {friendly}".lower().replace(".", " ").replace("_", " ")
    # Also keep underscored form for token hints like charge_limit
    name_raw = f"{entity_id} {friendly}".lower()
    return {
        "entity_id": entity_id,
        "domain": domain,
        "unit": unit,
        "device_class": device_class,
        "state_class": state_class,
        "name_blob": name_blob,
        "name_raw": name_raw,
    }


def _score_row(row: dict[str, Any], rules: dict[str, Any], field: str = "") -> float:
    allowed = rules.get("domains") or frozenset()
    if row["domain"] not in allowed:
        return 0.0
    if not _physically_compatible(row, field):
        return 0.0
    exclude = rules.get("exclude_hints") or ()
    for bad in exclude:
        if bad in row["name_raw"] or bad in row["name_blob"]:
            return 0.0
    score = _hint_score(row["name_raw"], row["name_blob"], rules.get("hints") or ())
    device_classes = rules.get("device_classes") or ()
    if device_classes and row["device_class"] in device_classes:
        score = max(score, 0.45) + 0.15
    state_classes = rules.get("state_classes") or ()
    if state_classes and row["state_class"] in state_classes:
        score += 0.10
    units = rules.get("units") or ()
    if units and row["unit"] in units:
        score += 0.10
    # Name match is required for a proposal — attrs alone are too ambiguous
    # (many power sensors share device_class=power).
    if score < _MIN_SCORE:
        return 0.0
    # Ensure at least one name hint contributed (attrs-only would be < 0.35 after
    # the check above only if we had no hint; boost path can exceed threshold).
    if _hint_score(row["name_raw"], row["name_blob"], rules.get("hints") or ()) <= 0:
        return 0.0
    return min(0.75, score)


def _physically_compatible(row: dict[str, Any], field: str) -> bool:
    """Rule 1: only bind entities whose unit / device_class match the field's quantity.

    Sensors must carry a matching unit; write helpers (number / input_number)
    without a unit are allowed (assumed to be in the EHAL base unit).
    """
    check = unit_check(field, row["unit"], device_class=row["device_class"])
    if check == "mismatch":
        return False
    if check == "unknown" and row["domain"] in _SENSOR_DOMAINS:
        return False
    return True


def _hint_score(name_raw: str, name_blob: str, hints: tuple[str, ...]) -> float:
    score = 0.0
    for hint in hints:
        low = hint.lower()
        if low in name_raw or low in name_blob:
            score = max(score, 0.55 + 0.05 * min(len(low), 4))
    return score

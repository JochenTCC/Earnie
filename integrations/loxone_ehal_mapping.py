"""EHAL field ↔ loxone_blocks mapping helpers + optional Ollama propose (2.4.f)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from ehal.models import TELEMETRY_FIELD_ALIASES

logger = logging.getLogger(__name__)

TELEMETRY_REQUIRED = (
    "sens_grid_power_active",
    "sens_pv_production_active",
    "sens_ess_soc",
)
TELEMETRY_OPTIONAL = (
    "sens_ess_power",
    "sens_evcs_active_power",
    "sens_power_consumers",
)
SETPOINT_FIELDS = (
    "set_ess_active_power",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_mode",
    "set_evcs_max_current",
    "set_evcs_mode",
)
EHAL_MAP_FIELDS = TELEMETRY_REQUIRED + TELEMETRY_OPTIONAL + SETPOINT_FIELDS
EXTRAS_FIELDS: tuple[str, ...] = ()

# Canonical §C → loxone_blocks role keys (+ legacy unprefixed dual-read aliases).
EHAL_TO_BLOCKS: dict[str, str] = {
    "sens_ess_soc": "soc_name",
    "sens_pv_production_active": "pv_power_name",
    "sens_ess_power": "battery_power_name",
    "sens_grid_power_active": "grid_power_name",
    "sens_power_consumers": "consumers_power_name",
    "set_ess_active_power": "target_active_power_name",
    "set_ess_charge_power_limit": "target_charge_power_name",
    "set_ess_discharge_power_limit": "target_discharge_power_name",
    "set_ess_mode": "control_cmd_name",
    # Legacy M1 unprefixed keys (dual-read during 2.4.j).
    "ess_soc": "soc_name",
    "pv_production_active": "pv_power_name",
    "ess_power": "battery_power_name",
    "grid_power_active": "grid_power_name",
}

# Prefer ehal.profiles (2.4.g); keep local fallback if import fails in odd envs.
try:
    from ehal.profiles import role_field_labels as _role_field_labels

    FIELD_LABELS: dict[str, str] = _role_field_labels()
except ImportError:  # pragma: no cover
    FIELD_LABELS = {
        "sens_grid_power_active": "Netzleistung (W, +Bezug)",
        "sens_pv_production_active": "PV-Produktion (W)",
        "sens_ess_soc": "Batterie-SoC (%)",
        "sens_ess_power": "Batterieleistung (W, +Entladung)",
        "sens_evcs_active_power": "Wallbox-Leistung (W)",
        "sens_power_consumers": "Hauslast (W)",
        "set_ess_active_power": "Setpoint ESS-Sollleistung (W, +Entladung)",
        "set_ess_charge_power_limit": "Setpoint Ladegrenze (W)",
        "set_ess_discharge_power_limit": "Setpoint Entladegrenze (W)",
        "set_ess_mode": "Setpoint ESS-Modus / Steuerbefehl (Hinweis)",
        "set_evcs_max_current": "Setpoint Wallbox-Maxstrom (A)",
        "set_evcs_mode": "Setpoint Wallbox-Modus (pv|now)",
    }

_HINTS: dict[str, tuple[str, ...]] = {
    "sens_grid_power_active": ("netz", "grid", "bezug", "energieversorger"),
    "sens_pv_production_active": ("pv", "produktion", "solar", "erzeug"),
    "sens_ess_soc": ("soc", "ladezustand", "batterie soc", "akku soc"),
    "sens_ess_power": ("batterie", "speicher", "akku", "ess"),
    "sens_evcs_active_power": ("wallbox", "evcs", "e-auto", "eauto", "ladung leistung"),
    "sens_power_consumers": ("hauslast", "verbraucher", "house load", "verbrauch"),
    "set_ess_active_power": (
        "sollleistung",
        "active power",
        "ziel leistung batterie",
        "ess setpoint",
    ),
    "set_ess_charge_power_limit": ("ladegrenze", "charge limit", "max lade"),
    "set_ess_discharge_power_limit": ("entladegrenze", "discharge limit", "max entlade"),
    "set_ess_mode": ("steuerbefehl", "control_cmd", "huawei", "modbus cmd", "ess mode"),
    "set_evcs_max_current": (
        "maxstrom",
        "max current",
        "ladestrom",
        "sollstrom",
        "set current",
    ),
    "set_evcs_mode": ("pv_follow", "sofort", "charge_immediate", "ev mode"),
    "get_evcs_limit_soc": ("limit soc", "ladeziel", "target soc ev", "limit_soc"),
    "sens_evcs_connected": ("angeschlossen", "plugged", "connected", "ev da"),
    "sens_evcs_soc_act": ("ev soc", "fahrzeug soc", "ist-soc", "vehicle soc"),
    "sens_evcs_bat_capacity": ("kapazität", "capacity", "akkukapazität"),
    "get_evcs_nominal_current": ("nennstrom", "nominal", "maxstrom ev"),
    "get_evcs_ready_by_time": (
        "tna",
        "wecker",
        "ladewecker",
        "alarm",
        "fertig",
        "ready",
        "deadline",
    ),
    "flex.power_name": ("leistung", "power", "verbrauch"),
    "flex.enable_name": ("freigabe", "enable", "sg ready"),
    "flex.power_setpoint_name": ("sollwert", "setpoint", "ziel leistung"),
    "flex.sens_power_act": ("leistung", "power", "verbrauch"),
    "flex.set_enable": ("freigabe", "enable", "sg ready"),
    "flex.set_power_setpoint": ("sollwert", "setpoint", "ziel leistung"),
}


def ehal_mapping_to_loxone_blocks(
    ehal_map: dict[str, str],
    *,
    extras: dict[str, str] | None = None,
) -> dict[str, str]:
    """Translate EHAL field → marker map into loxone_blocks role keys."""
    blocks: dict[str, str] = {}
    for field, marker in ehal_map.items():
        canonical = TELEMETRY_FIELD_ALIASES.get(field, field)
        role = EHAL_TO_BLOCKS.get(canonical) or EHAL_TO_BLOCKS.get(field)
        name = str(marker or "").strip()
        if role and name:
            blocks[role] = name
    for role, marker in (extras or {}).items():
        name = str(marker or "").strip()
        if role == "control_cmd_name" and name:
            blocks["control_cmd_name"] = name
    return blocks


def merge_loxone_blocks(
    existing: dict[str, Any] | None,
    updates: dict[str, str],
) -> dict[str, Any]:
    """Merge mapping updates into existing loxone_blocks (preserve unrelated keys)."""
    out = dict(existing or {}) if isinstance(existing, dict) else {}
    for key, value in updates.items():
        if str(value).strip():
            out[key] = str(value).strip()
    return out


def heuristic_propose(
    names: list[str],
    *,
    fields: tuple[str, ...] = EHAL_MAP_FIELDS + EXTRAS_FIELDS,
) -> dict[str, dict[str, Any]]:
    """Name-hint matching without LLM; confidence 0.35–0.75."""
    proposals: dict[str, dict[str, Any]] = {}
    lowered = [(n, n.lower()) for n in names if str(n).strip()]
    for field in fields:
        hints = _HINTS.get(field, ())
        best_name = ""
        best_score = 0.0
        for name, low in lowered:
            score = _hint_score(low, hints)
            if score > best_score:
                best_score = score
                best_name = name
        if best_name and best_score >= 0.35:
            proposals[field] = {
                "marker_name": best_name,
                "confidence": round(min(0.75, best_score), 2),
                "source": "heuristic",
            }
    return proposals


def _hint_score(low_name: str, hints: tuple[str, ...]) -> float:
    score = 0.0
    for hint in hints:
        if hint in low_name:
            score = max(score, 0.55 + 0.05 * min(len(hint), 4))
    return score


def ollama_reachable(
    base_url: str = "http://127.0.0.1:11434",
    *,
    timeout_sec: float = 2.0,
) -> bool:
    url = str(base_url or "").rstrip("/") + "/api/tags"
    try:
        response = requests.get(url, timeout=timeout_sec)
        return response.status_code == 200
    except requests.RequestException:
        return False


def propose_with_ollama(
    names: list[str],
    *,
    base_url: str = "http://127.0.0.1:11434",
    model: str = "llama3.2",
    timeout_sec: float = 60.0,
    fields: tuple[str, ...] = EHAL_MAP_FIELDS + EXTRAS_FIELDS,
) -> dict[str, dict[str, Any]]:
    """Ask Ollama for JSON proposals; empty dict on failure."""
    if not names:
        return {}
    prompt = _build_propose_prompt(names, fields)
    url = str(base_url or "").rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You map Loxone Miniserver control names to Earnie EHAL fields. "
                    "Reply with JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    try:
        response = requests.post(url, json=body, timeout=timeout_sec)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, OSError, ValueError) as exc:
        logger.info("Ollama propose failed: %s", exc)
        return {}
    content = ""
    if isinstance(payload, dict):
        msg = payload.get("message")
        if isinstance(msg, dict):
            content = str(msg.get("content") or "")
        if not content:
            content = str(payload.get("response") or "")
    return parse_ollama_proposals(content, allowed_names=set(names), fields=fields)


def _build_propose_prompt(names: list[str], fields: tuple[str, ...]) -> str:
    sample = names[:200]
    return (
        "Given Loxone control names and EHAL target fields, propose the best "
        "marker_name for each field (or omit if unsure).\n"
        f"Fields: {list(fields)}\n"
        f"Names: {sample}\n"
        'Return JSON: {"mappings":[{"field":"...","marker_name":"...","confidence":0.0}]}\n'
        "confidence is 0..1."
    )


def parse_ollama_proposals(
    content: str,
    *,
    allowed_names: set[str],
    fields: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Parse LLM JSON into field → {marker_name, confidence, source}."""
    data = _extract_json_object(content)
    if not data:
        return {}
    rows = data.get("mappings")
    if not isinstance(rows, list):
        rows = data.get("proposals") if isinstance(data.get("proposals"), list) else []
    allowed_fields = set(fields)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = str(row.get("field") or "").strip()
        marker = str(row.get("marker_name") or row.get("name") or "").strip()
        if field not in allowed_fields or marker not in allowed_names:
            continue
        try:
            confidence = float(row.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        out[field] = {
            "marker_name": marker,
            "confidence": round(confidence, 2),
            "source": "ollama",
        }
    return out


def _extract_json_object(content: str) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

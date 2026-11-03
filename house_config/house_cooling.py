"""Cooling of the house: the air conditioning as inverse heat source of ``thermal_annual``.

Stored shape (the device on the house's heating consumer, the switch on the profile)::

    {"id": "haus", ..., "cooling_enabled": true,
     "consumers": [{"type": "thermal_annual", ...,
                    "cooling": {"type": "split", "seer": 5.0,
                                "cooling_power_kw": 3.5, "setpoint_c": 26.0}}]}

``cooling_enabled`` is the switch „Kühlung betrachten“, independent of „Heizung betrachten“: a
house may model cooling without heating. ``type`` ``split`` is a device of its own (split or
mono-block air conditioner), ``heat_pump`` the reversible heat pump of the heating system.
``seer`` is the seasonal cooling efficiency (cold / electricity); ``cooling_power_kw`` the
cooling capacity (thermal); ``setpoint_c`` the indoor temperature the device holds.

Missing ``seer`` / ``cooling_power_kw`` / ``setpoint_c`` take the schema defaults
(``x-earnie-type-defaults`` for ``seer``). The block is kept when the switch is off.
"""
from __future__ import annotations

import copy
from typing import Any

COOLING_ENABLED_KEY = "cooling_enabled"
COOLING_KEY = "cooling"
COOLING_TYPE_SPLIT = "split"
COOLING_TYPE_HEAT_PUMP = "heat_pump"
COOLING_TYPES: tuple[str, ...] = (COOLING_TYPE_SPLIT, COOLING_TYPE_HEAT_PUMP)
COOLING_FIELDS: tuple[str, ...] = ("type", "seer", "cooling_power_kw", "setpoint_c")
# Planned consumer id of the cooling load (never in the file; Kennung of the cooling series).
COOLING_ID_SUFFIX = "_cooling"


def cooling_seer_default(cooling_type: str) -> float:
    """Seasonal cooling efficiency of a device type (schema ``x-earnie-type-defaults``)."""
    from house_config.profile_schema_defaults import schema_default

    return float(schema_default("cooling", "seer", consumer_type=cooling_type))


def _field_default(key: str) -> float:
    from house_config.profile_schema_defaults import schema_default

    return float(schema_default("cooling", key))


def _positive(raw: dict, key: str, default: float, *, label: str) -> float:
    value = raw.get(key)
    number = default if value in (None, "") else float(value)
    if number <= 0.0:
        raise ValueError(f"{label}: cooling.{key} muss > 0 sein (ist {number}).")
    return number


def normalize_cooling(raw: Any, *, label: str, heat_source: dict | None) -> dict[str, Any]:
    """Validated ``cooling`` block of a thermal_annual consumer.

    ``heat_pump`` needs a heat pump as heat source (the reversible device of the heating
    system); any other heat source fails loud.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{label}: cooling muss ein Objekt sein.")
    extra = sorted(set(raw) - set(COOLING_FIELDS))
    if extra:
        raise ValueError(f"{label}: cooling enthält unbekannte Felder {', '.join(extra)}.")
    cooling_type = str(raw.get("type") or "").strip().lower()
    if cooling_type not in COOLING_TYPES:
        raise ValueError(
            f"{label}: cooling.type '{raw.get('type')}' unbekannt "
            f"(erlaubt: {', '.join(COOLING_TYPES)})."
        )
    if cooling_type == COOLING_TYPE_HEAT_PUMP:
        source_type = str((heat_source or {}).get("type") or "")
        if source_type != "heat_pump":
            raise ValueError(
                f"{label}: cooling.type heat_pump kühlt mit der Wärmepumpe des Heizsystems, "
                f"die Wärmequelle ist aber '{source_type or '—'}'. Klimaanlage als eigenes "
                "Gerät (split) eintragen."
            )
    setpoint = raw.get("setpoint_c")
    return {
        "type": cooling_type,
        "seer": _positive(raw, "seer", cooling_seer_default(cooling_type), label=label),
        "cooling_power_kw": _positive(
            raw, "cooling_power_kw", _field_default("cooling_power_kw"), label=label
        ),
        "setpoint_c": float(_field_default("setpoint_c") if setpoint in (None, "") else setpoint),
    }


def default_cooling() -> dict[str, Any]:
    """A new device (form seed): split air conditioner with the schema defaults."""
    return normalize_cooling({"type": COOLING_TYPE_SPLIT}, label="Kühlung", heat_source=None)


def serialize_cooling(block: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(block[key]) for key in COOLING_FIELDS if key in block}


def normalize_cooling_enabled(raw_profile: dict, *, label: str) -> bool:
    """The switch „Kühlung betrachten“ (missing = off)."""
    value = raw_profile.get(COOLING_ENABLED_KEY)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError(f"{label}: {COOLING_ENABLED_KEY} muss true oder false sein.")
    return value


def cooling_id(consumer: dict) -> str:
    return f"{consumer['id']}{COOLING_ID_SUFFIX}"


def cooling_consumer(profile: dict) -> dict | None:
    """The heating consumer that carries the active cooling of a normalized profile.

    It may sit in ``consumers`` or (heating switch off) in ``inactive_consumers``; ``None``
    when „Kühlung betrachten“ is off.
    """
    from house_config.house_thermal import INACTIVE_CONSUMERS_KEY

    if not profile.get(COOLING_ENABLED_KEY):
        return None
    for consumer in [*profile.get("consumers", []), *(profile.get(INACTIVE_CONSUMERS_KEY) or [])]:
        if consumer.get("type") == "thermal_annual" and consumer.get(COOLING_KEY):
            return consumer
    raise ValueError(
        f"Hausprofil '{profile.get('id')}': „Kühlung betrachten“ ist an, aber der "
        "Haus-Wärme-Verbraucher hat keine Klimaanlage (cooling)."
    )

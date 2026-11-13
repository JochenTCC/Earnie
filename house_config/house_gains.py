"""SUSI P2 — solar and internal gains of the house: data model (normalize, defaults, suggestion).

Fields (raw ``house_profiles.json``):

- profile ``baseload_internal_gain_factor`` (share of the Grundlast that ends up as heat in the
  heated volume),
- consumer ``internal_gain_factor`` (per electrical unit, D1; type defaults in the schema),
  heating-rod part ``internal_gain_factor`` (always 0, its heat goes into the store),
- house block ``thermal.gross_floor_area_m2`` (BGF, HWB area basis) and ``thermal.solar_gains``.

A missing field means the documented schema default; the migration ``dm5.house_gains`` writes
them explicitly. The physics (hourly gain series) lives in ``optimizer.house_gains``.
"""
from __future__ import annotations

from typing import Any

from house_config.profile_schema_defaults import (
    consumer_default,
    profile_default,
    schema_default,
)

BASELOAD_GAIN_FACTOR_KEY = "baseload_internal_gain_factor"
INTERNAL_GAIN_FACTOR_KEY = "internal_gain_factor"
GROSS_FLOOR_AREA_KEY = "gross_floor_area_m2"
SOLAR_GAINS_KEY = "solar_gains"
# Normalized thermal_annual ``thermal`` only: what the year model needs for internal gains.
INTERNAL_GAINS_KEY = "internal_gains"

# SUSI: BGF / WNF (Bruttogrundfläche / Wohnnutzfläche).
GROSS_TO_LIVING_AREA_FACTOR = 1.25
WINDOW_DIRECTIONS: tuple[str, ...] = ("s", "e", "w", "n")
# Consumer types whose electric energy must not count as internal gain (the heat is the model).
ZERO_GAIN_CONSUMER_TYPES: frozenset[str] = frozenset({"thermal_annual"})

# SUSI cuboid for the window suggestion (design § P2): side ratio, storey height, storeys,
# window share of the façade per direction.
SUGGEST_SIDE_RATIO = 1.5
SUGGEST_STOREY_HEIGHT_M = 2.6
SUGGEST_STOREYS = 2
SUGGEST_WINDOW_SHARE = {"s": 0.20, "e": 0.10, "w": 0.10, "n": 0.06}


def _fraction(raw: Any, *, where: str, maximum: float = 1.0) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"{where} muss eine Zahl sein (ist {raw!r}).")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where} muss eine Zahl sein (ist {raw!r}).") from exc
    if value < 0.0 or value > maximum:
        raise ValueError(f"{where} muss zwischen 0 und {maximum:g} liegen (ist {value:g}).")
    return value


def normalize_baseload_gain_factor(raw: Any, *, label: str) -> float:
    if raw is None or raw == "":
        return float(profile_default(BASELOAD_GAIN_FACTOR_KEY))
    return _fraction(raw, where=f"{label}: {BASELOAD_GAIN_FACTOR_KEY}")


# The pool filter pump is a generic consumer but stands outside like the pool heating.
OUTDOOR_CONSUMER_IDS: frozenset[str] = frozenset({"pool_filter"})


def default_consumer_gain_factor(consumer_type: str, consumer_id: str | None = None) -> float:
    """Schema type default; the pool filter (generic, outdoors) gets 0."""
    if consumer_id is not None and str(consumer_id).strip() in OUTDOOR_CONSUMER_IDS:
        return 0.0
    return float(consumer_default(INTERNAL_GAIN_FACTOR_KEY, consumer_type=consumer_type))


def normalize_consumer_gain_factor(
    raw: Any, *, consumer_type: str, label: str, consumer_id: str | None = None
) -> float:
    """``internal_gain_factor`` of a consumer (missing = type default from the schema)."""
    where = f"{label}: {INTERNAL_GAIN_FACTOR_KEY}"
    if raw is None or raw == "":
        return default_consumer_gain_factor(consumer_type, consumer_id)
    value = _fraction(raw, where=where)
    if consumer_type in ZERO_GAIN_CONSUMER_TYPES and value:
        raise ValueError(
            f"{where} muss beim Heizungs-Verbraucher 0 sein (ist {value:g}): seine Wärme ist "
            "das Hausmodell selbst und würde sonst doppelt zählen."
        )
    return value


def normalize_part_gain_factor(raw: Any, *, label: str) -> float:
    """``internal_gain_factor`` of a heating-rod part: always 0 (heat goes into the store)."""
    if raw is None or raw == "":
        return float(schema_default("consumer_part", INTERNAL_GAIN_FACTOR_KEY))
    value = _fraction(raw, where=f"{label}: {INTERNAL_GAIN_FACTOR_KEY}")
    if value:
        raise ValueError(
            f"{label}: {INTERNAL_GAIN_FACTOR_KEY} muss beim Heizstab 0 sein (ist {value:g}): "
            "seine Wärme geht in den Wärmespeicher und ist dort modelliert."
        )
    return value


def _solar_default(key: str):
    return schema_default("solar_gains", key)


def _window_default(direction: str) -> float:
    from house_config.profile_schema_defaults import _definitions

    props = _definitions()["solar_gains"]["properties"]["window_area_m2"]["properties"]
    return float(props[direction]["default"])


def normalize_solar_gains(raw: Any, *, label: str) -> dict[str, Any]:
    """Validated ``thermal.solar_gains`` (missing block = schema default, i.e. off)."""
    where = f"{label}: thermal.{SOLAR_GAINS_KEY}"
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"{where} muss ein Objekt sein.")
    extra = sorted(set(raw) - {"enabled", "window_area_m2", "g_value", "frame_shading_factor"})
    if extra:
        raise ValueError(f"{where} enthält unbekannte Felder {', '.join(extra)}.")
    enabled = raw.get("enabled", _solar_default("enabled"))
    if not isinstance(enabled, bool):
        raise ValueError(f"{where}.enabled muss true oder false sein.")
    windows_raw = raw.get("window_area_m2") or {}
    if not isinstance(windows_raw, dict):
        raise ValueError(f"{where}.window_area_m2 muss ein Objekt sein.")
    unknown = sorted(set(windows_raw) - set(WINDOW_DIRECTIONS))
    if unknown:
        raise ValueError(
            f"{where}.window_area_m2: unbekannte Richtung {', '.join(unknown)} "
            "(erlaubt: s, e, w, n)."
        )
    windows: dict[str, float] = {}
    for direction in WINDOW_DIRECTIONS:
        value = windows_raw.get(direction)
        area = _window_default(direction) if value in (None, "") else float(value)
        if area < 0.0:
            raise ValueError(f"{where}.window_area_m2.{direction} muss >= 0 sein (ist {area:g}).")
        windows[direction] = area
    g_raw = raw.get("g_value")
    frame_raw = raw.get("frame_shading_factor")
    g_value = _fraction(
        _solar_default("g_value") if g_raw in (None, "") else g_raw, where=f"{where}.g_value"
    )
    frame = _fraction(
        _solar_default("frame_shading_factor") if frame_raw in (None, "") else frame_raw,
        where=f"{where}.frame_shading_factor",
    )
    if g_value <= 0.0 or frame <= 0.0:
        raise ValueError(f"{where}: g_value und frame_shading_factor müssen > 0 sein.")
    return {
        "enabled": enabled,
        "window_area_m2": windows,
        "g_value": g_value,
        "frame_shading_factor": frame,
    }


def normalize_gross_floor_area(raw: Any, *, label: str) -> float | None:
    if raw in (None, ""):
        return None
    value = float(raw)
    if value <= 0.0:
        raise ValueError(f"{label}: thermal.{GROSS_FLOOR_AREA_KEY} muss > 0 sein (ist {value:g}).")
    return value


def hwb_reference_area_m2(thermal: dict[str, Any]) -> float:
    """Bezugsfläche des HWB: explizite BGF, sonst Wohnfläche × 1,25 (SUSI)."""
    explicit = thermal.get(GROSS_FLOOR_AREA_KEY)
    if explicit not in (None, "") and float(explicit) > 0.0:
        return float(explicit)
    return float(thermal.get("living_area_m2", 0.0) or 0.0) * GROSS_TO_LIVING_AREA_FACTOR


def suggested_window_areas_m2(
    living_area_m2: float,
    *,
    gross_floor_area_m2: float | None = None,
    storeys: int = SUGGEST_STOREYS,
) -> dict[str, float]:
    """Window areas per direction after the SUSI cuboid (rounded to 0.5 m²).

    BGF = WNF × 1.25 (or explicit), footprint = BGF / storeys with side ratio 1.5 (long side
    facing south/north), façade height = storeys × 2.6 m, window share S 20 %, E/W 10 %, N 6 %.
    """
    import math

    if storeys < 1:
        raise ValueError(f"storeys muss >= 1 sein (ist {storeys}).")
    gross = (
        float(gross_floor_area_m2)
        if gross_floor_area_m2
        else float(living_area_m2) * GROSS_TO_LIVING_AREA_FACTOR
    )
    if gross <= 0.0:
        return {direction: 0.0 for direction in WINDOW_DIRECTIONS}
    footprint = gross / storeys
    short_side = math.sqrt(footprint / SUGGEST_SIDE_RATIO)
    long_side = short_side * SUGGEST_SIDE_RATIO
    height = storeys * SUGGEST_STOREY_HEIGHT_M
    facade = {"s": long_side, "n": long_side, "e": short_side, "w": short_side}
    return {
        direction: round(facade[direction] * height * SUGGEST_WINDOW_SHARE[direction] * 2) / 2
        for direction in WINDOW_DIRECTIONS
    }


def default_solar_gains_for_new_house(living_area_m2: float) -> dict[str, Any]:
    """Seed of a new house: enabled, SUSI-cuboid window areas, schema g-value / shading."""
    block = normalize_solar_gains({}, label="Hausprofil")
    block["enabled"] = True
    block["window_area_m2"] = suggested_window_areas_m2(living_area_m2)
    return block


def solar_gains_active(thermal: dict[str, Any]) -> bool:
    block = thermal.get(SOLAR_GAINS_KEY) or {}
    if not block.get("enabled"):
        return False
    return any(float(v) > 0.0 for v in (block.get("window_area_m2") or {}).values())


def internal_gain_descriptor(
    *,
    annual_kwh: float,
    baseload_factor: float,
    consumers: list[dict[str, Any]],
) -> dict[str, Any]:
    """What the year model needs for internal gains (placed into the heating consumer's thermal).

    ``consumers`` are the other planned consumers of the house (not the heating consumer): their
    annual kWh feed the Grundlast, their hourly series × factor the gains.
    """
    stripped = []
    for consumer in consumers:
        if consumer.get("type") in ZERO_GAIN_CONSUMER_TYPES:
            continue
        stripped.append(
            {
                k: v
                for k, v in consumer.items()
                if k not in ("ehal_bindings", "loxone_inputs", "loxone_outputs", "thermal_control")
            }
        )
    return {
        "annual_kwh": float(annual_kwh),
        "baseload_factor": float(baseload_factor),
        "consumers": stripped,
    }


__all__ = [
    "BASELOAD_GAIN_FACTOR_KEY",
    "GROSS_FLOOR_AREA_KEY",
    "GROSS_TO_LIVING_AREA_FACTOR",
    "INTERNAL_GAINS_KEY",
    "INTERNAL_GAIN_FACTOR_KEY",
    "SOLAR_GAINS_KEY",
    "WINDOW_DIRECTIONS",
    "default_consumer_gain_factor",
    "default_solar_gains_for_new_house",
    "hwb_reference_area_m2",
    "internal_gain_descriptor",
    "normalize_baseload_gain_factor",
    "normalize_consumer_gain_factor",
    "normalize_gross_floor_area",
    "normalize_part_gain_factor",
    "normalize_solar_gains",
    "solar_gains_active",
    "suggested_window_areas_m2",
]


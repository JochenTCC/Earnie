"""Lineares Amortisationsmodell für Batterieverschleiß in der MILP-Zielfunktion."""
from __future__ import annotations

BATTERY_WEAR_COST_KEYS = (
    "replacement_cost_euro",
    "expected_cycles",
    "cycle_cost_fraction",
)


def validate_battery_wear_config(raw: dict | None) -> dict:
    """Validiert battery_wear aus config.json; wirft bei fehlenden/ungültigen Werten."""
    if not isinstance(raw, dict):
        raise ValueError(
            "Kritischer Konfigurationsfehler: Block 'battery_wear' fehlt oder ist ungültig."
        )
    if "enabled" not in raw:
        raise ValueError(
            "Kritischer Konfigurationsfehler: battery_wear.enabled fehlt in config.json."
        )
    enabled = bool(raw["enabled"])
    if not enabled:
        return {"enabled": False}

    missing = [key for key in BATTERY_WEAR_COST_KEYS if key not in raw]
    if missing:
        raise ValueError(
            "Kritischer Konfigurationsfehler: battery_wear."
            + ", battery_wear.".join(missing)
            + " fehlt in config.json (erforderlich wenn enabled=true)."
        )

    replacement_cost_euro = float(raw["replacement_cost_euro"])
    expected_cycles = float(raw["expected_cycles"])
    cycle_cost_fraction = float(raw["cycle_cost_fraction"])
    if replacement_cost_euro <= 0.0:
        raise ValueError(
            "Kritischer Konfigurationsfehler: battery_wear.replacement_cost_euro "
            "muss > 0 sein."
        )
    if expected_cycles <= 0.0:
        raise ValueError(
            "Kritischer Konfigurationsfehler: battery_wear.expected_cycles "
            "muss > 0 sein."
        )
    if cycle_cost_fraction <= 0.0 or cycle_cost_fraction > 1.0:
        raise ValueError(
            "Kritischer Konfigurationsfehler: battery_wear.cycle_cost_fraction "
            "muss zwischen 0 (exklusiv) und 1 (inklusiv) liegen."
        )
    return {
        "enabled": True,
        "replacement_cost_euro": replacement_cost_euro,
        "expected_cycles": expected_cycles,
        "cycle_cost_fraction": cycle_cost_fraction,
    }


def throughput_wear_cent_per_kwh(
    *,
    replacement_cost_euro: float,
    expected_cycles: float,
    cycle_cost_fraction: float,
    capacity_kwh: float,
) -> float:
    """Verschleiß in ct/kWh Durchsatz (Laden + Entladen, je kWh am Speicher)."""
    if capacity_kwh <= 0.0:
        raise ValueError(
            "battery_capacity_kwh muss > 0 sein, um Verschleißkosten zu berechnen."
        )
    euro_per_kwh = (
        cycle_cost_fraction * replacement_cost_euro / expected_cycles / capacity_kwh
    )
    return euro_per_kwh * 100.0


def battery_wear_cent_per_kwh_from_config(
    wear_config: dict,
    capacity_kwh: float,
) -> float:
    if not wear_config.get("enabled"):
        return 0.0
    return throughput_wear_cent_per_kwh(
        replacement_cost_euro=wear_config["replacement_cost_euro"],
        expected_cycles=wear_config["expected_cycles"],
        cycle_cost_fraction=wear_config["cycle_cost_fraction"],
        capacity_kwh=capacity_kwh,
    )

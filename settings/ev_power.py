"""Shared EV nominal-power helpers (A→kW conversion for live and planning)."""
from __future__ import annotations

DEFAULT_EV_NOMINAL_VOLTAGE_V = 230.0
DEFAULT_EV_NOMINAL_PHASES = 1


def ampere_to_kw(amps: float, *, voltage_v: float, phases: int) -> float:
    return amps * voltage_v * max(1, phases) / 1000.0


def _optional_conversion_fields(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    if "nominal_power_voltage_v" in raw and raw["nominal_power_voltage_v"] is not None:
        out["nominal_power_voltage_v"] = float(raw["nominal_power_voltage_v"])
    if "nominal_power_phases" in raw and raw["nominal_power_phases"] is not None:
        out["nominal_power_phases"] = max(1, int(raw["nominal_power_phases"]))
    return out


def merge_ev_power_conversion_fields(base: dict, raw: dict | None) -> dict:
    """Übernimmt optionale A→kW-Felder aus Roh-Config in ein Schedule-Dict."""
    merged = dict(base)
    merged.update(_optional_conversion_fields(raw))
    return merged


def ev_nominal_power_conversion(consumer: dict) -> tuple[float, int]:
    """Spannung (V) und Phasenzahl für A→kW-Umrechnung (Default 230 V / 1 Phase)."""
    sched = consumer.get("charging_schedule") or {}
    lox = sched.get("loxone") or {}

    voltage_raw = sched.get("nominal_power_voltage_v")
    if voltage_raw is None:
        voltage_raw = lox.get("nominal_power_voltage_v")
    voltage_v = float(
        voltage_raw if voltage_raw is not None else DEFAULT_EV_NOMINAL_VOLTAGE_V
    )

    phases_raw = sched.get("nominal_power_phases")
    if phases_raw is None:
        phases_raw = lox.get("nominal_power_phases")
    phases = int(phases_raw if phases_raw is not None else DEFAULT_EV_NOMINAL_PHASES)
    return voltage_v, max(1, phases)


def kw_from_nominal_reading(value: float, unit: str | None, consumer: dict) -> float:
    """Wandelt einen Loxone-Nennleistungswert (kW oder A) in kW um."""
    if unit == "a":
        voltage_v, phases = ev_nominal_power_conversion(consumer)
        return ampere_to_kw(value, voltage_v=voltage_v, phases=phases)
    return value

"""Resolve effective ESS SOC / power ceilings (HK vs live get_ess_*, 2.7.j)."""
from __future__ import annotations

from typing import Any


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _telemetry_power_kw(telemetry: dict[str, Any] | None, field: str) -> float | None:
    """EHAL ``get_ess_max_*`` is W; return kW magnitude or None if absent/invalid."""
    if not isinstance(telemetry, dict) or field not in telemetry:
        return None
    watts = _as_float(telemetry.get(field))
    if watts is None or watts < 0.0:
        return None
    return watts / 1000.0


def _telemetry_soc_percent(telemetry: dict[str, Any] | None, field: str) -> float | None:
    if not isinstance(telemetry, dict) or field not in telemetry:
        return None
    value = _as_float(telemetry.get(field))
    if value is None:
        return None
    return max(0.0, min(100.0, value))


def hk_ess_limits_from_battery_params(battery_params: dict[str, Any]) -> dict[str, float]:
    """HK ceilings from ``battery_params`` / snapshot (kW / %)."""
    charge = _as_float(battery_params.get("max_charge_power_kw"))
    discharge = _as_float(battery_params.get("max_discharge_power_kw"))
    legacy = _as_float(battery_params.get("max_power_kw"))
    if charge is None:
        charge = legacy if legacy is not None else 0.0
    if discharge is None:
        discharge = legacy if legacy is not None else 0.0
    min_soc = _as_float(battery_params.get("min_soc"))
    max_soc = _as_float(battery_params.get("max_soc"))
    return {
        "min_soc": 0.0 if min_soc is None else min_soc,
        "max_soc": 100.0 if max_soc is None else max_soc,
        "max_charge_power_kw": max(0.0, float(charge)),
        "max_discharge_power_kw": max(0.0, float(discharge)),
        "max_power_kw": max(0.0, float(charge), float(discharge)),
    }


def resolve_effective_ess_limits(
    battery_params: dict[str, Any],
    *,
    telemetry: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Effective SOC + charge/discharge caps for MILP / setpoints / export.

    When ``limits_from_live`` is true, prefer mapped ``get_ess_*`` values; missing
    mapping falls back to HK. When false, always use HK.
    """
    hk = hk_ess_limits_from_battery_params(battery_params)
    if not bool(battery_params.get("limits_from_live", False)):
        return hk

    live_min = _telemetry_soc_percent(telemetry, "get_ess_soc_min")
    live_max = _telemetry_soc_percent(telemetry, "get_ess_soc_max")
    live_charge = _telemetry_power_kw(telemetry, "get_ess_max_charge_power")
    live_discharge = _telemetry_power_kw(telemetry, "get_ess_max_discharge_power")

    charge = live_charge if live_charge is not None else hk["max_charge_power_kw"]
    discharge = (
        live_discharge if live_discharge is not None else hk["max_discharge_power_kw"]
    )
    return {
        "min_soc": live_min if live_min is not None else hk["min_soc"],
        "max_soc": live_max if live_max is not None else hk["max_soc"],
        "max_charge_power_kw": max(0.0, float(charge)),
        "max_discharge_power_kw": max(0.0, float(discharge)),
        "max_power_kw": max(0.0, float(charge), float(discharge)),
    }


def apply_effective_ess_limits(
    battery_params: dict[str, Any],
    *,
    telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of ``battery_params`` with effective SOC/power ceilings applied."""
    out = dict(battery_params)
    out.update(resolve_effective_ess_limits(battery_params, telemetry=telemetry))
    return out

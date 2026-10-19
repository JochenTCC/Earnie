"""Resolve effective ESS SOC / power ceilings (HK vs live get_ess_*, 2.7.j)."""
from __future__ import annotations

from typing import Any

_LIVE_LIMIT_KINDS: tuple[str, ...] = (
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def telemetry_for_ess(
    telemetry: dict[str, Any] | None,
    ess_id: str | None,
) -> dict[str, Any] | None:
    """Flat ``get_ess_*`` view for one ESS (entity-scoped keys win over plant-flat)."""
    if not isinstance(telemetry, dict):
        return telemetry
    slug = str(ess_id or "").strip()
    out: dict[str, Any] = {
        kind: telemetry[kind] for kind in _LIVE_LIMIT_KINDS if kind in telemetry
    }
    if not slug:
        return out or None
    from ehal.ess_fields import ess_field

    for kind in _LIVE_LIMIT_KINDS:
        qid = ess_field(slug, kind)
        if qid in telemetry:
            out[kind] = telemetry[qid]
    return out or None


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

    When ``limits_from_live`` is false: always HK.

    When true: use mapped ``get_ess_*`` when present, but never loosen beyond HK
    (``min`` for charge/discharge/max_soc, ``max`` for min_soc). Missing live
    fields fall back to HK. Entity-scoped ``ess.{id}.*`` keys are preferred when
    ``battery_params['id']`` is set.
    """
    hk = hk_ess_limits_from_battery_params(battery_params)
    if not bool(battery_params.get("limits_from_live", False)):
        return hk

    ess_id = str(battery_params.get("id") or "").strip() or None
    tel = telemetry_for_ess(telemetry, ess_id)
    live_min = _telemetry_soc_percent(tel, "get_ess_soc_min")
    live_max = _telemetry_soc_percent(tel, "get_ess_soc_max")
    live_charge = _telemetry_power_kw(tel, "get_ess_max_charge_power")
    live_discharge = _telemetry_power_kw(tel, "get_ess_max_discharge_power")

    charge = hk["max_charge_power_kw"]
    if live_charge is not None:
        charge = min(charge, live_charge)
    discharge = hk["max_discharge_power_kw"]
    if live_discharge is not None:
        discharge = min(discharge, live_discharge)
    min_soc = hk["min_soc"]
    if live_min is not None:
        min_soc = max(min_soc, live_min)
    max_soc = hk["max_soc"]
    if live_max is not None:
        max_soc = min(max_soc, live_max)
    return {
        "min_soc": float(min_soc),
        "max_soc": float(max_soc),
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

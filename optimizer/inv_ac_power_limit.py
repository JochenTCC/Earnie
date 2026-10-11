"""Per-inverter AC power limit setpoints (Inverter P5 curtailment write loop).

Curtail-only: lower ``set_inv_ac_power_limit`` when plant ``p_pv_curtail[t0] > 0``;
otherwise write the inverter rating (sticky release), like export-limit unconstrained.
"""
from __future__ import annotations

from typing import Any, Sequence

from optimizer.export_power_limit import EXPORT_LIMIT_UNCONSTRAINED_W
from optimizer.milp_inverter import (
    apply_dc_pv_cap,
    ac_clip_pv_and_max_discharge,
    is_grid_tied,
    optional_positive_kw,
    raw_pv_kw_by_inverter,
)

CURTAIL_EPS_KW = 1e-6


def eligible_inv_limit_ids(
    inverters: Sequence[dict],
    *,
    mapped_ids: set[str],
) -> set[str]:
    """Grid-tied ``control=full`` inverters with a mapped limit binding."""
    from house_config.inverter import DEFAULT_INVERTER_CONTROL

    out: set[str] = set()
    for inv in inverters:
        if not isinstance(inv, dict):
            continue
        inv_id = str(inv.get("id") or "").strip()
        if not inv_id or inv_id not in mapped_ids:
            continue
        if not is_grid_tied(inv):
            continue
        control = str(inv.get("control") or DEFAULT_INVERTER_CONTROL).strip().lower()
        if control != "full":
            continue
        out.add(inv_id)
    return out


def inverter_unconstrained_kw(
    inv: dict,
    *,
    pv_kwp: float = 0.0,
    force_discharge_kw: float = 0.0,
) -> float | None:
    """Physical AC maximum for sticky release (kW), or None if unknown."""
    max_ac = optional_positive_kw(inv, "max_ac_power_kw")
    if max_ac is not None:
        return float(max_ac)
    pv = max(0.0, float(pv_kwp or 0.0))
    max_pv = optional_positive_kw(inv, "max_pv_input_kw")
    if max_pv is not None:
        pv = min(pv, float(max_pv))
    contrib = pv + max(0.0, float(force_discharge_kw or 0.0))
    return contrib if contrib > 0.0 else None

def inv_ac_limit_setpoint_w(
    limit_kw: float | None, *, unconstrained_kw: float | None = None
) -> float:
    """Wire value for ``set_inv_ac_power_limit`` (W, magnitude)."""
    if limit_kw is None:
        if unconstrained_kw is not None and float(unconstrained_kw) > 0.0:
            return min(float(unconstrained_kw) * 1000.0, EXPORT_LIMIT_UNCONSTRAINED_W)
        return EXPORT_LIMIT_UNCONSTRAINED_W
    return min(max(0.0, float(limit_kw)) * 1000.0, EXPORT_LIMIT_UNCONSTRAINED_W)


def pv_kwp_by_inverter(pv_systems: Sequence[dict]) -> dict[str, float]:
    """Sum ``pv_kwp`` per ``inverter_id``."""
    out: dict[str, float] = {}
    for pv in pv_systems:
        if not isinstance(pv, dict):
            continue
        inv_id = str(pv.get("inverter_id") or "").strip()
        if not inv_id:
            continue
        out[inv_id] = out.get(inv_id, 0.0) + float(pv.get("pv_kwp") or 0.0)
    return out


def force_discharge_kw_by_inverter(battery_params: Sequence[dict]) -> dict[str, float]:
    """Max discharge kW of force-dischargeable house batteries per inverter."""
    from house_config.battery_control import (
        BATTERY_CONTROL_FULL,
        control_from_battery_params,
    )
    from house_config.powerstation import is_powerstation

    out: dict[str, float] = {}
    for bat in battery_params:
        if not isinstance(bat, dict):
            continue
        inv_id = str(bat.get("inverter_id") or "").strip()
        if not inv_id or is_powerstation(bat):
            continue
        if control_from_battery_params(bat) != BATTERY_CONTROL_FULL:
            continue
        out[inv_id] = out.get(inv_id, 0.0) + float(
            bat.get("max_discharge_power_kw", bat.get("max_power_kw") or 0.0) or 0.0
        )
    return out


def planned_discharge_kw_by_inverter(
    milp_plan: dict[str, Any] | None,
    *,
    battery_params: Sequence[dict],
) -> dict[str, float]:
    """Sum planned ESS discharge (kW) per inverter from ``milp_plan['ess']``."""
    out: dict[str, float] = {}
    ess_map = (milp_plan or {}).get("ess")
    if not isinstance(ess_map, dict):
        return out
    inv_by_bat: dict[str, str] = {}
    for bat in battery_params:
        if not isinstance(bat, dict):
            continue
        bat_id = str(bat.get("id") or "").strip()
        inv_id = str(bat.get("inverter_id") or "").strip()
        if bat_id and inv_id:
            inv_by_bat[bat_id] = inv_id
    for bat_id, powers in ess_map.items():
        if not isinstance(powers, dict):
            continue
        inv_id = inv_by_bat.get(str(bat_id).strip())
        if not inv_id:
            continue
        out[inv_id] = out.get(inv_id, 0.0) + max(
            0.0, float(powers.get("p_discharge") or 0.0)
        )
    return out


def _has_pv_curtail_weight(inv: dict) -> bool:
    from house_config.inverter import INVERTER_TYPE_BATTERY, INVERTER_TYPE_HYBRID

    inv_type = str(inv.get("type") or INVERTER_TYPE_HYBRID).strip().lower()
    return inv_type != INVERTER_TYPE_BATTERY


def allocate_inv_ac_limits_kw(
    *,
    inverters: Sequence[dict],
    writable_ids: set[str],
    plant_curtail_kw: float,
    matrix_row: dict[str, Any],
    pv_systems: Sequence[dict],
    pv_kwp_by_inverter: dict[str, float],
    force_discharge_kw_by_inverter: dict[str, float],
    planned_discharge_by_inverter: dict[str, float],
) -> dict[str, float]:
    """Per writable inverter: AC limit kW (curtail-only allocation).

    Keys are inverter ids in ``writable_ids``. Values are always concrete kW
    (unconstrained rating when no plant curtail).
    """
    inv_list = [inv for inv in inverters if isinstance(inv, dict)]
    curtail = max(0.0, float(plant_curtail_kw or 0.0))
    raw_pv = raw_pv_kw_by_inverter(
        matrix_row, inverters=list(inv_list), pv_systems=list(pv_systems)
    )

    base_pv_ac: dict[str, float] = {}
    for inv in inv_list:
        inv_id = str(inv.get("id") or "").strip()
        if not inv_id or inv_id not in writable_ids:
            continue
        if not is_grid_tied(inv):
            continue
        if not _has_pv_curtail_weight(inv):
            base_pv_ac[inv_id] = 0.0
            continue
        pv_dc = apply_dc_pv_cap(raw_pv.get(inv_id, 0.0), inv)
        pv_ac, _ = ac_clip_pv_and_max_discharge(pv_dc, inv)
        base_pv_ac[inv_id] = max(0.0, float(pv_ac))

    allocated: dict[str, float] = {i: 0.0 for i in writable_ids}
    if curtail > CURTAIL_EPS_KW:
        weight_ids = sorted(
            i
            for i in writable_ids
            if base_pv_ac.get(i, 0.0) > CURTAIL_EPS_KW
        )
        weight_sum = sum(base_pv_ac[i] for i in weight_ids)
        remaining = curtail
        for inv_id in weight_ids:
            if inv_id == weight_ids[-1]:
                share = remaining
            else:
                share = (
                    curtail * (base_pv_ac[inv_id] / weight_sum)
                    if weight_sum > 0.0
                    else 0.0
                )
                remaining = max(0.0, remaining - share)
            allocated[inv_id] = share

    limits: dict[str, float] = {}
    for inv in inv_list:
        inv_id = str(inv.get("id") or "").strip()
        if not inv_id or inv_id not in writable_ids:
            continue
        unc = inverter_unconstrained_kw(
            inv,
            pv_kwp=float(pv_kwp_by_inverter.get(inv_id) or 0.0),
            force_discharge_kw=float(
                force_discharge_kw_by_inverter.get(inv_id) or 0.0
            ),
        )
        discharge = max(0.0, float(planned_discharge_by_inverter.get(inv_id) or 0.0))
        share = allocated.get(inv_id, 0.0)
        if share <= CURTAIL_EPS_KW:
            limit = unc
        else:
            usable_pv = max(0.0, base_pv_ac.get(inv_id, 0.0) - share)
            limit = usable_pv + discharge
            if unc is not None:
                limit = min(float(limit), float(unc))
        if limit is None:
            limits[inv_id] = EXPORT_LIMIT_UNCONSTRAINED_W / 1000.0
        else:
            limits[inv_id] = max(0.0, float(limit))
    return limits
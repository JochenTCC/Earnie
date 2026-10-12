"""Inverter topology for MILP house balance (Inverter P3 / 2.7.l).

AC-path conversion: P_pv_ac = P_pv_dc · η_inv then existing AC clip.
Absent optional kW caps keep prior behaviour for that inverter.
"""
from __future__ import annotations

from typing import Any

import pulp

from house_config.inverter import (
    AC_GRID_TIED,
    AC_ISLAND,
    INVERTER_TYPE_BATTERY,
    INVERTER_TYPE_HYBRID,
    INVERTER_TYPE_PV_STRING,
)


def coerce_inverter_params_list(
    inverter_params: dict | list[dict] | None,
) -> list[dict]:
    if inverter_params is None:
        return []
    if isinstance(inverter_params, list):
        return [dict(item) for item in inverter_params if isinstance(item, dict)]
    if isinstance(inverter_params, dict):
        return [dict(inverter_params)]
    return []


def coerce_pv_systems_list(pv_systems: list[dict] | None) -> list[dict]:
    if not pv_systems:
        return []
    return [dict(item) for item in pv_systems if isinstance(item, dict)]


def inverters_by_id(inverters: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for inv in inverters:
        inv_id = str(inv.get("id") or "").strip()
        if inv_id:
            out[inv_id] = inv
    return out


def optional_positive_kw(inv: dict, field: str) -> float | None:
    if field not in inv or inv[field] is None or inv[field] == "":
        return None
    return float(inv[field])


def is_grid_tied(inv: dict) -> bool:
    return str(inv.get("ac_connection") or AC_GRID_TIED).strip().lower() != AC_ISLAND


def battery_on_grid_tied_bus(
    bat: dict,
    inv_map: dict[str, dict],
) -> bool:
    """True when the battery participates in the house AC balance."""
    ac = str(bat.get("ac_connection") or "").strip().lower()
    if ac == AC_ISLAND:
        return False
    if ac == AC_GRID_TIED:
        return True
    inv_id = str(bat.get("inverter_id") or "").strip()
    if not inv_id:
        return True
    inv = inv_map.get(inv_id)
    if inv is None:
        raise ValueError(
            f"Batterie '{bat.get('id')}': unbekannte inverter_id '{inv_id}'."
        )
    return is_grid_tied(inv)


def filter_house_balance_batteries(
    batteries: list[dict],
    inverters: list[dict],
) -> list[dict]:
    """Drop island-bus batteries when inverter topology is active."""
    if not inverters:
        return list(batteries)
    inv_map = inverters_by_id(inverters)
    return [b for b in batteries if battery_on_grid_tied_bus(b, inv_map)]


def apply_dc_pv_cap(pv_kw: float, inv: dict) -> float:
    """Optional max_pv_input_kw on inverter PV (absent = no cap)."""
    raw = max(0.0, float(pv_kw))
    cap = optional_positive_kw(inv, "max_pv_input_kw")
    if cap is None:
        return raw
    return min(raw, cap)


def inverter_efficiency(inv: dict) -> float:
    """One-way DC↔AC factor η_inv; required on normalized inverters."""
    if "efficiency" not in inv or inv["efficiency"] is None or inv["efficiency"] == "":
        raise ValueError(
            f"Inverter '{inv.get('id')}': efficiency (η_inv) fehlt."
        )
    eta = float(inv["efficiency"])
    if not (0.0 < eta <= 1.0):
        raise ValueError(
            f"Inverter '{inv.get('id')}': efficiency muss in (0, 1] liegen "
            f"(got {eta!r})."
        )
    return eta


def apply_dc_to_ac_efficiency(pv_dc_kw: float, inv: dict) -> float:
    """P_pv_ac = P_pv_dc · η_inv (before AC clip)."""
    return max(0.0, float(pv_dc_kw)) * inverter_efficiency(inv)


def ac_clip_pv_and_max_discharge(
    pv_dc_kw: float,
    inv: dict,
) -> tuple[float, float | None]:
    """House PV after η_inv + AC clip + optional discharge headroom.

    ``pv_dc_kw`` is DC after ``apply_dc_pv_cap``. Applies η_inv then AC clip.
    Returns ``(pv_for_house_kw, max_discharge_kw_or_None)``.
    ``None`` discharge cap means no inverter AC limit on discharge.
    """
    inv_type = str(inv.get("type") or INVERTER_TYPE_HYBRID).strip().lower()
    max_ac = optional_positive_kw(inv, "max_ac_power_kw")
    if inv_type == INVERTER_TYPE_BATTERY:
        return 0.0, max_ac
    pv_after_eta = apply_dc_to_ac_efficiency(pv_dc_kw, inv)
    if max_ac is None:
        return pv_after_eta, None
    pv_ac = min(pv_after_eta, max_ac)
    return pv_ac, max(0.0, max_ac - pv_ac)


def _pv_id_to_inverter(
    pv_systems: list[dict],
    inv_map: dict[str, dict],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for pv in pv_systems:
        pv_id = str(pv.get("id") or "").strip()
        if not pv_id:
            continue
        inv_id = str(pv.get("inverter_id") or "").strip()
        if not inv_id:
            raise ValueError(f"PV-Anlage '{pv_id}': inverter_id fehlt.")
        if inv_id not in inv_map:
            raise ValueError(
                f"PV-Anlage '{pv_id}': unbekannte inverter_id '{inv_id}'."
            )
        mapping[pv_id] = inv_id
    return mapping


def raw_pv_kw_by_inverter(
    matrix_row: dict[str, Any],
    *,
    inverters: list[dict],
    pv_systems: list[dict],
) -> dict[str, float]:
    """Group slot PV forecast by inverter_id (before DC/AC caps)."""
    inv_map = inverters_by_id(inverters)
    if not inv_map:
        return {}
    pv_to_inv = _pv_id_to_inverter(pv_systems, inv_map)
    by_system = matrix_row.get("expected_p_pv_by_system")
    out: dict[str, float] = {inv_id: 0.0 for inv_id in inv_map}
    if isinstance(by_system, dict):
        for pv_id, power in by_system.items():
            key = str(pv_id).strip()
            if key not in pv_to_inv:
                raise ValueError(
                    f"expected_p_pv_by_system: unbekannte PV-id '{key}'."
                )
            out[pv_to_inv[key]] += max(0.0, float(power or 0.0))
        return out
    inv_with_pv = sorted(set(pv_to_inv.values()))
    plant_pv = max(0.0, float(matrix_row.get("expected_p_pv") or 0.0))
    if len(inv_with_pv) > 1:
        raise ValueError(
            "expected_p_pv_by_system fehlt, obwohl mehrere Wechselrichter "
            "PV-Anlagen haben (Inverter P3)."
        )
    if len(inv_with_pv) == 1:
        out[inv_with_pv[0]] = plant_pv
    return out


def house_balance_pv_kw(
    matrix_row: dict[str, Any],
    *,
    inverters: list[dict],
    pv_systems: list[dict],
) -> float:
    """Grid-tied inverter PV after DC + AC clip (island excluded)."""
    if not inverters:
        return max(0.0, float(matrix_row.get("expected_p_pv") or 0.0))
    raw = raw_pv_kw_by_inverter(
        matrix_row, inverters=inverters, pv_systems=pv_systems
    )
    total = 0.0
    for inv in inverters:
        inv_id = str(inv.get("id") or "").strip()
        if not inv_id or not is_grid_tied(inv):
            continue
        pv_dc = apply_dc_pv_cap(raw.get(inv_id, 0.0), inv)
        pv_ac, _ = ac_clip_pv_and_max_discharge(pv_dc, inv)
        total += pv_ac
    return total


def ess_ids_on_inverter(
    ess_ids: list[str],
    battery_params_by_id: dict[str, dict],
    inv_id: str,
) -> list[str]:
    target = str(inv_id or "").strip()
    return [
        eid
        for eid in ess_ids
        if str(battery_params_by_id[eid].get("inverter_id") or "").strip() == target
    ]


def add_inverter_slot_constraints(
    prob: pulp.LpProblem,
    *,
    t: int,
    grid_vars: Any,
    inverters: list[dict],
    pv_systems: list[dict],
    matrix_row: dict[str, Any],
) -> None:
    """AC clipping, optional grid-charge cap (per inverter, one slot)."""
    if not inverters:
        return
    raw = raw_pv_kw_by_inverter(
        matrix_row, inverters=inverters, pv_systems=pv_systems
    )
    params_by = grid_vars.battery_params_by_id
    for inv in inverters:
        if not is_grid_tied(inv):
            continue
        inv_id = str(inv.get("id") or "").strip()
        if not inv_id:
            continue
        ess_ids = ess_ids_on_inverter(grid_vars.ess_ids, params_by, inv_id)
        _add_one_inverter_slot(
            prob,
            t=t,
            inv=inv,
            inv_id=inv_id,
            pv_raw=raw.get(inv_id, 0.0),
            ess_ids=ess_ids,
            grid_vars=grid_vars,
        )


def _add_one_inverter_slot(
    prob: pulp.LpProblem,
    *,
    t: int,
    inv: dict,
    inv_id: str,
    pv_raw: float,
    ess_ids: list[str],
    grid_vars: Any,
) -> None:
    slug = inv_id.replace("-", "_")
    pv_dc = apply_dc_pv_cap(pv_raw, inv)
    inv_type = str(inv.get("type") or INVERTER_TYPE_HYBRID).strip().lower()
    max_ac = optional_positive_kw(inv, "max_ac_power_kw")
    discharge_sum = pulp.lpSum(
        grid_vars.p_discharge_by_ess[eid][t] for eid in ess_ids
    )
    charge_sum = pulp.lpSum(
        grid_vars.p_charge_by_ess[eid][t] for eid in ess_ids
    )
    if inv_type == INVERTER_TYPE_BATTERY and max_ac is not None:
        prob += discharge_sum <= max_ac, f"inv_ac_dis_{slug}_{t}"
        prob += charge_sum <= max_ac, f"inv_ac_chg_{slug}_{t}"
    elif inv_type in (INVERTER_TYPE_HYBRID, INVERTER_TYPE_PV_STRING):
        _, max_dis = ac_clip_pv_and_max_discharge(pv_dc, inv)
        if max_dis is not None and ess_ids:
            prob += discharge_sum <= max_dis, f"inv_ac_clip_{slug}_{t}"
    max_chg = optional_positive_kw(inv, "max_ac_charge_kw")
    if max_chg is not None and ess_ids:
        prob += charge_sum <= max_chg, f"inv_ac_charge_cap_{slug}_{t}"

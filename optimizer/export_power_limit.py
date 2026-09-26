"""Hard grid-export power ceilings (2.7.a).

Effective cap = min of active sources; missing source = no cap from that source.
When ``k_push_act < 0`` (user pays to export), that slot is hard-capped at 0 kW.
"""
from __future__ import annotations

from typing import Sequence

# ``set_grid_export_power_limit`` is a non-negative magnitude (W), like the ESS limits.
# Unconstrained = the plant's physical export maximum (see ``physical_max_export_kw``)
# so sticky backends (Loxone/HA) release the curtailment — never omit on sticky paths.
# This 1 MW value is only the fallback when PV/ESS ratings are unknown; inbound values
# at or above it also mean "no cap".
EXPORT_LIMIT_UNCONSTRAINED_W = 1_000_000.0


def coerce_optional_kw(value: object | None) -> float | None:
    """Return a non-negative kW cap, or None if absent/invalid."""
    if value is None:
        return None
    try:
        kw = float(value)
    except (TypeError, ValueError):
        return None
    if kw < 0.0:
        return None
    return kw


def inbound_limit_w_to_kw(value_w: object | None) -> float | None:
    """Convert EHAL inbound ``get_grid_export_power_limit`` (W) to kW.

    Negative or ``>= EXPORT_LIMIT_UNCONSTRAINED_W`` = no inbound cap.
    """
    if value_w is None:
        return None
    try:
        watts = float(value_w)
    except (TypeError, ValueError):
        return None
    if watts < 0.0 or watts >= EXPORT_LIMIT_UNCONSTRAINED_W:
        return None
    return watts / 1000.0


def effective_export_cap_kw(
    *,
    hk_max_export_kw: float | None = None,
    inbound_limit_kw: float | None = None,
    k_push_act: float | None = None,
) -> float | None:
    """Min of active hard ceilings; None = unconstrained."""
    caps: list[float] = []
    hk = coerce_optional_kw(hk_max_export_kw)
    if hk is not None:
        caps.append(hk)
    inbound = coerce_optional_kw(inbound_limit_kw)
    if inbound is not None:
        caps.append(inbound)
    if k_push_act is not None:
        try:
            if float(k_push_act) < 0.0:
                caps.append(0.0)
        except (TypeError, ValueError):
            pass
    if not caps:
        return None
    return min(caps)


def export_caps_for_horizon(
    matrix: Sequence[dict],
    *,
    hk_max_export_kw: float | None = None,
    inbound_limit_kw: float | None = None,
    fallback_k_push: float = 0.0,
) -> list[float | None]:
    """Per-slot effective export caps (kW) for the MILP horizon."""
    from data.feed_in_prices import k_push_act_for_matrix_row

    caps: list[float | None] = []
    for row in matrix:
        k_push = k_push_act_for_matrix_row(row, float(fallback_k_push))
        caps.append(
            effective_export_cap_kw(
                hk_max_export_kw=hk_max_export_kw,
                inbound_limit_kw=inbound_limit_kw,
                k_push_act=k_push,
            )
        )
    return caps


def physical_max_export_kw(
    pv_kwp: float | None, force_discharge_kw: float | None
) -> float | None:
    """Plant export maximum: PV nameplate sum + max discharge of force-discharge ESS.

    ``force_discharge_kw`` must only include batteries that can be force-discharged
    into the grid. Multi-ESS (2.7.c): pass the sum over all such batteries.
    None when both parts are unknown/zero.
    """
    total = max(0.0, float(pv_kwp or 0.0)) + max(0.0, float(force_discharge_kw or 0.0))
    return total if total > 0.0 else None


def export_limit_setpoint_w(
    effective_cap_kw: float | None, *, unconstrained_kw: float | None = None
) -> float:
    """Wire value for ``set_grid_export_power_limit`` (W, magnitude).

    ``None`` (unconstrained) → ``unconstrained_kw`` (plant maximum, see
    ``physical_max_export_kw``), else ``EXPORT_LIMIT_UNCONSTRAINED_W``.
    """
    if effective_cap_kw is None:
        if unconstrained_kw is not None and float(unconstrained_kw) > 0.0:
            return min(float(unconstrained_kw) * 1000.0, EXPORT_LIMIT_UNCONSTRAINED_W)
        return EXPORT_LIMIT_UNCONSTRAINED_W
    return min(max(0.0, float(effective_cap_kw)) * 1000.0, EXPORT_LIMIT_UNCONSTRAINED_W)


def export_limit_setpoint_kw(
    effective_cap_kw: float | None, *, unconstrained_kw: float | None = None
) -> float:
    """Loxone Merker / status.json value (kW); same rules as ``export_limit_setpoint_w``."""
    return (
        export_limit_setpoint_w(effective_cap_kw, unconstrained_kw=unconstrained_kw)
        / 1000.0
    )


def plant_max_export_power_kw(house_doc: dict | None) -> float | None:
    """Read optional ``plant.max_export_power_kw`` from a house_profiles document."""
    if not isinstance(house_doc, dict):
        return None
    plant = house_doc.get("plant")
    if not isinstance(plant, dict):
        return None
    return coerce_optional_kw(plant.get("max_export_power_kw"))

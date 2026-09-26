"""Hard grid-export power ceilings (2.7.a).

Effective cap = min of active sources; missing source = no cap from that source.
When ``k_push_act < 0`` (user pays to export), that slot is hard-capped at 0 kW.
"""
from __future__ import annotations

from typing import Sequence

# Sticky backends (Loxone/HA): write this on ``set_grid_export_power_limit`` when
# unconstrained so Config releases curtailment (never omit on sticky paths).
EXPORT_LIMIT_UNCONSTRAINED_SENTINEL_W = -1.0

# Loxone/HA sticky ``set_ess_mode`` / Steuerbefehl when Einspeisesperre is active.
STEUERBEFEHL_EINSPEISESPERRE = 3


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
    """Convert EHAL inbound ``get_grid_export_power_limit`` (W) to kW."""
    if value_w is None:
        return None
    try:
        watts = float(value_w)
    except (TypeError, ValueError):
        return None
    if watts < 0.0:
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


def export_limit_setpoint_w(effective_cap_kw: float | None) -> float:
    """Wire value for ``set_grid_export_power_limit`` (W); ``-1`` = unconstrained."""
    if effective_cap_kw is None:
        return EXPORT_LIMIT_UNCONSTRAINED_SENTINEL_W
    return max(0.0, float(effective_cap_kw)) * 1000.0


def export_limit_setpoint_kw(effective_cap_kw: float | None) -> float:
    """Loxone Merker / status.json value (kW); ``-1`` = unconstrained."""
    if effective_cap_kw is None:
        return EXPORT_LIMIT_UNCONSTRAINED_SENTINEL_W
    return max(0.0, float(effective_cap_kw))


def plant_max_export_power_kw(house_doc: dict | None) -> float | None:
    """Read optional ``plant.max_export_power_kw`` from a house_profiles document."""
    if not isinstance(house_doc, dict):
        return None
    plant = house_doc.get("plant")
    if not isinstance(plant, dict):
        return None
    return coerce_optional_kw(plant.get("max_export_power_kw"))

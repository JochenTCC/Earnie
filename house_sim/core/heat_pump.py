"""Heat pump with a heat store and its own controller (HeatControl P2; no Earnie imports).

The controller keeps the store between its normal setpoint and the band below it, like a
plant controller does without Earnie. Earnie's request arrives either as level 0
(``enable`` 0/1) or as level 1 (``sg_ready_state`` 1–4, docs/dev/heat-control-sg-ready.md
§ 6); one source per step:

- enable 0 / state 2: normal operation, target = setpoint.
- enable 1 / state 3: target = setpoint + boost (the fixed boost of the heating system).
- state 1: lock, the generator does not start (a running one stops).
- state 4: forced charge up to ``max_c``, started at once without waiting for the band.

Level 2 (HeatControl P3) adds ``store_target_c``: in a charge (enable 1 / state 3) the
controller charges to that temperature instead of setpoint + boost; ``0`` = no target. A
backend may use the target alone, without enable or state: target > 0 is a charge to it,
0 is normal operation.

The generator starts when the store is below target − tolerance (the switch-on
difference) and runs until it reaches the target. Heat is put in at the generator's
thermal power, capped at the target within a step.
"""
from __future__ import annotations

from dataclasses import dataclass

from .thermal import compute_heat_loss_kw

SG_READY_LOCK = 1
SG_READY_NORMAL = 2
SG_READY_CHARGE = 3
SG_READY_FORCED = 4


@dataclass(frozen=True)
class HeatPumpStoreParams:
    capacity_kwh_per_k: float
    heat_loss_kw_per_k: float
    heat_power_kw: float
    cop: float
    setpoint_c: float
    tolerance_c: float
    boost_k: float = 0.0
    max_c: float | None = None

    def __post_init__(self) -> None:
        if self.capacity_kwh_per_k <= 0:
            raise ValueError("capacity_kwh_per_k must be > 0")
        if self.heat_power_kw <= 0:
            raise ValueError("heat_power_kw must be > 0")
        if self.cop <= 0:
            raise ValueError("cop must be > 0")
        if self.tolerance_c < 0 or self.boost_k < 0:
            raise ValueError("tolerance_c and boost_k must be >= 0")


@dataclass(frozen=True)
class HeatPumpStoreState:
    temp_c: float
    running: bool = False


def _request_state(
    enable: int | None, sg_ready_state: int | None, store_target_c: float | None = None
) -> int:
    """Earnie's request as an SG-Ready state; one of enable / state, or the target alone."""
    if enable is None and sg_ready_state is None and store_target_c is not None:
        return SG_READY_CHARGE if store_target_c > 0 else SG_READY_NORMAL
    if (enable is None) == (sg_ready_state is None):
        raise ValueError("give exactly one of enable (level 0) or sg_ready_state (level 1)")
    if enable is not None:
        if enable not in (0, 1):
            raise ValueError(f"enable must be 0 or 1, got {enable!r}")
        return SG_READY_CHARGE if enable else SG_READY_NORMAL
    if sg_ready_state not in (1, 2, 3, 4):
        raise ValueError(f"sg_ready_state must be 1..4, got {sg_ready_state!r}")
    return int(sg_ready_state)


def controller_target_c(
    params: HeatPumpStoreParams, state: int, store_target_c: float | None = None
) -> float | None:
    """Store temperature the controller charges to in ``state``; None = locked."""
    if state == SG_READY_LOCK:
        return None
    if state == SG_READY_NORMAL:
        return params.setpoint_c
    if state == SG_READY_CHARGE:
        if store_target_c is not None and store_target_c > 0:
            upper = store_target_c if params.max_c is None else min(store_target_c, params.max_c)
            return max(params.setpoint_c, float(upper))
        return params.setpoint_c + params.boost_k
    if params.max_c is None:
        raise ValueError("state 4 needs max_c (the controller's highest store temperature)")
    return float(params.max_c)


def step_heat_pump_store(
    params: HeatPumpStoreParams,
    state: HeatPumpStoreState,
    *,
    demand_kw: float,
    ambient_c: float,
    dt_h: float,
    enable: int | None = None,
    sg_ready_state: int | None = None,
    store_target_c: float | None = None,
) -> tuple[HeatPumpStoreState, float]:
    """Advance the store by ``dt_h``; return the new state and the electricity [kWh]."""
    if dt_h <= 0:
        raise ValueError("dt_h must be > 0")
    if store_target_c is not None and store_target_c < 0:
        raise ValueError("store_target_c must be >= 0 (0 = no target)")
    request = _request_state(enable, sg_ready_state, store_target_c)
    target = controller_target_c(params, request, store_target_c)
    temp = float(state.temp_c)
    if target is None:
        running = False
    elif state.running:
        running = temp < target - 1e-9
    elif request == SG_READY_FORCED:
        running = temp < target - 1e-9
    else:
        running = temp < target - params.tolerance_c - 1e-9
    loss_kw = compute_heat_loss_kw(temp, ambient_c, params.heat_loss_kw_per_k)
    heat_kwh = 0.0
    if running and target is not None:
        room_kwh = (target - temp) * params.capacity_kwh_per_k + (
            float(demand_kw) + loss_kw
        ) * dt_h
        heat_kwh = max(0.0, min(params.heat_power_kw * dt_h, room_kwh))
    next_temp = temp + (heat_kwh - (float(demand_kw) + loss_kw) * dt_h) / (
        params.capacity_kwh_per_k
    )
    still_running = running and target is not None and next_temp < target - 1e-9
    return HeatPumpStoreState(temp_c=next_temp, running=still_running), heat_kwh / params.cop

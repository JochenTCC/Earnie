"""Short closed-loop physics (mock adapter over house_sim.core)."""
from __future__ import annotations

from house_sim.core.archetype import ArchetypePackage
from house_sim.core.physics import (
    EssSetpoints,
    PhysicsState,
    ScenarioOverlay,
    ess_setpoints_from_lookup,
    initial_physics,
    resolve_ess_power_w,
    run_ticks as _core_run_ticks,
    step_physics as _core_step_physics,
)
from house_sim.state_store import StateStore

__all__ = [
    "EssSetpoints",
    "PhysicsState",
    "ScenarioOverlay",
    "initial_physics",
    "resolve_ess_power_w",
    "run_ticks",
    "step_physics",
    "setpoints_from_store",
]


def setpoints_from_store(store: StateStore, package: ArchetypePackage) -> EssSetpoints:
    """Read ESS setpoints from mapped mock entities (unit-aware, EHAL signed W)."""
    return ess_setpoints_from_lookup(package, store.numeric_state)


def step_physics(
    state: PhysicsState,
    *,
    package: ArchetypePackage,
    store: StateStore,
    dt_h: float,
    overlay: ScenarioOverlay | None = None,
    pv_kw_override: float | None = None,
) -> PhysicsState:
    """Advance physics using last setpoints written into the mock store."""
    return _core_step_physics(
        state,
        package=package,
        setpoints=setpoints_from_store(store, package),
        dt_h=dt_h,
        overlay=overlay,
        pv_kw_override=pv_kw_override,
    )


def run_ticks(
    package: ArchetypePackage,
    store: StateStore,
    *,
    n_ticks: int,
    dt_h: float,
    physics: PhysicsState | None = None,
    overlay: ScenarioOverlay | None = None,
) -> PhysicsState:
    return _core_run_ticks(
        package,
        store,
        n_ticks=n_ticks,
        dt_h=dt_h,
        physics=physics,
        overlay=overlay,
        read_setpoints=setpoints_from_store,
    )

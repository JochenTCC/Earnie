# GENERATED — edit house_sim/core/ (or fixtures), then run:
#   python -m scripts.sync_house_sim_integration
# Do not hand-edit this copy.
"""Pure house-sim physics core (no Home Assistant, no Earnie imports)."""

from __future__ import annotations

from .archetype import (
    FIXTURES_DIR,
    ArchetypePackage,
    load_archetype,
    physics_entity_values,
    project_physics_to_store,
)
from .physics import (
    EssSetpoints,
    PhysicsState,
    ScenarioOverlay,
    ess_setpoints_from_lookup,
    initial_physics,
    run_ticks,
    step_physics,
)
from .thermal import compute_heat_loss_kw, simulate_next_temp_c
from .weather_pv import pv_kw_from_weather

__all__ = [
    "FIXTURES_DIR",
    "ArchetypePackage",
    "EssSetpoints",
    "PhysicsState",
    "ScenarioOverlay",
    "compute_heat_loss_kw",
    "ess_setpoints_from_lookup",
    "initial_physics",
    "load_archetype",
    "physics_entity_values",
    "project_physics_to_store",
    "pv_kw_from_weather",
    "run_ticks",
    "simulate_next_temp_c",
    "step_physics",
]

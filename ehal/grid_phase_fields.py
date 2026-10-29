"""Grid meter per-phase EHAL fields for device detection (NILM stage 0, dev only).

Read-only meter values at the point of common coupling, exchanged as
``grid.meter.<kind>``. They are pushed by the hub (Loxone VO) and only logged
(``runtime_store.grid_phase_log``); the optimizer does not read them.

Not part of the public mapping catalog: the fields live in their own role file
``share/ehal/roles/grid_phases.json`` (hub conversion) instead of ``grid.json``, so
``ehal.signal_catalog`` does not offer them. Activation is the UI mode key
``device_detection`` in ``EARNIE_UI_MODES`` (``runtime_store.env_vars``).

Units / signs (EHAL wire, see ``docs/dev/nilm-grid-phase-logging.md``):

* ``sens_grid_voltage_l{1,2,3}`` — V, line-to-neutral
* ``sens_grid_current_l{1,2,3}`` — A, as delivered by the meter
* ``sens_grid_power_active_l{1,2,3}`` — W, ``+`` = import (same as ``sens_grid_power_active``)
* ``sens_grid_power_reactive`` — var, total, sign as delivered by the meter
* ``sens_grid_power_factor`` — dimensionless, total
"""
from __future__ import annotations

from ehal.qualified_ids import field_kind, qualified_grid_id

PHASES: tuple[str, ...] = ("l1", "l2", "l3")

GRID_PHASE_KINDS: tuple[str, ...] = (
    *(f"sens_grid_voltage_{p}" for p in PHASES),
    *(f"sens_grid_current_{p}" for p in PHASES),
    *(f"sens_grid_power_active_{p}" for p in PHASES),
    "sens_grid_power_reactive",
    "sens_grid_power_factor",
)

# Total grid power is logged alongside (stage 0 acceptance: Σ phases vs. total).
GRID_PHASE_LOG_KINDS: tuple[str, ...] = ("sens_grid_power_active",) + GRID_PHASE_KINDS


def grid_phase_ids() -> tuple[str, ...]:
    """Qualified exchange IDs (``grid.meter.<kind>``) of the per-phase fields."""
    return tuple(qualified_grid_id(kind) for kind in GRID_PHASE_KINDS)


def grid_phase_log_ids() -> frozenset[str]:
    """Qualified IDs written to the device-detection log (per-phase + total power)."""
    return frozenset(qualified_grid_id(kind) for kind in GRID_PHASE_LOG_KINDS)


def is_grid_phase_kind(field: str) -> bool:
    return field_kind(field) in GRID_PHASE_KINDS

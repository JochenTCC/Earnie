"""Dataclasses of the horizon simulation (split from simulation)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


@dataclass(frozen=True)
class _HorizonOptions:
    """Unveränderte ``simulate_horizon``-Steuerparameter für die Slot-Helfer."""

    k_push: float | None
    verbose: bool
    commit_hours: int
    flex_book_hours: int | None
    flex_book_start: int
    sunrise_soc_min_index: int | None
    soc_hold_index: int | None
    soc_hold_percent: float | None


@dataclass(frozen=True)
class _HorizonSetup:
    """Vorbereitete Matrix, Kontexte und Flex-Grenzen eines Horizontlaufs."""

    matrix: list
    consumers_cfg: list
    battery_params: dict
    batteries: list[dict]
    charging_contexts: dict[str, dict] | None
    filters: dict[str, dict] | None
    horizon_limits: dict[str, float]
    horizon_terminal_soc: float | None
    options: _HorizonOptions
    current_soc_by_id: dict[str, float] | None = None
    chart_soc_entities: tuple[dict, ...] = ()
    standby_plans: dict | None = None
    standby_packs_by_id: dict | None = None


class _SlotInputs(NamedTuple):
    """Slot-abhängige MILP-Eingaben (Restmatrix, Restenergie, Flex-Fenster)."""

    remaining_slice: list
    remaining: dict[str, float]
    continue_on: dict[str, bool]
    flex_indices: list[int]

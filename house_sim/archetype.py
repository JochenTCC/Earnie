"""Load hand-authored archetype fixtures for the HouseSim bench."""
from __future__ import annotations

from pathlib import Path

from house_sim.core.archetype import (
    FIXTURES_DIR,
    ArchetypePackage,
    load_archetype as _core_load,
    project_physics_to_store,
)
from house_sim.state_store import StateStore

__all__ = [
    "FIXTURES_DIR",
    "ArchetypePackage",
    "load_archetype",
    "project_physics_to_store",
]


def _build_store(self: ArchetypePackage) -> StateStore:
    return StateStore(self.entities)


ArchetypePackage.build_store = _build_store  # type: ignore[attr-defined]


def load_archetype(name: str, *, fixtures_dir: Path | None = None) -> ArchetypePackage:
    return _core_load(name, fixtures_dir=fixtures_dir)

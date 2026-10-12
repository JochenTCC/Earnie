"""Topology P1: regulates_on enum helpers (no silent defaults for house batteries)."""
from __future__ import annotations

from typing import Literal

RegulatesOn = Literal["grid", "none"]

REGULATES_ON_GRID: RegulatesOn = "grid"
REGULATES_ON_NONE: RegulatesOn = "none"
_VALID = frozenset({REGULATES_ON_GRID, REGULATES_ON_NONE})

TOPOLOGY_MIGRATE_HINT = (
    "components.json needs batteries[].regulates_on on house batteries "
    "(Topology P1). Run: "
    "python -m scripts.migrate_topology_once --config-dir <config-dir>"
)


def normalize_regulates_on(
    raw: object,
    *,
    entity_kind: str,
    entity_id: str,
    index: int,
    required: bool,
) -> RegulatesOn | None:
    """Validate regulates_on; return None when optional and absent."""
    if raw is None or raw == "":
        if required:
            raise ValueError(
                f"{entity_kind}[{index}] ('{entity_id}'): regulates_on fehlt. "
                f"{TOPOLOGY_MIGRATE_HINT}"
            )
        return None
    value = str(raw).strip().lower()
    if value not in _VALID:
        raise ValueError(
            f"{entity_kind}[{index}] ('{entity_id}'): regulates_on muss "
            f"'grid' oder 'none' sein (got {raw!r})."
        )
    return value  # type: ignore[return-value]

"""Entity-scoped PV EHAL field names: ``pv.{slug}.sens_pv_production_active``."""
from __future__ import annotations

import re

# Canonical field kinds (suffix after pv.{slug}.)
PV_FIELD_KINDS: frozenset[str] = frozenset(
    {
        "sens_pv_production_active",
    }
)

PV_MAPPING_KINDS: tuple[str, ...] = tuple(sorted(PV_FIELD_KINDS))

PV_LIVE_READ_KINDS: tuple[str, ...] = ("sens_pv_production_active",)

_ENTITY_SCOPED = re.compile(
    r"^pv\.(?P<slug>[^.]+)\.(?P<kind>"
    + "|".join(sorted(PV_FIELD_KINDS))
    + r")$"
)


def pv_ehal_slug(pv_system_id: str) -> str:
    """Wire slug for entity-scoped PV bindings."""
    return str(pv_system_id or "").strip()


def pv_field(pv_system_id: str, kind: str) -> str:
    """Canonical binding / Live field: ``pv.{slug}.{kind}``."""
    kind_s = str(kind or "").strip()
    if kind_s not in PV_FIELD_KINDS:
        raise ValueError(f"Unknown PV EHAL kind '{kind_s}'.")
    slug = pv_ehal_slug(pv_system_id)
    if not slug:
        raise ValueError("PV EHAL field needs a non-empty pv_system id / slug.")
    return f"pv.{slug}.{kind_s}"


def pv_field_kind(field: str) -> str | None:
    """Return kind for entity-scoped or flat plant PV key, else None."""
    name = str(field or "").strip()
    if name in PV_FIELD_KINDS:
        return name
    match = _ENTITY_SCOPED.match(name)
    if match:
        return match.group("kind")
    return None


def is_pv_entity_scoped_field(field: str) -> bool:
    return _ENTITY_SCOPED.match(str(field or "").strip()) is not None


def parse_pv_entity_scoped(field: str) -> tuple[str, str] | None:
    """Return (slug, kind) for ``pv.{slug}.{kind}``, else None."""
    match = _ENTITY_SCOPED.match(str(field or "").strip())
    if not match:
        return None
    return match.group("slug"), match.group("kind")


def binding_address(
    bindings: dict | None,
    pv_system_id: str,
    kind: str,
) -> str:
    """Address for ``pv.{slug}.{kind}`` only."""
    if not isinstance(bindings, dict):
        return ""
    return str(bindings.get(pv_field(pv_system_id, kind)) or "").strip()

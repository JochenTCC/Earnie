"""Entity-scoped inverter EHAL field names: ``inv.{slug}.sens_inv_power_ac`` (2.7.l P4)."""
from __future__ import annotations

import re

# Canonical §C field kinds (suffix after inv.{slug}.)
INVERTER_FIELD_KINDS: frozenset[str] = frozenset(
    {
        "sens_inv_power_ac",
        "sens_inv_power_pv",
        "get_inv_max_ac_power",
        "get_inv_max_pv_power",
        "set_inv_ac_power_limit",
    }
)

INVERTER_MAPPING_KINDS: tuple[str, ...] = tuple(sorted(INVERTER_FIELD_KINDS))

INVERTER_LIVE_READ_KINDS: tuple[str, ...] = (
    "sens_inv_power_ac",
    "sens_inv_power_pv",
    "get_inv_max_ac_power",
    "get_inv_max_pv_power",
)

INVERTER_LIVE_WRITE_KINDS: tuple[str, ...] = ("set_inv_ac_power_limit",)

_ENTITY_SCOPED = re.compile(
    r"^inv\.(?P<slug>[^.]+)\.(?P<kind>"
    + "|".join(sorted(INVERTER_FIELD_KINDS))
    + r")$"
)


def inv_ehal_slug(inverter_id: str) -> str:
    """Wire slug for entity-scoped inverter bindings."""
    return str(inverter_id or "").strip()


def inv_field(inverter_id: str, kind: str) -> str:
    """Canonical binding / Live field: ``inv.{slug}.{kind}``."""
    kind_s = str(kind or "").strip()
    if kind_s not in INVERTER_FIELD_KINDS:
        raise ValueError(f"Unknown inverter EHAL kind '{kind_s}'.")
    slug = inv_ehal_slug(inverter_id)
    if not slug:
        raise ValueError("Inverter EHAL field needs a non-empty inverter id / slug.")
    return f"inv.{slug}.{kind_s}"


def inv_field_kind(field: str) -> str | None:
    """Return kind for entity-scoped or flat inverter key, else None."""
    name = str(field or "").strip()
    if name in INVERTER_FIELD_KINDS:
        return name
    match = _ENTITY_SCOPED.match(name)
    if match:
        return match.group("kind")
    return None


def is_inv_entity_scoped_field(field: str) -> bool:
    return _ENTITY_SCOPED.match(str(field or "").strip()) is not None


def parse_inv_entity_scoped(field: str) -> tuple[str, str] | None:
    """Return (slug, kind) for ``inv.{slug}.{kind}``, else None."""
    match = _ENTITY_SCOPED.match(str(field or "").strip())
    if not match:
        return None
    return match.group("slug"), match.group("kind")


def binding_address(
    bindings: dict | None,
    inverter_id: str,
    kind: str,
) -> str:
    """Address for ``inv.{slug}.{kind}`` only."""
    if not isinstance(bindings, dict):
        return ""
    return str(bindings.get(inv_field(inverter_id, kind)) or "").strip()

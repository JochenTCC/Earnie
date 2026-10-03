"""Pattern B ESS EHAL field names: ``ess.{slug}.sens_ess_soc`` etc. (2.7.c)."""
from __future__ import annotations

import re

# Canonical §C field kinds (suffix after ess.{slug}.)
ESS_FIELD_KINDS: frozenset[str] = frozenset(
    {
        "sens_ess_soc",
        "sens_ess_power",
        "set_ess_active_power",
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
        "set_ess_mode",
        "get_ess_soc_min",
        "get_ess_soc_max",
        "get_ess_max_charge_power",
        "get_ess_max_discharge_power",
    }
)

_PLANT_FLAT_ESS_FIELDS: frozenset[str] = frozenset(ESS_FIELD_KINDS)

_PATTERN_B = re.compile(
    r"^ess\.(?P<slug>[^.]+)\.(?P<kind>"
    + "|".join(sorted(ESS_FIELD_KINDS))
    + r")$"
)


def ess_ehal_slug(battery_id: str) -> str:
    """Wire slug for Pattern B ESS bindings."""
    return str(battery_id or "").strip()


def ess_field(battery_id: str, kind: str) -> str:
    """Canonical binding / Live field: ``ess.{slug}.{kind}``."""
    kind_s = str(kind or "").strip()
    if kind_s not in ESS_FIELD_KINDS:
        raise ValueError(f"Unknown ESS EHAL kind '{kind_s}'.")
    slug = ess_ehal_slug(battery_id)
    if not slug:
        raise ValueError("ESS EHAL field needs a non-empty battery id / slug.")
    return f"ess.{slug}.{kind_s}"


def ess_field_kind(field: str) -> str | None:
    """Return kind for Pattern B or flat plant ESS key, else None."""
    name = str(field or "").strip()
    if name in _PLANT_FLAT_ESS_FIELDS:
        return name
    match = _PATTERN_B.match(name)
    if match:
        return match.group("kind")
    return None


def is_ess_pattern_b_field(field: str) -> bool:
    return _PATTERN_B.match(str(field or "").strip()) is not None


def is_plant_flat_ess_field(field: str) -> bool:
    return str(field or "").strip() in _PLANT_FLAT_ESS_FIELDS


def parse_ess_pattern_b(field: str) -> tuple[str, str] | None:
    """Return (slug, kind) for ``ess.{slug}.{kind}``, else None."""
    match = _PATTERN_B.match(str(field or "").strip())
    if not match:
        return None
    return match.group("slug"), match.group("kind")


def expand_ess_field(field: str, battery_id: str) -> str:
    """Map flat plant ESS key → Pattern B for this battery; leave others."""
    kind = ess_field_kind(field)
    name = str(field or "").strip()
    if kind is None:
        return name
    if is_ess_pattern_b_field(name):
        return ess_field(battery_id, kind)
    if is_plant_flat_ess_field(name):
        return ess_field(battery_id, kind)
    return name


def expand_ess_bindings(
    bindings: dict | None,
    battery_id: str,
) -> dict[str, str]:
    """Rewrite flat ESS keys to Pattern B; leave non-ESS keys unchanged."""
    if not isinstance(bindings, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in bindings.items():
        address = str(value or "").strip()
        if not address:
            continue
        field = expand_ess_field(str(key), battery_id)
        if field and field not in out:
            out[field] = address
    return out


def binding_address(
    bindings: dict | None,
    battery_id: str,
    kind: str,
) -> str:
    """Address for ``ess.{slug}.{kind}`` only."""
    if not isinstance(bindings, dict):
        return ""
    return str(bindings.get(ess_field(battery_id, kind)) or "").strip()


def plant_flat_ess_keys(bindings: dict | None) -> dict[str, str]:
    """Subset of plant bindings that are flat ESS §C keys."""
    if not isinstance(bindings, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in bindings.items():
        name = str(key or "").strip()
        if name in _PLANT_FLAT_ESS_FIELDS:
            addr = str(value or "").strip()
            if addr:
                out[name] = addr
    return out

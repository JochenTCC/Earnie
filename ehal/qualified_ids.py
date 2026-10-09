"""Qualified EHAL IDs — exchange / display form ``<namespace>.<Kennung>.<field>``.

Pilot start of backlog 2.7.n-2 (spike/vo-push-pilot). The namespace names the *device
type*; where a field family has a stem the namespace equals it (``ess`` ↔ ``sens_ess_*``,
``evcs`` ↔ ``sens_evcs_*``, ``inv`` ↔ ``sens_inv_*``, ``grid`` ↔ ``sens_grid_*`` /
``*_grid_*``). Other plant house-wide fields stay bare for now (PV deferred).

Storage is unchanged: bindings stay under the keys they were saved with (``ess.{id}.*``,
legacy ``flex.{slug}.*``, bare plant/consumer fields). ``flex`` is only a legacy alias
that is still accepted on input; it is not emitted in new exchange IDs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ehal.flex_fields import flex_ehal_slug

NS_ESS = "ess"
NS_EVCS = "evcs"  # wallbox (charger)
NS_EV = "ev"  # vehicle
NS_INV = "inv"  # inverter (2.7.l P4)
NS_GRID = "grid"
NS_HEATPUMP = "heatpump"
NS_POOL = "pool"
NS_CONSUMER = "consumer"  # every other consumer

# First (and currently only) grid meter Kennung; more meters may follow.
GRID_METER_ID = "meter"

NAMESPACES: tuple[str, ...] = (
    NS_ESS,
    NS_EVCS,
    NS_EV,
    NS_INV,
    NS_GRID,
    NS_HEATPUMP,
    NS_POOL,
    NS_CONSUMER,
)
LEGACY_NAMESPACES: tuple[str, ...] = ("flex",)

# Plant binding keys that exchange as ``grid.meter.<kind>``.
GRID_KINDS: frozenset[str] = frozenset(
    {
        "sens_grid_power_active",
        "sens_grid_energy_import",
        "sens_grid_energy_export",
        "get_grid_export_power_limit",
        "set_grid_export_power_limit",
    }
)

# EV consumer field kinds: charger vs vehicle (decision 2.7.n-2; field kinds not renamed).
EVCS_KINDS = frozenset(
    {
        "sens_evcs_active_power",
        "sens_evcs_connected",
        "get_evcs_nominal_current",
        "set_evcs_max_current",
        "set_evcs_mode",
    }
)
EV_KINDS = frozenset(
    {
        "sens_evcs_soc_act",
        "sens_evcs_bat_capacity",
        "get_evcs_limit_soc",
        "get_evcs_soc_min_immediate",
        "get_evcs_ready_by_time",
    }
)

POOL_FILTER_ID = "pool_filter"


def field_kind(key: str) -> str:
    """Last dotted segment of a binding key (``flex.x.sens_power_act`` → ``sens_power_act``)."""
    return str(key or "").rsplit(".", 1)[-1]


def consumer_namespace(consumer_id: str, consumer_type: str = "", kind: str = "") -> str:
    """Namespace for a consumer entity; EV consumers split by field ``kind``."""
    ctype = str(consumer_type or "").strip()
    if ctype == "ev":
        return NS_EVCS if kind in EVCS_KINDS else NS_EV
    if ctype == "thermal_annual":
        return NS_HEATPUMP
    if ctype == "thermal_rc" or str(consumer_id or "").strip() == POOL_FILTER_ID:
        return NS_POOL
    return NS_CONSUMER


def qualified_consumer_id(consumer_id: str, consumer_type: str, key: str) -> str:
    """``<namespace>.<Kennung>.<kind>`` for a consumer binding key (any stored spelling)."""
    kind = field_kind(key)
    slug = flex_ehal_slug(consumer_id)
    return f"{consumer_namespace(consumer_id, consumer_type, kind)}.{slug}.{kind}"


def qualified_battery_id(battery_id: str, key: str) -> str:
    """``ess.<Kennung>.<kind>`` for a battery binding key (Pattern B or flat)."""
    return f"{NS_ESS}.{str(battery_id).strip()}.{field_kind(key)}"


def qualified_grid_id(key: str, *, meter_id: str = GRID_METER_ID) -> str:
    """``grid.<meter>.<kind>`` for a plant grid field (binding key or kind)."""
    mid = str(meter_id or GRID_METER_ID).strip() or GRID_METER_ID
    return f"{NS_GRID}.{mid}.{field_kind(key)}"


def qualified_plant_id(key: str) -> str:
    """Exchange ID for a plant binding key: ``grid.meter.*`` or bare house-wide."""
    kind = field_kind(key)
    if kind in GRID_KINDS:
        return qualified_grid_id(kind)
    return kind


def id_namespace_alternation(*, include_legacy: bool = True) -> str:
    names = NAMESPACES + (LEGACY_NAMESPACES if include_legacy else ())
    return "|".join(names)


# Field kinds that are 0/1 states. A Loxone output reports them only on edges
# (On = 1, Off = 0), so the last explicit value stays valid until the next edge.
DIGITAL_KINDS = frozenset(
    {
        "sens_absent_mode",
        "sens_evcs_connected",
        "sens_heating_active",
        "sens_filter_active",
        "sens_consumer_active",
    }
)


def is_digital_id(ehal_id: str) -> bool:
    return field_kind(ehal_id) in DIGITAL_KINDS


_KNOWN_NS = frozenset(NAMESPACES + LEGACY_NAMESPACES)
_KIND_RE_PART = r"(?:sens|get|set|supports)_[a-z0-9_]+"
_SLUG_RE_PART = r"[a-z0-9_]{1,64}"


@dataclass(frozen=True)
class ParsedQualifiedId:
    """Decomposed exchange / display ID.

    Plant bare fields and ``heartbeat`` have ``namespace`` / ``kennung`` = ``None``.
    Legacy ``flex.*`` is accepted (``namespace == "flex"``); builders never emit it.
    """

    namespace: str | None
    kennung: str | None
    kind: str
    raw: str

    @property
    def is_legacy_flex(self) -> bool:
        return self.namespace == "flex"

    @property
    def is_plant_bare(self) -> bool:
        return self.namespace is None


def parse_qualified_id(ehal_id: object) -> ParsedQualifiedId | None:
    """Parse a qualified or plant-bare EHAL ID; ``None`` when the shape is invalid.

    Accepted forms:
    - plant bare: ``sens_*`` / ``get_*`` / ``set_*`` / ``supports_*`` (no dots)
    - ``heartbeat`` (link proof; not a field kind)
    - ``<ns>.<Kennung>.<kind>`` for namespaces in ``NAMESPACES`` plus legacy ``flex``
    """
    raw = str(ehal_id or "").strip()
    if not raw:
        return None
    if raw == "heartbeat":
        return ParsedQualifiedId(None, None, "heartbeat", raw)
    if "." not in raw:
        if not _looks_like_kind(raw):
            return None
        return ParsedQualifiedId(None, None, raw, raw)
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    ns, kennung, kind = parts
    if ns not in _KNOWN_NS:
        return None
    if not kennung or not _looks_like_slug(kennung):
        return None
    if not _looks_like_kind(kind):
        return None
    return ParsedQualifiedId(ns, kennung, kind, raw)


def _looks_like_kind(kind: str) -> bool:
    return bool(re.fullmatch(_KIND_RE_PART, kind))


def _looks_like_slug(slug: str) -> bool:
    return bool(re.fullmatch(_SLUG_RE_PART, slug))


def format_qualified_id(parsed: ParsedQualifiedId) -> str:
    """Rebuild the exchange string (legacy ``flex`` kept as-is when present)."""
    if parsed.namespace is None:
        return parsed.kind
    return f"{parsed.namespace}.{parsed.kennung}.{parsed.kind}"

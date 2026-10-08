"""Qualified EHAL IDs — exchange / display form ``<namespace>.<Kennung>.<field>``.

Pilot start of backlog 2.7.n-2 (spike/vo-push-pilot). The namespace names the *device
type*; where a field family has a stem the namespace equals it (``ess`` ↔ ``sens_ess_*``,
``evcs`` ↔ ``sens_evcs_*``, ``inv`` ↔ ``sens_inv_*``). The plant has exactly one instance
and keeps the bare house-wide field names.

Storage is unchanged: bindings stay under the keys they were saved with (``ess.{id}.*``,
legacy ``flex.{slug}.*``, bare consumer fields). ``flex`` is only a legacy alias that is
still accepted on input; it is not emitted in new exchange IDs.
"""
from __future__ import annotations

from ehal.flex_fields import flex_ehal_slug

NS_ESS = "ess"
NS_EVCS = "evcs"  # wallbox (charger)
NS_EV = "ev"  # vehicle
NS_INV = "inv"  # inverter (2.7.l P4)
NS_HEATPUMP = "heatpump"
NS_POOL = "pool"
NS_CONSUMER = "consumer"  # every other consumer

NAMESPACES: tuple[str, ...] = (NS_ESS, NS_EVCS, NS_EV, NS_INV, NS_HEATPUMP, NS_POOL, NS_CONSUMER)
LEGACY_NAMESPACES: tuple[str, ...] = ("flex",)

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

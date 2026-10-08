"""Pattern B flex EHAL field names: ``flex.{slug}.sens_power_act`` etc.

Legacy stub keys (``flex.power_name`` / ``flex.enable_name``) expand to the
slug form. Zähler ids ``zaehler_<slug>`` use ``<slug>`` in the wire path (e.g.
``zaehler_trockner`` → ``flex.trockner.sens_power_act``).
"""

from __future__ import annotations

import re

KIND_SENS_POWER_ACT = "sens_power_act"
KIND_SENS_CONSUMER_ACTIVE = "sens_consumer_active"
KIND_SET_ENABLE = "set_enable"

_FLEX_KINDS: frozenset[str] = frozenset(
    {KIND_SENS_POWER_ACT, KIND_SENS_CONSUMER_ACTIVE, KIND_SET_ENABLE}
)

_ROLE_TO_KIND: dict[str, str] = {
    "flex.power_name": KIND_SENS_POWER_ACT,
    "flex.sens_power_act": KIND_SENS_POWER_ACT,
    "flex.sens_consumer_active": KIND_SENS_CONSUMER_ACTIVE,
    "flex.enable_name": KIND_SET_ENABLE,
    "flex.set_enable": KIND_SET_ENABLE,
}

_PATTERN_B = re.compile(
    r"^flex\.(?P<slug>[^.]+)\.(?P<kind>sens_power_act|sens_consumer_active|set_enable)$"
)

_KIND_LABELS_DE: dict[str, str] = {
    KIND_SENS_POWER_ACT: "Flex Leistung / Zustand",
    KIND_SENS_CONSUMER_ACTIVE: "Gerät läuft (Binär)",
    KIND_SET_ENABLE: "Flex Freigabe",
}


def flex_ehal_slug(consumer_id: str) -> str:
    """Wire slug for Pattern B; strip leading ``zaehler_`` when present."""
    cid = str(consumer_id or "").strip()
    if cid.startswith("zaehler_"):
        rest = cid[len("zaehler_") :]
        return rest if rest else cid
    return cid


def flex_field(consumer_id: str, kind: str) -> str:
    """Canonical binding / Live field: ``flex.{slug}.{kind}``."""
    kind_s = str(kind or "").strip()
    if kind_s not in _FLEX_KINDS:
        raise ValueError(f"Unknown flex EHAL kind '{kind_s}'.")
    slug = flex_ehal_slug(consumer_id)
    if not slug:
        raise ValueError("flex EHAL field needs a non-empty consumer id / slug.")
    return f"flex.{slug}.{kind_s}"


def flex_sens_power_act(consumer_id: str) -> str:
    return flex_field(consumer_id, KIND_SENS_POWER_ACT)


def flex_sens_consumer_active(consumer_id: str) -> str:
    return flex_field(consumer_id, KIND_SENS_CONSUMER_ACTIVE)


def flex_set_enable(consumer_id: str) -> str:
    return flex_field(consumer_id, KIND_SET_ENABLE)


def flex_fields_for_consumer(consumer_id: str) -> tuple[str, ...]:
    """HITL / Live field list for a non-EV flex consumer."""
    return (
        flex_sens_power_act(consumer_id),
        flex_sens_consumer_active(consumer_id),
        flex_set_enable(consumer_id),
    )


def flex_field_kind(field: str) -> str | None:
    """Return kind for role stub, Pattern B, or ``None``."""
    name = str(field or "").strip()
    if name in _ROLE_TO_KIND:
        return _ROLE_TO_KIND[name]
    match = _PATTERN_B.match(name)
    if match:
        return match.group("kind")
    return None


def is_flex_sens_power_act_field(field: str) -> bool:
    return flex_field_kind(field) == KIND_SENS_POWER_ACT


def is_flex_sens_consumer_active_field(field: str) -> bool:
    return flex_field_kind(field) == KIND_SENS_CONSUMER_ACTIVE


def is_flex_live_read_field(field: str) -> bool:
    """True for Live-Lesen flex power / active rows (Pattern B or legacy stub)."""
    return is_flex_sens_power_act_field(field) or is_flex_sens_consumer_active_field(
        field
    )


def flex_field_label(field: str) -> str | None:
    kind = flex_field_kind(field)
    return _KIND_LABELS_DE.get(kind) if kind else None


def expand_flex_field(field: str, consumer_id: str) -> str:
    """Map role stub / any Pattern B slug → this consumer's Pattern B key."""
    kind = flex_field_kind(field)
    if kind is None:
        return str(field or "").strip()
    return flex_field(consumer_id, kind)


def expand_flex_bindings(
    bindings: dict | None,
    consumer_id: str,
) -> dict[str, str]:
    """Rewrite flex role stubs to Pattern B; leave other keys unchanged."""
    if not isinstance(bindings, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in bindings.items():
        address = str(value or "").strip()
        if not address:
            continue
        field = expand_flex_field(str(key), consumer_id)
        if field and field not in out:
            out[field] = address
    return out


def binding_address(
    bindings: dict | None,
    consumer_id: str,
    kind: str,
) -> str:
    """Address for this consumer's Pattern B key ``flex.{slug}.{kind}`` only."""
    if not isinstance(bindings, dict):
        return ""
    return str(bindings.get(flex_field(consumer_id, kind)) or "").strip()

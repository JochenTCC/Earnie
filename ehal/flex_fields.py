"""Consumer EHAL binding keys: storage uses typed namespaces; ``flex.*`` is legacy.

Role stubs (``flex.power_name`` / ``flex.enable_name`` / ``flex.sens_power_act``)
and legacy entity-scoped ``flex.{slug}.{kind}`` expand to
``consumer|heatpump|pool.{slug}.{kind}`` via :func:`canonicalize_consumer_bindings`.
Zähler ids ``zaehler_<slug>`` use ``<slug>`` as Kennung.
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

_ENTITY_SCOPED = re.compile(
    r"^flex\.(?P<slug>[^.]+)\.(?P<kind>sens_power_act|sens_consumer_active|set_enable)$"
)

_TYPED_CONSUMER_NS = frozenset({"consumer", "heatpump", "pool", "flex"})

_KIND_LABELS_DE: dict[str, str] = {
    KIND_SENS_POWER_ACT: "Flex Leistung / Zustand",
    KIND_SENS_CONSUMER_ACTIVE: "Gerät läuft (Binär)",
    KIND_SET_ENABLE: "Flex Freigabe",
}


def flex_ehal_slug(consumer_id: str) -> str:
    """Wire slug for entity-scoped; strip leading ``zaehler_`` when present."""
    cid = str(consumer_id or "").strip()
    if cid.startswith("zaehler_"):
        rest = cid[len("zaehler_") :]
        return rest if rest else cid
    return cid


def flex_field(consumer_id: str, kind: str) -> str:
    """Legacy storage key ``flex.{slug}.{kind}`` (parse / dual-read only)."""
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


def consumer_storage_field(
    consumer_id: str, consumer_type: str, kind: str
) -> str:
    """Canonical storage key: ``consumer|heatpump|pool.{slug}.{kind}``."""
    from ehal.qualified_ids import qualified_consumer_id

    kind_s = str(kind or "").strip()
    if kind_s not in _FLEX_KINDS:
        raise ValueError(f"Unknown consumer EHAL kind '{kind_s}'.")
    return qualified_consumer_id(consumer_id, consumer_type, kind_s)


def consumer_fields_for_consumer(
    consumer_id: str, consumer_type: str = ""
) -> tuple[str, ...]:
    """HITL / mapping field list for a non-EV flex consumer (typed storage keys)."""
    return (
        consumer_storage_field(consumer_id, consumer_type, KIND_SENS_POWER_ACT),
        consumer_storage_field(consumer_id, consumer_type, KIND_SENS_CONSUMER_ACTIVE),
        consumer_storage_field(consumer_id, consumer_type, KIND_SET_ENABLE),
    )


def flex_fields_for_consumer(consumer_id: str) -> tuple[str, ...]:
    """Legacy alias — prefer :func:`consumer_fields_for_consumer` with type."""
    return consumer_fields_for_consumer(consumer_id, "")


def flex_field_kind(field: str) -> str | None:
    """Return kind for role stub, ``flex.*``, typed consumer key, or ``None``."""
    name = str(field or "").strip()
    if name in _ROLE_TO_KIND:
        return _ROLE_TO_KIND[name]
    match = _ENTITY_SCOPED.match(name)
    if match:
        return match.group("kind")
    from ehal.qualified_ids import parse_qualified_id

    parsed = parse_qualified_id(name)
    if (
        parsed
        and parsed.namespace in _TYPED_CONSUMER_NS
        and parsed.kind in _FLEX_KINDS
    ):
        return parsed.kind
    return None


def is_flex_sens_power_act_field(field: str) -> bool:
    return flex_field_kind(field) == KIND_SENS_POWER_ACT


def is_flex_sens_consumer_active_field(field: str) -> bool:
    return flex_field_kind(field) == KIND_SENS_CONSUMER_ACTIVE


def is_flex_live_read_field(field: str) -> bool:
    """True for Live-Lesen flex power / active rows (entity-scoped or legacy stub)."""
    return is_flex_sens_power_act_field(field) or is_flex_sens_consumer_active_field(
        field
    )


def flex_field_label(field: str) -> str | None:
    kind = flex_field_kind(field)
    return _KIND_LABELS_DE.get(kind) if kind else None


def canonicalize_consumer_field(
    field: str, consumer_id: str, consumer_type: str = ""
) -> str:
    """Map role stub / flex.* / typed flex-kind key → typed storage key."""
    kind = flex_field_kind(field)
    if kind is None:
        return str(field or "").strip()
    return consumer_storage_field(consumer_id, consumer_type, kind)


def canonicalize_consumer_bindings(
    bindings: dict | None,
    consumer_id: str,
    consumer_type: str = "",
) -> dict[str, str]:
    """Rewrite flex stubs / ``flex.*`` to typed namespaces; leave other keys.

    Empty string values are kept as Loxone activation flags (2.7.q Q8).
    First-writer wins when two keys canonicalize to the same field.
    """
    if not isinstance(bindings, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in bindings.items():
        field = canonicalize_consumer_field(str(key), consumer_id, consumer_type)
        if not field or field in out:
            continue
        out[field] = str(value or "").strip()
    return out


def expand_flex_field(field: str, consumer_id: str) -> str:
    """Map role stub / flex.* → typed storage (generic ``consumer`` namespace)."""
    return canonicalize_consumer_field(field, consumer_id, "")


def expand_flex_bindings(
    bindings: dict | None,
    consumer_id: str,
    consumer_type: str = "",
) -> dict[str, str]:
    """Rewrite flex role stubs to typed storage keys.

    Prefer :func:`canonicalize_consumer_bindings` with an explicit consumer type.
    """
    return canonicalize_consumer_bindings(bindings, consumer_id, consumer_type)


def binding_address(
    bindings: dict | None,
    consumer_id: str,
    kind: str,
    *,
    consumer_type: str = "",
) -> str:
    """Address for typed storage key, falling back to legacy ``flex.{slug}.{kind}``."""
    if not isinstance(bindings, dict):
        return ""
    kind_s = str(kind or "").strip()
    if kind_s not in _FLEX_KINDS:
        return str(bindings.get(kind_s) or "").strip()
    typed = consumer_storage_field(consumer_id, consumer_type, kind_s)
    if typed in bindings:
        return str(bindings.get(typed) or "").strip()
    # Type unknown: any typed namespace with this Kennung + kind.
    if not str(consumer_type or "").strip():
        slug = flex_ehal_slug(consumer_id)
        for ns in ("consumer", "heatpump", "pool"):
            key = f"{ns}.{slug}.{kind_s}"
            if key in bindings:
                return str(bindings.get(key) or "").strip()
    legacy = flex_field(consumer_id, kind_s)
    return str(bindings.get(legacy) or "").strip()

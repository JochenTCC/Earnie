"""Per-consumer power on the HA backend for the slot log (Ledger P9e, plan savings-ledger-v2-plan.md § 3.1).

On Loxone the power sampler logs each measured consumer's power (``closed_interval.flex_kw``);
on network backends it logged none, so every consumer fell under D6 (logged timing) in the
savings ledger. This reader gives the HA backend the same: measured consumers only, from the
push inbox.

Per flex consumer, the first that applies:

- an EV: its wallbox's ``sens_evcs_active_power``;
- ``sens_power_act`` when bound;
- a consumer without power setpoint (on/off): ``sens_consumer_active`` × nominal power.

Units: the HA carrier pushes a field with an EHAL quantity in its canonical unit
(``ehal_base_unit``: ``sens_evcs_active_power`` and ``sens_power_act`` in W, converted from the
entity's W / kW / MW), converted here to kW. A carrier package generated before
``sens_power_act`` had a unit pushes the entity's number as it is: generate it again.

A value counts only when it was measured: inbox state ``OK`` or an explicitly pushed 0
(``0 (gehalten)``), and for the digital run state also the held edge (``Digital (gehalten)``).
A missing, stale, last-known or assumed-zero value gives **no key**, never 0, so the ledger
treats the consumer as not metered (D6) instead of as idle. Two consumers that resolve to the
same push signal (one wallbox for two EVs) cannot be told apart and get no key either.

Scope: the slot log and Chart 1 "Ist". The planning snapshot and ``cons_data`` take only the
heating rods from here (``read_ha_heating_rod_kw_live``): the rod has no demand of its own, so
its power must leave the base load like on Loxone. Every other consumer keeps zero power there
on network backends.
"""
from __future__ import annotations

import logging
from typing import Callable

from ehal.push_signals import pilot_id
from ehal.qualified_ids import field_kind
from integrations.ha_carrier_yaml import ehal_base_unit
from integrations.ha_units import from_ehal
from optimizer.consumer_power import uses_power_setpoint
from runtime_store.ehal_push_inbox import (
    STATE_DIGITAL_HELD,
    STATE_OK,
    STATE_ZERO_HELD,
)

logger = logging.getLogger(__name__)

KIND_POWER = "sens_power_act"
KIND_ACTIVE = "sens_consumer_active"
KIND_EVCS_POWER = "sens_evcs_active_power"

MEASURED_POWER_STATES = frozenset({STATE_OK, STATE_ZERO_HELD})
MEASURED_DIGITAL_STATES = MEASURED_POWER_STATES | {STATE_DIGITAL_HELD}

ReadValue = Callable[[str], "tuple[float | None, str]"]
ApplySign = Callable[[float, str], float]


def _is_ev(consumer: dict) -> bool:
    schedule = consumer.get("charging_schedule") or {}
    return consumer.get("type") == "ev" or bool(schedule.get("enabled"))


def pushed_power_kw(value: float, qid: str) -> float:
    """Pushed power of ``qid`` in kW: from its EHAL base unit, or as is without one."""
    if ehal_base_unit(qid) is None:
        return value
    return from_ehal(field_kind(qid), value, "kW")


def _binding_qid(consumer: dict, kind: str) -> tuple[str, str] | None:
    """``(binding_key, push_qid)`` of the consumer's binding of ``kind``, as the push contract names it."""
    cid = str(consumer.get("id") or "").strip()
    ctype = str(consumer.get("type") or "")
    for key in consumer.get("ehal_bindings") or {}:
        if field_kind(str(key)) != kind:
            continue
        qid = pilot_id("consumer", cid, str(key), ctype)
        if qid:
            return str(key), str(qid)
    return None


def _source(consumer: dict) -> tuple[str, str, str] | None:
    """``(kind, binding_key, qid)`` the consumer's power is read from, or ``None`` without one."""
    if _is_ev(consumer):
        found = _binding_qid(consumer, KIND_EVCS_POWER)
        return (KIND_EVCS_POWER, *found) if found else None
    found = _binding_qid(consumer, KIND_POWER)
    if found:
        return (KIND_POWER, *found)
    if not uses_power_setpoint(consumer):
        found = _binding_qid(consumer, KIND_ACTIVE)
        if found:
            return (KIND_ACTIVE, *found)
    return None


def read_ha_flex_chart_kw(
    consumers: list[dict],
    *,
    read_value: ReadValue,
    apply_sign: ApplySign,
) -> dict[str, float]:
    """kW per measured consumer (``closed_interval.flex_kw`` sample); see the module docstring.

    ``read_value(qid)`` returns ``(value, inbox state)`` (``ehal_push_inbox.read_push_value``);
    ``apply_sign(value, binding_key)`` applies ``ehal.ha.sign`` like the plant reads.
    """
    sources: dict[str, tuple[str, str, str]] = {}
    for consumer in consumers:
        source = _source(consumer)
        if source is not None:
            sources[str(consumer["id"])] = source
    by_qid: dict[str, list[str]] = {}
    for cid, (_kind, _key, qid) in sources.items():
        by_qid.setdefault(qid, []).append(cid)
    shared = {qid: cids for qid, cids in by_qid.items() if len(cids) > 1}
    if shared:
        logger.warning(
            "HA consumer power: %s share one push signal; they get no power in the slot log.",
            "; ".join(f"{qid}: {', '.join(cids)}" for qid, cids in sorted(shared.items())),
        )
    by_id = {str(c["id"]): c for c in consumers}
    out: dict[str, float] = {}
    for cid, (kind, key, qid) in sources.items():
        if qid in shared:
            continue
        value, state = read_value(qid)
        if value is None:
            continue
        if kind == KIND_ACTIVE:
            if state not in MEASURED_DIGITAL_STATES:
                continue
            out[cid] = round(float(by_id[cid]["nominal_power_kw"]) if float(value) >= 0.5 else 0.0, 3)
            continue
        if state not in MEASURED_POWER_STATES:
            continue
        out[cid] = round(pushed_power_kw(apply_sign(float(value), key), qid), 3)
    return out


def _live_readers() -> tuple[ReadValue, ApplySign]:
    """The push inbox and the adapter's sign map (``ehal.ha.sign``)."""
    from integrations.ehal_live import get_ha_adapter
    from integrations.ha_push_read import apply_push_sign
    from runtime_store.ehal_push_inbox import read_push_value

    sign = dict(getattr(get_ha_adapter().cfg, "sign", {}) or {})
    return read_push_value, lambda value, key: apply_push_sign(value, sign=sign, adapter_field=key)


def read_ha_flex_chart_kw_live() -> dict[str, float]:
    """``read_ha_flex_chart_kw`` with the configured consumers, the push inbox and the adapter's sign map."""
    import config

    read_value, apply_sign = _live_readers()
    return read_ha_flex_chart_kw(
        config.get_flexible_consumers(), read_value=read_value, apply_sign=apply_sign
    )


def read_ha_heating_rod_kw(
    consumers: list[dict],
    *,
    read_value: ReadValue,
    apply_sign: ApplySign,
) -> dict[str, float]:
    """kW of every measured heating rod among ``consumers`` (``read_ha_flex_chart_kw`` rules).

    A rod with a power or run-state binding but no measured value gets no key and a warning:
    its power then stays in the base load, as before this reader existed.
    """
    from optimizer.thermal_flex_context import is_heating_rod_consumer

    rods = [consumer for consumer in consumers if is_heating_rod_consumer(consumer)]
    if not rods:
        return {}
    out = read_ha_flex_chart_kw(rods, read_value=read_value, apply_sign=apply_sign)
    for rod in rods:
        rid = str(rod["id"])
        if rid not in out and _source(rod) is not None:
            logger.warning(
                "HA: keine gemessene Leistung für Heizstab '%s' — seine Leistung bleibt in der "
                "Grundlast.",
                rid,
            )
    return out


def read_ha_heating_rod_kw_live(consumers: list[dict]) -> dict[str, float]:
    """``read_ha_heating_rod_kw`` with the push inbox and the adapter's sign map."""
    read_value, apply_sign = _live_readers()
    return read_ha_heating_rod_kw(consumers, read_value=read_value, apply_sign=apply_sign)

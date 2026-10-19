"""Entity-scoped ``get_ess_*`` enrichment for live ESS / powerstation limits (2.7.j).

``read_telemetry`` only stores plant-flat gets for the primary house battery.
Standby packs require ``ess.{id}.get_ess_*`` — read those the same way as SoC.
"""
from __future__ import annotations

import logging
from typing import Any

from integrations.ehal_live_ref import live
from integrations.loxone_adapter import LoxoneAdapterError
from integrations.ha_adapter import HaHttpError
from integrations.openems_adapter import OpenemsHttpError

logger = logging.getLogger("integrations.ehal_live")

_LIMIT_KINDS: tuple[str, ...] = (
    "get_ess_soc_min",
    "get_ess_soc_max",
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)


def enrich_telemetry_with_ess_live_limits(
    telemetry: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge entity-scoped live gets for batteries with ``limits_from_live``."""
    out: dict[str, Any] = dict(telemetry) if isinstance(telemetry, dict) else {}
    for bat in _batteries_needing_live_limits():
        ess_id = str(bat.get("id") or "").strip()
        if not ess_id:
            continue
        for kind in _LIMIT_KINDS:
            from ehal.ess_fields import ess_field

            qid = ess_field(ess_id, kind)
            if qid in out:
                continue
            value = _read_limit_for_battery(bat, kind)
            if value is not None:
                out[qid] = float(value)
    return out


def _batteries_needing_live_limits() -> list[dict]:
    from house_config.ess_bindings import mappable_batteries

    return [
        bat
        for bat in mappable_batteries()
        if isinstance(bat, dict) and bool(bat.get("limits_from_live", False))
    ]


def _read_limit_for_battery(bat: dict, kind: str) -> float | None:
    from house_config.ess_bindings import resolve_battery_ess_binding

    address = resolve_battery_ess_binding(bat, kind)
    if not address:
        return None
    return _read_limit_from_address(address, kind)


def _read_limit_from_address(address: str, kind: str) -> float | None:
    addr = str(address or "").strip()
    if not addr:
        return None
    try:
        if live.is_openems_backend():
            return None
        if live.is_ha_backend():
            from integrations.ha_push_read import PushReadError, read_push_ehal_value

            try:
                adapter = live.get_ha_adapter()
                sign = dict(getattr(adapter.cfg, "sign", {}) or {})
                return float(
                    read_push_ehal_value(addr, sign=sign, adapter_field=addr)
                )
            except PushReadError:
                return None
        if live.is_loxone_backend() or not live.is_ehal_network_backend():
            from ehal.field_registry import apply_loxone_read, loxone_spec

            raw = live.loxone_client.fetch_loxone_generic_value(addr)
            spec = loxone_spec(kind)
            if spec is not None:
                return apply_loxone_read(raw, spec)
            return None if raw is None else float(raw)
    except (
        OpenemsHttpError,
        HaHttpError,
        LoxoneAdapterError,
        TypeError,
        ValueError,
        OSError,
        KeyError,
    ) as exc:
        logger.debug("Per-ESS limit read failed for %s: %s", addr, exc)
        return None
    return None

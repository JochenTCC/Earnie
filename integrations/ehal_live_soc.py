"""Per-ESS SoC reads (split from ``ehal_live``).

Late-bound through ``integrations.ehal_live`` (``live``) so patches applied to
the façade (``config``, adapters, backend checks, ...) stay effective.
"""
from __future__ import annotations

import logging

from integrations.ehal_live_ref import live
from integrations.loxone_adapter import LoxoneAdapterError
from integrations.ha_adapter import HaHttpError
from integrations.openems_adapter import OpenemsHttpError

# Keep the historic logger name so log filters keep working after the split.
logger = logging.getLogger("integrations.ehal_live")


def read_ess_soc() -> float | None:
    """Primary house-battery SoC (%) via entity-scoped path only."""
    from house_config.powerstation import primary_house_battery

    try:
        by_id = live.read_ess_soc_by_id()
    except (
        OpenemsHttpError,
        HaHttpError,
        LoxoneAdapterError,
        ValueError,
        OSError,
    ) as exc:
        logger.error("EHAL SoC read failed: %s", exc)
        return None
    batteries = live._mappable_batteries_for_soc()
    primary = primary_house_battery(batteries)
    primary_id = str((primary or {}).get("id") or "").strip()
    if primary_id and primary_id in by_id:
        return float(by_id[primary_id])
    if by_id:
        # Single mapped SoC when primary id is unknown / empty
        return float(next(iter(by_id.values())))
    if primary_id:
        logger.error(
            "EHAL SoC read failed: missing ess.%s.sens_ess_soc for primary "
            "battery (map SoC on that battery in EHAL-Com / "
            "batteries[].ehal_bindings, or ensure Live delivers it)",
            primary_id,
        )
    else:
        logger.error(
            "EHAL SoC read failed: no primary house battery id and no "
            "ess.*.sens_ess_soc values available"
        )
    return None


def _soc_address_for_battery(bat: dict) -> str:
    """Resolve SoC read key: Loxone uses qualified ID; HA uses binding address."""
    from ehal.ess_fields import binding_address
    from ehal.qualified_ids import qualified_battery_id

    ess_id = str(bat.get("id") or "").strip()
    if not ess_id:
        return ""
    if live.is_loxone_backend() or not live.is_ehal_network_backend():
        return qualified_battery_id(ess_id, "sens_ess_soc")
    if live.is_openems_backend():
        bindings = bat.get("ehal_bindings")
        if isinstance(bindings, dict):
            addr = binding_address(bindings, ess_id, "sens_ess_soc")
            if addr:
                return addr
        # Primary OpenEMS channel from adapter config (no plant telemetry key).
        from house_config.powerstation import primary_house_battery

        primary = primary_house_battery(live._mappable_batteries_for_soc())
        if primary and str(primary.get("id") or "").strip() == ess_id:
            adapter = live.get_openems_adapter()
            return f"{adapter.cfg.ess_component}/Soc"
        return ""
    if live.is_ha_backend():
        # Binding P5e: push-only — address is the qualified EHAL id.
        return qualified_battery_id(ess_id, "sens_ess_soc")
    bindings = bat.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return ""
    return str(binding_address(bindings, ess_id, "sens_ess_soc") or "").strip()


def _read_soc_from_address(address: str) -> float | None:
    addr = str(address or "").strip()
    if not addr:
        return None
    try:
        if live.is_openems_backend():
            parts = live._openems_channel_parts(addr)
            if parts is None:
                return None
            component, channel = parts
            adapter = live.get_openems_adapter()
            raw = adapter.read_channel(component, channel)
            if raw is None and channel == "Soc":
                raw = adapter.read_channel("_sum", "EssSoc")
            return None if raw is None else float(raw)
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
            spec = loxone_spec("sens_ess_soc")
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
        logger.debug("Per-ESS SoC read failed for %s: %s", addr, exc)
        return None
    return None


def _mappable_batteries_for_soc() -> list[dict]:
    """House + physical PS from components; fallback to planning battery list."""
    try:
        from house_config.components_store import load_components_document
        from house_config.powerstation import ehal_mappable_batteries
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if path:
            doc = load_components_document(path)
            raw = doc.get("batteries") if isinstance(doc, dict) else []
            mapped = ehal_mappable_batteries(raw if isinstance(raw, list) else [])
            if mapped:
                return mapped
    except Exception as exc:  # noqa: BLE001
        logger.debug("SoC battery list from components failed: %s", exc)
    get_list = getattr(live.config, "get_battery_params_list", None)
    batteries = get_list() if callable(get_list) else []
    return [b for b in (batteries or []) if isinstance(b, dict)]


def _warn_soc_missing_once(ess_id: str) -> None:
    if ess_id in live._soc_missing_warned:
        return
    live._soc_missing_warned.add(ess_id)
    logger.warning(
        "ESS SoC missing for %s — refuse planning (no primary SoC fallback)",
        ess_id,
    )


def filter_planning_batteries_with_soc(
    battery_params: list | dict,
    current_soc_by_id: dict[str, float] | None,
) -> list | dict:
    """Drop multi-ESS house batteries without an own SoC from this cycle's plan."""
    if not isinstance(battery_params, list):
        return battery_params
    soc_map = current_soc_by_id or {}
    kept: list[dict] = []
    for bat in battery_params:
        if not isinstance(bat, dict):
            continue
        ess_id = str(bat.get("id") or "").strip()
        if ess_id and ess_id not in soc_map:
            logger.warning(
                "Dropping ESS %s from this cycle — no own SoC",
                ess_id,
            )
            continue
        kept.append(bat)
    return kept if kept else battery_params


def read_ess_soc_by_id() -> dict[str, float]:
    """SoC (%) per mappable battery id; omit when own SoC missing.

    Each battery needs its own ``ess.{{id}}.sens_ess_soc`` (or OpenEMS primary
    channel for the primary house battery). No plant-flat SoC alias.
    """
    batteries = live._mappable_batteries_for_soc()
    out: dict[str, float] = {}
    for bat in batteries:
        ess_id = str(bat.get("id") or "").strip()
        if not ess_id:
            continue
        soc = live._read_soc_from_address(live._soc_address_for_battery(bat))
        if soc is None:
            live._warn_soc_missing_once(ess_id)
            continue
        out[ess_id] = float(soc)
    return out

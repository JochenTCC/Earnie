"""Safe setpoint push at daemon start (split from ``ehal_live``).

Late-bound through ``integrations.ehal_live`` (``live``) so patches applied to the
façade (``config``, write functions, backend checks, ...) stay effective.
"""
from __future__ import annotations

import logging
from typing import Any

from integrations.ehal_live_ref import live

# Keep the historic logger name so log filters keep working after the split.
logger = logging.getLogger("integrations.ehal_live")


def push_safe_setpoints_on_startup() -> None:
    """Force-write safe ESS/flex setpoints once at daemon start (before first optimize).

    Does not update ``optimizer_run_state`` / ``loxone_sent``. Soft-fail: log only.
    Skip via ``EARNIE_SKIP_SAFE_SETPOINTS_ON_START=1`` or silent mode.
    """
    from runtime_store.env_vars import is_truthy

    if is_truthy("SKIP_SAFE_SETPOINTS_ON_START"):
        logger.info(
            "Safe setpoint startup push skipped (EARNIE_SKIP_SAFE_SETPOINTS_ON_START)."
        )
        return
    if live.config.is_loxone_silent_mode():
        logger.info("Silent-Modus: Safe setpoint startup push übersprungen.")
        return
    try:
        if live.is_ehal_network_backend():
            live._push_safe_setpoints_network()
        else:
            live._push_safe_setpoints_loxone()
    except Exception:
        # main.py does not log fatal startup errors; without this the daemon dies
        # with the traceback only on stderr and ``earnie.log`` just stops.
        logger.exception("Startup: sichere Sollwerte fehlgeschlagen — main.py bricht ab.")
        raise


def _push_safe_setpoints_network() -> None:
    backend = "HA" if live.is_ha_backend() else "OpenEMS"
    logger.info(
        "Startup: sende sichere EHAL-Sollwerte (ESS Automatik, EVCS 0 A) an %s...",
        backend,
    )
    err_ess: Any = None
    try:
        telemetry = live._startup_ess_limit_telemetry(live.config.get_battery_params())
    except StartupEssLimitsMissing as exc:
        logger.error("Startup: ESS-Sollwerte an %s nicht gesendet: %s", backend, exc)
        err_ess = {"message": str(exc)}
    else:
        if telemetry is None:
            err_ess, _ess_records = live.write_ess_setpoints_from_control(0, 0.0)
        else:
            err_ess, _ess_records = live.write_ess_setpoints_from_control(
                0, 0.0, telemetry=telemetry
            )
    err_evcs, _evcs_records = live.write_evcs_max_current_from_consumers({})
    err_inv, _inv_records = live.write_inv_ac_limits_from_plan(plant_curtail_kw=0.0)
    if err_ess is None and err_evcs is None and err_inv is None:
        live.clear_write_error()
        logger.info("Startup: sichere EHAL-Sollwerte an %s gesendet.", backend)
        return
    parts: list[str] = []
    if err_ess is not None:
        parts.append(str(err_ess.get("message") or "ESS"))
    if err_evcs is not None:
        parts.append(str(err_evcs.get("message") or "EVCS"))
    if err_inv is not None:
        parts.append(str(err_inv.get("message") or "INV"))
    logger.error(
        "Startup: sichere EHAL-Sollwerte an %s teilweise fehlgeschlagen: %s",
        backend,
        "; ".join(parts),
    )


def _push_safe_setpoints_loxone() -> None:
    logger.info(
        "Startup: sende sichere Loxone-Sollwerte "
        "(ESS Automatik, Freigabe/Sollwerte aus)..."
    )
    # Automatik target SoC is 99 like the optimizer's Automatik; 0 would ask the
    # inverter to discharge to empty where it honours set_ess_target_soc.
    battery_params = live.config.get_battery_params()
    ess_failed = 0
    try:
        telemetry = live._startup_ess_limit_telemetry(battery_params)
    except StartupEssLimitsMissing as exc:
        logger.error("Startup: ESS-Sollwerte an Loxone nicht gesendet: %s", exc)
        huawei = []
        ess_failed = 1
    else:
        if telemetry is None:
            huawei = live.write_huawei_modbus_states(0, 0.0, 99.0)
        else:
            from settings.ess_limits_resolve import apply_effective_ess_limits

            huawei = live.write_huawei_modbus_states(
                0,
                0.0,
                99.0,
                battery_params=apply_effective_ess_limits(
                    battery_params, telemetry=telemetry
                ),
            )
    # Startup: no plan yet, so the store charge target is 0 (no target, HeatControl P3).
    flex = live.write_flexible_consumer_states({}, None, None, heat_storage_targets={})
    _inv_err, inv_rows = live.write_inv_ac_limits_from_plan(plant_curtail_kw=0.0)
    failed = [
        row
        for row in (huawei + flex)
        if not getattr(row, "success", True)
    ]
    failed_inv = [row for row in inv_rows if not row.get("success")]
    if not failed and not failed_inv and not ess_failed:
        logger.info("Startup: sichere Loxone-Sollwerte gesendet.")
        return
    logger.error(
        "Startup: sichere Loxone-Sollwerte teilweise fehlgeschlagen (%s Feld(er)).",
        len(failed) + len(failed_inv) + ess_failed,
    )


class StartupEssLimitsMissing(RuntimeError):
    """The battery takes its limits from live values, but none are readable at startup."""


_STARTUP_LIVE_POWER_KINDS: tuple[str, ...] = (
    "get_ess_max_charge_power",
    "get_ess_max_discharge_power",
)


def _missing_live_power_limits(
    telemetry: dict[str, Any] | None, ess_id: str | None
) -> list[str]:
    from settings.ess_limits_resolve import _telemetry_power_kw, telemetry_for_ess

    tel = telemetry_for_ess(telemetry, ess_id)
    return [
        kind
        for kind in _STARTUP_LIVE_POWER_KINDS
        if _telemetry_power_kw(tel, kind) is None
    ]


def _startup_ess_limit_telemetry(battery_params: dict) -> dict[str, Any] | None:
    """Live ``get_ess_max_*`` for the startup push, like the cycle reads them.

    ``None`` when the battery does not use ``limits_from_live`` (the HK limits apply).
    Raises ``StartupEssLimitsMissing`` when a live power limit is not readable: the
    startup push must not release more than the inverter allows (no HK fallback).
    """
    if not bool(battery_params.get("limits_from_live", False)):
        return None
    ess_id = str(battery_params.get("id") or "").strip() or None
    telemetry = live.enrich_telemetry_with_ess_live_limits(None)
    if not live._missing_live_power_limits(telemetry, ess_id):
        return telemetry
    # Plant-flat get_ess_max_* (no entity-scoped binding) come only with the full read.
    try:
        telemetry = live.enrich_telemetry_with_ess_live_limits(
            live.get_adapter().read_telemetry()
        )
    except Exception as exc:  # noqa: BLE001 — reported as missing live limits below
        raise StartupEssLimitsMissing(
            f"Live-Limits der Batterie {ess_id or '?'} nicht lesbar ({exc})"
        ) from exc
    missing = live._missing_live_power_limits(telemetry, ess_id)
    if missing:
        raise StartupEssLimitsMissing(
            f"Live-Limits der Batterie {ess_id or '?'} fehlen: {', '.join(missing)}"
        )
    return telemetry

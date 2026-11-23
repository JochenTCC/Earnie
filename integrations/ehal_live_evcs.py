"""EV charger and HA flex-enable writes (split from ``ehal_live``).

Late-bound through ``integrations.ehal_live`` (``live``) so patches applied to the
façade (``config``, adapters, backend checks, ``live_ev_consumers``, ...) stay effective.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ehal import EHAL_SCHEMA_VERSION, EhalWriteError
from integrations.ehal_live_ref import live

# Keep the historic logger name so log filters keep working after the split.
logger = logging.getLogger("integrations.ehal_live")


def write_flex_enables_for_ha(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
    *,
    heat_storage_targets: dict[str, float] | None = None,
    heat_forced_charge: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Publish the flex ``set_enable`` (heat pump, pool, generic) for the HA backend,
    plus the heat pump's SG-Ready state and store charge target (HeatControl P2/P3).

    Returns ``optimizer_run_state.ehal_writes`` rows. The EV current is not part of this
    (``write_evcs_max_current_from_consumers`` writes it).
    """
    records = live.write_flexible_consumer_enables(
        consumer_powers,
        charging_contexts,
        consumer_pv_follow,
        heat_storage_targets=heat_storage_targets,
        heat_forced_charge=heat_forced_charge,
    )
    return [
        {
            "field": record.io_name,
            "value": record.value,
            "success": record.success,
            "written_at": record.written_at,
            "message": "" if record.success else "EHAL publish rejected",
        }
        for record in records
    ]


def write_evcs_max_current_from_consumers(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> tuple[EhalWriteError | None, list[dict[str, Any]]]:
    """Write ``set_evcs_max_current`` (kW→A) for every EV ↔ wallbox pair (multi-EV M2).

    The kW follow the same rule as the Loxone path (``loxone_control_outputs``): 0 or
    [min_power_kw, nominal], P_max with PV follow.
    One adapter call per charger (``evcs.<Kennung>.*``) with the pair's voltage and phases:
    a failing charger does not stop the others. HA backend: also ``set_evcs_mode``
    (skipped by the adapter when not activated). With "Sofort laden" only the mode ``now``
    goes out and no current, as on the Loxone path. Returns the first write error and the
    trace rows of all chargers (fields ``evcs.<Kennung>.set_evcs_*``).
    """
    from ehal.qualified_ids import charger_id_of_ev, qualified_charger_id

    consumers = live.live_ev_consumers()
    if not consumers:
        logger.info("EHAL: no EV consumer configured — skip EVCS write")
        return None, []
    adapter = live.get_network_adapter()
    if not adapter.capabilities()["supports_evcs_current"]:
        logger.info("EHAL: supports_evcs_current=false — skip EVCS write")
        return None, []
    first_error: EhalWriteError | None = None
    records: list[dict[str, Any]] = []
    for consumer in consumers:
        charger_id = charger_id_of_ev(consumer)
        error, written, ts = live._write_one_charger(
            adapter, consumer, charger_id, consumer_powers, charging_contexts, consumer_pv_follow
        )
        if error is not None:
            live.persist_write_error(error)
            first_error = first_error or error
        rows = live.build_ehal_write_records(
            written,
            written_at=ts,
            error=error,
            skipped=live._last_skipped(adapter),
            unconfigured=live._last_unconfigured(adapter),
        )
        for row in rows:
            row["field"] = qualified_charger_id(charger_id, row["field"])
        records.extend(rows)
    return first_error, records


def live_ev_consumers() -> list[dict]:
    """Live EV consumers as pairs with their wallbox (pair view, multi-EV M2).

    Dynamic EVs appear only while assigned, with ``charger_id`` = their wallbox (M3); the pool
    view of a dynamic EV that is not assigned has no charger and is left out (M4).
    """
    from house_config.wallboxes import is_pool_ev

    return [
        c
        for c in live.config.get_flexible_consumers()
        if c.get("type") == "ev" and not is_pool_ev(c)
    ]


def live_charger_consumers() -> list[dict]:
    """Every charger the adapters address (``evcs.<Wallbox>.*``): the wallboxes of the fixed
    pairs (M4) and every wallbox open to dynamic EVs (multi-EV M3), assigned or not.
    """
    from house_config.wallboxes import is_dynamic_ev
    from integrations.ev_assignment_live import dynamic_charger_consumers

    fixed = [c for c in live.live_ev_consumers() if not is_dynamic_ev(c)]
    return fixed + dynamic_charger_consumers()


def _write_one_charger(
    adapter: Any,
    consumer: dict,
    charger_id: str,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None,
    consumer_pv_follow: dict[str, int] | None,
) -> tuple[EhalWriteError | None, dict[str, Any], str]:
    from integrations.loxone_writes import _effective_consumer_power_kw
    from optimizer.consumer_power import loxone_control_outputs

    cid = consumer["id"]
    contexts = charging_contexts or {}
    ctx = contexts.get(cid)
    # Same rule as the Loxone path (``flex_consumer_power_setpoint_kw``): inactive, or
    # anticipated but not plugged in → 0 kW; otherwise 0 or [min_power_kw, nominal], and
    # with PV follow P_max so the hub follows the surplus instead of the plan average.
    planned_kw = _effective_consumer_power_kw(consumer, consumer_powers, contexts, cid)
    plan_pv = int((consumer_pv_follow or {}).get(cid, 0) or 0)
    setpoint_kw, pv_out = loxone_control_outputs(consumer, planned_kw, plan_pv)
    # The pair view carries the wallbox voltage and the pair's phases.
    voltage_v, phases = live.ev_nominal_power_conversion(consumer)
    amps_out = round(live.kw_to_ampere(setpoint_kw, voltage_v=voltage_v, phases=phases), 3)
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    written: dict[str, Any] = {}
    immediate = live.is_ha_backend() and bool((ctx or {}).get("skip_loxone_output"))
    if not immediate:
        written["set_evcs_max_current"] = amps_out
    if live.is_ha_backend():
        written["set_evcs_mode"] = live._evcs_mode_for_cycle(pv_out, amps_out, immediate)
    setpoint = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter.cfg.adapter_id,
        **written,
    }
    error = adapter.write_evcs_setpoints(
        charger_id, setpoint, voltage_v=voltage_v, phases=phases
    )
    return error, written, ts


def _evcs_mode_for_cycle(pv_follow_out: int, amps: float, immediate: bool) -> str:
    """Mode matching the current written this cycle.

    ``pv_follow_out`` and ``amps`` come from the same ``loxone_control_outputs`` call, so
    mode ``pv`` always goes with the P_max current and ``now`` with the clamped plan current.
    """
    from optimizer.consumer_power import set_evcs_mode_for_plan

    return set_evcs_mode_for_plan(
        pv_follow=int(pv_follow_out), immediate=immediate, charging=amps > 1e-6
    )

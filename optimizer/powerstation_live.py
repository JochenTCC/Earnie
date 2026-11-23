"""Live-cycle hooks for 2.7.g powerstation reserves and 2.7.h standby-backup."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

import config
from house_config.powerstation import BACKING_VIRTUAL, MODE_RESERVE
from optimizer.powerstation_reserve import (
    _group_reserve_appliances,
    advance_reserve_after_slot,
    collect_active_reserves,
    detect_trigger_from_power,
    physical_reserves,
    prepare_battery_params_for_reserves,
    protected_kwh_from_state,
    virtual_asap_charge_kwh,
)
from runtime_store.powerstation_reserves import load_reserve_states, set_trigger
from optimizer.powerstation_writes import (  # noqa: F401  (re-exported: setpoint writers)
    _binding_for_ps,
    _ha_remap_powerstation_fields,
    _last_powerstation_sent,
    _loxone_ps_wire_value,
    _persist_ps_write_error,
    _physical_powerstation_ids,
    _resolve_marker,
    _standby_backup_physical_ids,
    _status_key,
    _utc_ts,
    _write_error_kinds,
    _write_powerstation_fields,
    _write_powerstation_ha,
    _write_powerstation_loxone,
    build_cycle_powerstation_fields,
    cycle_powerstation_charge_kw,
    cycle_standby_source_selects,
    last_powerstation_sent,
    planned_powerstation_loxone_sent,
    write_cycle_powerstation_setpoints,
    write_physical_powerstation_charges,
    write_standby_source_selects,
)

logger = logging.getLogger(__name__)


# Reports a failed live read (source, error) instead of dropping it (Reserve P1 wait loop).
ReadErrorReporter = Callable[[str, Exception], None]


class WaitReadErrors:
    """Logs each failing read source once per wait between two runs (Reserve P1).

    The wait-loop release check reads every 30 s; a lasting outage would flood the log, a
    swallowed one hides that no release can happen. One warning per source and wait, the
    loop goes on (the next regular run reads with its own error handling).
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def __call__(self, source: str, exc: Exception) -> None:
        if source in self._seen:
            return
        self._seen.add(source)
        logger.warning(
            "Reserve-Freigabe (Warteschleife): %s nicht lesbar (%s: %s) — über dieses Signal "
            "keine Freigabe bis zum nächsten Lauf; weitere Fehler dieser Quelle in dieser "
            "Wartezeit werden nicht geloggt.",
            source,
            type(exc).__name__,
            exc,
        )


def _planning_powerstations(on_read_error: ReadErrorReporter | None = None) -> list[dict]:
    try:
        resolved = config.get_resolved_runtime_settings()
    except Exception as exc:  # noqa: BLE001
        if on_read_error is not None:
            on_read_error("Powerstation-Konfiguration", exc)
        return []
    if not isinstance(resolved, dict):
        return []
    value = resolved.get("_planning_powerstations")
    return list(value) if isinstance(value, list) else []


def _reserve_appliances(on_read_error: ReadErrorReporter | None = None) -> list[dict]:
    from house_config.powerstation import MODE_RESERVE

    try:
        appliances = config.get_appliances()
    except Exception as exc:  # noqa: BLE001
        if on_read_error is not None:
            on_read_error("Geräte-Konfiguration", exc)
        else:
            logger.warning("powerstation_live: get_appliances failed")
        return []
    return [
        a for a in appliances if str(a.get("mode") or "") == MODE_RESERVE
    ]


def load_active_reserves() -> list[dict[str, Any]]:
    return collect_active_reserves(
        appliances=_reserve_appliances(),
        powerstations=_planning_powerstations(),
    )


def apply_reserves_to_battery_params(
    battery_params: dict | list[dict],
    reserves: list[dict[str, Any]] | None = None,
) -> dict | list[dict]:
    active = reserves if reserves is not None else load_active_reserves()
    return prepare_battery_params_for_reserves(battery_params, active)


def _consumers_by_id(on_read_error: ReadErrorReporter | None = None) -> dict[str, dict]:
    try:
        consumers = config.get_flexible_consumers()
    except Exception as exc:  # noqa: BLE001
        if on_read_error is not None:
            on_read_error("Verbraucher-Konfiguration", exc)
        return {}
    out: dict[str, dict] = {}
    for consumer in consumers or []:
        if not isinstance(consumer, dict):
            continue
        cid = str(consumer.get("id") or "").strip()
        if cid:
            out[cid] = consumer
    return out


def _telemetry_number(telemetry: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(telemetry, dict) or key not in telemetry:
        return None
    raw = telemetry.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _digital_active_from_consumer(
    consumer: dict, on_read_error: ReadErrorReporter | None = None
) -> bool | None:
    """Read ``sens_consumer_active`` Merker when mapped; None if unavailable."""
    from settings.ehal_marker_resolve import marker_sens_consumer_active

    io_name = marker_sens_consumer_active(consumer)
    if not io_name:
        return None
    try:
        from integrations.ehal_live import read_generic_value as fetch_loxone_generic_value

        raw = fetch_loxone_generic_value(io_name)
    except Exception as exc:  # noqa: BLE001
        if on_read_error is not None:
            on_read_error(f"Laufsignal {io_name}", exc)
        return None
    if raw is None:
        return None
    try:
        return float(raw) >= 0.5
    except (TypeError, ValueError):
        return None


def _live_power_kw(
    consumer: dict, on_read_error: ReadErrorReporter | None = None
) -> float | None:
    try:
        from integrations.ehal_live import resolve_consumer_live_power_kw

        return resolve_consumer_live_power_kw(consumer)
    except Exception as exc:  # noqa: BLE001
        if on_read_error is not None:
            on_read_error(f"Leistung von {consumer.get('id') or '?'}", exc)
        return None


def _first_telemetry_number(
    telemetry: dict[str, Any] | None, *keys: str
) -> float | None:
    for key in keys:
        value = _telemetry_number(telemetry, key)
        if value is not None:
            return value
    return None


def appliance_run_signal_active(
    appliance_id: str,
    *,
    telemetry: dict[str, Any] | None,
    consumers_by_id: dict[str, dict] | None = None,
    on_read_error: ReadErrorReporter | None = None,
) -> bool:
    """OR trigger: digital active, power threshold, or telemetry keys (2.7.p).

    ``on_read_error``: receives failed live reads (wait loop); without it they count as no
    signal, as in the cycle, which has the telemetry.
    """
    cid = str(appliance_id or "").strip()
    if not cid:
        return False
    # Exchange form consumer.* (2.7.n); flex.* remains an accepted storage/legacy alias.
    digital = _first_telemetry_number(
        telemetry,
        f"consumer.{cid}.sens_consumer_active",
        f"flex.{cid}.sens_consumer_active",
    )
    if digital is not None and digital >= 0.5:
        return True
    power = _first_telemetry_number(
        telemetry,
        f"consumer.{cid}.sens_power_act",
        f"flex.{cid}.sens_power_act",
    )
    if detect_trigger_from_power(power):
        return True
    consumer = (consumers_by_id or {}).get(cid)
    if consumer is None:
        return False
    live_digital = _digital_active_from_consumer(consumer, on_read_error)
    if live_digital is True:
        return True
    live_power = _live_power_kw(consumer, on_read_error)
    return detect_trigger_from_power(live_power)


def sync_triggers_from_telemetry(
    telemetry: dict[str, Any] | None,
    reserves: list[dict[str, Any]],
) -> None:
    """Release when any attached consumer runs (digital OR power OR PS out).

    Inactive while discharging does **not** clear the latch — leftover
    ``stored_kwh`` keeps draining until empty, then refill opens (2.7.p).
    """
    consumers = _consumers_by_id()
    for reserve in reserves:
        ps_id = str(reserve.get("powerstation_id") or "")
        if not ps_id:
            continue
        appliance_ids = [
            str(cid).strip()
            for cid in (reserve.get("appliance_ids") or [])
            if str(cid or "").strip()
        ]
        if not appliance_ids:
            singular = str(reserve.get("appliance_id") or "").strip()
            if singular:
                appliance_ids = [singular]
        triggered = any(
            appliance_run_signal_active(
                appliance_id, telemetry=telemetry, consumers_by_id=consumers
            )
            for appliance_id in appliance_ids
        )
        if not triggered:
            # Physical pack out power as free meter (2.7.g bonus).
            power = _telemetry_number(telemetry, f"ess.{ps_id}.sens_ess_power")
            triggered = detect_trigger_from_power(power)
        if triggered:
            set_trigger(ps_id, active=True)


def release_virtual_reserves_on_appliance_start(
    on_read_error: ReadErrorReporter | None = None,
) -> list[str]:
    """Wait-loop check (Reserve P1): latch filled virtual reserves whose appliance runs.

    Only reserves that hold energy (``protected_kwh`` > 0) and are not latched
    yet are checked, so one appliance start latches once; the latch stays until
    the reserve is empty (``advance_reserve_after_slot``). Reads live signals
    (no cycle telemetry between runs: signals only present in the cycle telemetry
    are not seen here) and writes the reserve state only on a trigger. Failed
    reads go to ``on_read_error`` (default: a ``WaitReadErrors`` for this call, so
    each one is logged). Returns the latched powerstation ids.
    """
    report = on_read_error if on_read_error is not None else WaitReadErrors()
    ps_by_id = {
        str(p["id"]): p
        for p in _planning_powerstations(report)
        if isinstance(p, dict) and p.get("id")
    }
    groups = _group_reserve_appliances(_reserve_appliances(report), ps_by_id, warn=False)
    if not groups:
        return []
    states = load_reserve_states()
    consumers: dict[str, dict] | None = None
    latched: list[str] = []
    for ps_id, group in groups.items():
        if str(ps_by_id[ps_id].get("backing") or BACKING_VIRTUAL) != BACKING_VIRTUAL:
            continue
        entry = states.get(ps_id)
        if entry is None or entry.get("trigger_active"):
            continue
        if protected_kwh_from_state(entry) <= 1e-9:
            continue
        if consumers is None:
            consumers = _consumers_by_id(report)
        for appliance in group:
            appliance_id = str(appliance.get("id") or "").strip()
            if appliance_id and appliance_run_signal_active(
                appliance_id,
                telemetry=None,
                consumers_by_id=consumers,
                on_read_error=report,
            ):
                set_trigger(ps_id, active=True)
                logger.info(
                    "Reserve %s freigegeben: Gerät %s läuft — Plan wird neu berechnet.",
                    ps_id,
                    appliance_id,
                )
                latched.append(ps_id)
                break
    return latched


def advance_virtual_reserves_from_plan(
    *,
    battery_plan_kw: float,
    dt_h: float,
    reserves: list[dict[str, Any]],
) -> None:
    """Attribute house charge/discharge to virtual carve-outs after a slot plan."""
    asap_total = virtual_asap_charge_kwh(reserves)
    charge_kw = max(0.0, float(battery_plan_kw))
    discharge_kw = max(0.0, -float(battery_plan_kw))
    charge_kwh = charge_kw * dt_h
    discharge_kwh = discharge_kw * dt_h

    virtual = [r for r in reserves if r.get("backing") == "virtual"]
    if not virtual:
        return

    # Equal-share ASAP charge attribution (priority deferred to 2.+1).
    needing = [r for r in virtual if float(r.get("asap_charge_kwh") or 0.0) > 1e-9]
    if needing and charge_kwh > 1e-9:
        share = charge_kwh / len(needing)
        for reserve in needing:
            advance_reserve_after_slot(
                powerstation_id=str(reserve["powerstation_id"]),
                charged_kwh=share,
            )

    discharging = [
        r for r in virtual if r.get("state") == "discharging" or r.get("trigger_active")
    ]
    if discharging and discharge_kwh > 1e-9:
        share = discharge_kwh / len(discharging)
        for reserve in discharging:
            advance_reserve_after_slot(
                powerstation_id=str(reserve["powerstation_id"]),
                discharged_kwh=share,
            )
    elif discharging:
        # Trigger without measured house discharge: hand off target over runtime.
        for reserve in discharging:
            target = float(reserve.get("target_kwh") or 0.0)
            runtime_h = max(0.25, target / max(0.1, float(reserve.get("target_kwh") or 0.1)))
            # Fall back: consume a slot share of target.
            step = target * min(1.0, dt_h / max(runtime_h, dt_h))
            advance_reserve_after_slot(
                powerstation_id=str(reserve["powerstation_id"]),
                discharged_kwh=step,
            )

    _ = asap_total  # documented equal-share uses needing list above


def physical_charge_setpoints_kw(
    reserves: list[dict[str, Any]],
) -> dict[str, float]:
    """per powerstation_id → charge kW (0 when standby/full or discharging)."""
    out: dict[str, float] = {}
    for reserve in physical_reserves(reserves):
        ps_id = str(reserve["powerstation_id"])
        asap = float(reserve.get("asap_charge_kwh") or 0.0)
        max_charge = float(reserve.get("max_charge_power_kw") or 0.0)
        if asap > 1e-9 and max_charge > 0.0:
            out[ps_id] = max_charge
        else:
            out[ps_id] = 0.0
    return out


def appliance_is_reserve_mode(appliance: dict) -> bool:
    return str(appliance.get("mode") or "") == MODE_RESERVE


def load_standby_packs(
    telemetry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from optimizer.powerstation_standby import collect_standby_packs

    try:
        appliances = config.get_appliances()
    except Exception:  # noqa: BLE001
        appliances = []
    # Also include house-profile consumers for default_power_kw lookup.
    try:
        flex = config.get_flexible_consumers(optimizer_only=False)
    except Exception:  # noqa: BLE001
        flex = []
    # Flex fills gaps; appliances win so default_power_kw from Manuelle Geräte
    # is not overwritten by consumer-shaped dicts that only have nominal_power_kw.
    by_id: dict[str, dict] = {}
    for item in list(flex or []) + list(appliances or []):
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            by_id[str(item["id"]).strip()] = item
    return collect_standby_packs(
        powerstations=_planning_powerstations(),
        appliances=list(by_id.values()),
        telemetry=telemetry,
    )


def update_reserve_fill_basis(
    battery_params: dict | list[dict],
    matrix: list[dict[str, Any]],
    reserves: list[dict[str, Any]],
    *,
    dt_h: float,
) -> None:
    """Persist or clear the fill basis of the virtual reserves after a live plan (Reserve P2).

    Some slot of the horizon pays and its fill source is the persisted basis or slot 0: that fill
    price becomes the basis, so the next re-plan inside the expensive phase still sees the
    reserve as cheaply filled. No slot pays (cheap phase, released or no reserve) or the fill
    source lies ahead: the basis is cleared.
    """
    from optimizer.reserve_price_floor import reserve_price_floor, slot_start
    from runtime_store.powerstation_reserves import (
        clear_fill_basis,
        save_reserve_states,
        set_fill_basis,
    )

    virtual_ids = [
        str(r["powerstation_id"]) for r in reserves if r.get("backing") == BACKING_VIRTUAL
    ]
    if not virtual_ids:
        return
    primary = battery_params[0] if isinstance(battery_params, list) else battery_params
    plan = reserve_price_floor(primary, matrix, horizon=len(matrix), dt_h=dt_h) if primary else None
    basis: tuple[float, datetime] | None = None
    first = plan.first_paying_slot() if plan is not None else None
    if plan is not None and first is not None:
        price, at = plan.fill_price[first], plan.fill_at[first]
        if price is None or at is None:
            raise ValueError(
                f"Virtuelle Reserve: Slot {first} lohnt sich ohne Füllpreis/-zeitpunkt."
            )
        # Keep the basis while any slot of the horizon pays, not only while the floor is held
        # at the end of slot 0: slot 0 pays only through the basis, so with prices that rise
        # gradually slot 1 never pays from slot 0 and a held-now rule never sets it. A fill
        # source in the future is energy not bought yet: no basis from it.
        if at <= slot_start(matrix, 0):
            basis = (float(price), at)
    states = load_reserve_states()
    for ps_id in virtual_ids:
        entry = states.get(ps_id)
        if entry is None:
            continue
        if basis is None:
            clear_fill_basis(entry)
        else:
            set_fill_basis(entry, price=basis[0], at=basis[1])
    save_reserve_states(states)
    if basis is not None:
        logger.info(
            "Virtuelle Reserve gehalten: Füllbasis %.3f (%s)", basis[0], basis[1].isoformat()
        )

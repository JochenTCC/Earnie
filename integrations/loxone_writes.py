"""Loxone write helpers: setpoints, ESS, flexible consumer outputs."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

import config
from integrations.loxone_comm_trace import LoxoneWriteRecord
from settings.ehal_marker_resolve import (
    marker_flex_enable,
    marker_set_evcs_max_current,
    marker_set_evcs_mode,
)
from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere
from settings.flexible_consumers import runtime_consumer_id

logger = logging.getLogger(__name__)


def _loxone_auth():
    from integrations import loxone_client as lc

    return lc._loxone_auth()


def _loxone_jdev_url(io_name: str) -> str:
    from integrations import loxone_client as lc

    return lc._loxone_jdev_url(io_name)


def resolve_consumer_nominal_power_kw(consumer: dict) -> float:
    from integrations.loxone_live_power import resolve_consumer_nominal_power_kw as _impl

    return _impl(consumer)


def _send_loxone_value_traced(input_name: str, value: float) -> LoxoneWriteRecord:
    """Sendet einen Steuerwert und liefert Erfolg plus Zeitstempel."""
    from integrations import loxone_client as lc

    io_name = str(input_name or "").strip()
    written_at = datetime.now().isoformat(timespec="seconds")
    if not io_name:
        return LoxoneWriteRecord(io_name="", value=float(value), success=False, written_at=written_at)

    url = f"http://{config.get('LOXONE_IP')}/dev/sps/io/{io_name}/{value}"
    timeout_val = config.get_global_timeout(default=5)

    try:
        response = lc.requests.get(
            url,
            auth=_loxone_auth(),
            timeout=timeout_val,
        )
        response.raise_for_status()
        print(f"   ↳ Loxone API: {io_name} erfolgreich auf {value} gesetzt.")
        return LoxoneWriteRecord(io_name=io_name, value=float(value), success=True, written_at=written_at)
    except lc.requests.exceptions.Timeout:
        print(f"🚨 Loxone-Fehler: Timeout ({timeout_val}s) beim Senden an {io_name}.")
    except lc.requests.exceptions.RequestException as e:
        from integrations.loxone_connectivity import raise_if_loxone_auth_http_error

        raise_if_loxone_auth_http_error(e, source="loxone_writes")
        print(f"🚨 Loxone-Fehler: Fehler beim Senden an {io_name}: {e}")
    return LoxoneWriteRecord(io_name=io_name, value=float(value), success=False, written_at=written_at)


def send_loxone_value(input_name: str, value: float) -> bool:
    """
    Sendet einen berechneten Steuerwert an einen Virtuellen Eingang des Loxone Miniservers.

    Args:
        input_name (str): Name des virtuellen Eingangs in Loxone (z.B. 'Ernie_Mode')
        value (float): Der zu setzende Wert (z.B. 1, 0, 2.5)

    Returns:
        bool: True bei Erfolg, False bei Fehlern.
    """
    return _send_loxone_value_traced(input_name, value).success


def map_ess_setpoints(
    mode: int, target_power_kw: float, max_power_kw: float
) -> tuple[float | None, float, float, int]:
    """Design C1: (active_power_kw|None, charge_limit_kw, discharge_limit_kw, mode_hint).

    ``active_power_kw`` uses EHAL sign (+discharge, −charge). ``None`` means Automatik /
    Entladesperre without a forced Equals setpoint. Limits are true caps (kW magnitudes).
    ``mode_hint`` is for Loxone/HA (Huawei Steuerbefehl); OpenEMS ignores it.
    """
    max_kw = max(0.0, abs(float(max_power_kw)))
    target = max(0.0, abs(float(target_power_kw)))
    if mode == 1:  # MODE_ZWANGS_LADEN
        return -target, max_kw, 0.0, 1
    if mode == 2:  # MODE_ENTLADESPERRE
        return None, max_kw, 0.0, 1
    if mode == 3:  # MODE_ZWANGS_ENTLADEN
        return target, 0.0, max_kw, 2
    return None, max_kw, max_kw, 0


def flex_consumer_enable_value(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
) -> int | None:
    """Freigabe 0/1 für einen flexiblen Verbraucher (None wenn kein enable Merker)."""
    if not marker_flex_enable(consumer):
        return None

    cid = consumer["id"]
    power_kw = _effective_consumer_power_kw(consumer, consumer_powers, charging_contexts, cid)
    return 1 if power_kw > 1e-3 else 0


def _effective_consumer_power_kw(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    cid: str,
) -> float:
    power_kw = max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0))
    ctx = charging_contexts.get(cid)
    if ctx is not None and not ctx.get("active", True):
        return 0.0
    if ctx is not None and ctx.get("anticipated") and not ctx.get("plugged_in"):
        return 0.0
    return power_kw


def flex_consumer_power_setpoint_kw(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> float | None:
    """kW-Sollwert aus MILP (None wenn kein set_evcs_max_current / power_setpoint)."""
    from optimizer.consumer_power import loxone_control_outputs

    if not marker_set_evcs_max_current(consumer):
        return None

    cid = consumer["id"]
    planned_kw = _effective_consumer_power_kw(consumer, consumer_powers, charging_contexts, cid)
    pv_follow = int((consumer_pv_follow or {}).get(cid, 0) or 0)
    setpoint_kw, _ = loxone_control_outputs(consumer, planned_kw, pv_follow)
    return setpoint_kw


def flex_consumer_setpoint_amps(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> float | None:
    """set_evcs_max_current (A) from planned kW; None wenn kein Current-Merker."""
    setpoint_kw = flex_consumer_power_setpoint_kw(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    if setpoint_kw is None:
        return None
    voltage_v, phases = ev_nominal_power_conversion(consumer)
    return round(kw_to_ampere(setpoint_kw, voltage_v=voltage_v, phases=phases), 3)


def _skip_flexible_consumer_output(
    consumer: dict,
    charging_contexts: dict[str, dict],
) -> bool:
    ctx = charging_contexts.get(consumer["id"]) or {}
    return bool(ctx.get("skip_loxone_output"))


_EVCS_MODE_VALUES: dict[str, float] = {"off": 0.0, "pv": 1.0, "now": 2.0}


def _append_evcs_mode_writes(
    values: dict[str, float],
    consumer: dict,
    *,
    mode: str | None,
) -> None:
    """Write the canonical ``set_evcs_mode`` Merker (off=0, pv=1, now=2)."""
    mode_name = marker_set_evcs_mode(consumer)
    if not mode_name:
        return
    values[mode_name] = _EVCS_MODE_VALUES.get(str(mode or "").strip().lower(), 0.0)


def _immediate_skip_output_values(consumer: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    _append_evcs_mode_writes(values, consumer, mode="now")
    if values:
        logger.info(
            "Flex consumer %s -> Sofort laden: set_evcs_mode=now "
            "(kein Lade-Sollstrom von Earnie).",
            consumer["name"],
        )
    else:
        logger.info(
            "Flex consumer %s -> keine Steuerung (Sofort laden aktiv, Loxone regelt).",
            consumer["name"],
        )
    return values


def _evcs_current_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None,
    current_name: str,
) -> dict[str, float]:
    from optimizer.consumer_power import loxone_control_outputs, set_evcs_mode_for_plan

    amps = flex_consumer_setpoint_amps(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    if amps is None:
        return {}
    values = {str(current_name): float(amps)}
    cid = consumer["id"]
    planned_kw = _effective_consumer_power_kw(
        consumer, consumer_powers, charging_contexts, cid
    )
    plan_pv = int((consumer_pv_follow or {}).get(cid, 0) or 0)
    _, pv_out = loxone_control_outputs(consumer, planned_kw, plan_pv)
    mode = set_evcs_mode_for_plan(
        pv_follow=int(pv_out),
        immediate=False,
        charging=float(amps) > 1e-6,
    )
    _append_evcs_mode_writes(values, consumer, mode=mode)
    setpoint_kw = flex_consumer_power_setpoint_kw(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    logger.info(
        "Flex consumer %s -> Soll=%.2f A (%.2f kW), mode=%s "
        "(geplant %.2f kW, Loxone: %s)",
        consumer["name"],
        amps,
        setpoint_kw or 0.0,
        mode,
        max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0)),
        current_name,
    )
    return values


def _enable_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    enable_name: str,
) -> dict[str, float]:
    enabled = flex_consumer_enable_value(consumer, consumer_powers, charging_contexts)
    if enabled is None:
        return {}
    power_kw = max(0.0, float(consumer_powers.get(consumer["id"], 0.0) or 0.0))
    logger.info(
        "Flex consumer %s -> Freigabe=%s (optimiert %.2f kW, Loxone: %s)",
        consumer["name"],
        enabled,
        power_kw,
        enable_name,
    )
    return {str(enable_name): float(enabled)}


def _flexible_consumer_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> dict[str, float]:
    """Berechnet Loxone-Merker → Wert für einen flexiblen Verbraucher (ohne HTTP)."""
    if _skip_flexible_consumer_output(consumer, charging_contexts):
        return _immediate_skip_output_values(consumer)

    current_name = marker_set_evcs_max_current(consumer)
    enable_name = marker_flex_enable(consumer)
    if current_name:
        return _evcs_current_output_values(
            consumer,
            consumer_powers,
            charging_contexts,
            consumer_pv_follow,
            current_name,
        )

    if not enable_name:
        return {}
    return _enable_output_values(
        consumer, consumer_powers, charging_contexts, enable_name
    )


def _write_flexible_consumer_output(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    snapshot: dict[str, float] | None,
    consumer_pv_follow: dict[str, int] | None = None,
    *,
    send: bool,
) -> list[LoxoneWriteRecord]:
    """Schreibt Freigabe/Strom-Sollwert/Modus an Loxone und/oder in den Snapshot."""
    values = _flexible_consumer_output_values(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    records: list[LoxoneWriteRecord] = []
    if send:
        for io_name, value in values.items():
            records.append(_send_loxone_value_traced(io_name, value))
    if snapshot is not None:
        snapshot.update(values)
    return records


def build_sent_loxone_snapshot(
    mode: int,
    target_power_kw: float,
    target_soc: float,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> dict[str, float]:
    """Alle an Loxone gesendeten Steuerwerte: Merkername → Zahl."""
    max_kw = float(config.get_battery_params().get("max_power_kw") or 0.0)
    active_kw, charge_kw, discharge_kw, control_cmd = map_ess_setpoints(
        mode, target_power_kw, max_kw
    )
    contexts = charging_contexts or {}
    snapshot: dict[str, float] = {}
    # target_soc_name removed (2.4.j): ESS via active_power + limits + set_ess_mode.
    _ = target_soc

    for cfg_name, value in (
        (config.get("LOXONE_TARGET_ACTIVE_POWER_NAME"), active_kw),
        (config.get("LOXONE_TARGET_CHARGE_POWER_NAME"), charge_kw),
        (config.get("LOXONE_TARGET_DISCHARGE_POWER_NAME"), discharge_kw),
        (config.get("LOXONE_CONTROL_CMD_NAME"), float(control_cmd)),
    ):
        if not cfg_name:
            continue
        if value is None:
            if cfg_name != config.get("LOXONE_TARGET_ACTIVE_POWER_NAME"):
                continue
            snapshot[str(cfg_name)] = 0.0
        else:
            snapshot[str(cfg_name)] = float(value)

    for consumer in config.get_flexible_consumers(optimizer_only=True):
        _write_flexible_consumer_output(
            consumer, consumer_powers, contexts, snapshot, consumer_pv_follow, send=False
        )

    return snapshot


def send_huawei_modbus_states(
    mode: int, target_power_kw: float, target_soc: float
) -> list[LoxoneWriteRecord]:
    """Übersetzt Optimierungsmodi und schreibt ESS-Steuerwerte (Design C1) an Loxone."""
    from integrations import loxone_client as lc

    max_kw = float(lc.config.get_battery_params().get("max_power_kw") or 0.0)
    active_kw, charge_kw, discharge_kw, control_cmd = map_ess_setpoints(
        mode, target_power_kw, max_kw
    )
    # target_soc no longer written (2.4.j); kept in signature for call-site compat.
    _ = target_soc

    logger.info(
        "Sending ESS C1 Mapping -> Soll: %s kW, Ladegrenze: %s kW, "
        "Entladegrenze: %s kW, set_ess_mode/Cmd: %s",
        active_kw,
        charge_kw,
        discharge_kw,
        control_cmd,
    )

    records: list[LoxoneWriteRecord] = []
    active_name = lc.config.get("LOXONE_TARGET_ACTIVE_POWER_NAME")

    for cfg_name, value in (
        (active_name, active_kw),
        (lc.config.get("LOXONE_TARGET_CHARGE_POWER_NAME"), charge_kw),
        (lc.config.get("LOXONE_TARGET_DISCHARGE_POWER_NAME"), discharge_kw),
        (lc.config.get("LOXONE_CONTROL_CMD_NAME"), float(control_cmd)),
    ):
        if not cfg_name:
            continue
        if value is None:
            # Sticky Merker: still refresh Sollleistung with 0 under Automatik/Entladesperre.
            if cfg_name != active_name:
                continue
            send_value = 0.0
        else:
            send_value = float(value)
        records.append(lc._send_loxone_value_traced(str(cfg_name), send_value))
    return records


def send_flexible_consumer_states(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> list[LoxoneWriteRecord]:
    """Sendet Freigabe (0/1), set_evcs_max_current (A) und set_evcs_mode an Loxone."""
    contexts = charging_contexts or {}
    records: list[LoxoneWriteRecord] = []
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        records.extend(
            _write_flexible_consumer_output(
                consumer, consumer_powers, contexts, None, consumer_pv_follow, send=True
            )
        )
    return records



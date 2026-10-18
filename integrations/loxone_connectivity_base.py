"""Check record, read-check primitive and consumer predicates (split from loxone_connectivity)."""
from __future__ import annotations

from dataclasses import dataclass
import config
from integrations import loxone_client


@dataclass(frozen=True)
class LoxoneCheck:
    """Einzelprüfung: EHAL-Feld (label), Mapping/IO-Name, Erfolg, Detailtext."""

    label: str
    io_name: str
    passed: bool
    detail: str
    severity: str = "error"
    state: str | None = None


def _check_counts_as_ok(item: LoxoneCheck) -> bool:
    """True wenn die Prüfung den Gesamtstatus nicht negativ beeinflusst."""
    return item.passed or item.severity == "warning"


def _read_check(
    label: str,
    io_name: str,
    *,
    read_raw: bool = False,
    warn_if_missing: bool = False,
    validate_filter_start_hour: bool = False,
) -> LoxoneCheck:
    from ehal.push_signals import REQUEST_OPTIMIZE_ID

    io_name = str(io_name or "").strip()
    if not io_name:
        return LoxoneCheck(label, io_name, False, "IO-Name fehlt in config.json")

    if label == REQUEST_OPTIMIZE_ID or io_name == REQUEST_OPTIMIZE_ID:
        return _read_control_receipt_check(label, io_name)

    if read_raw:
        return _read_ready_by_check(label, io_name, warn_if_missing=warn_if_missing)

    if validate_filter_start_hour:
        return _read_filter_start_hour_check(label, io_name)

    return _read_push_inbox_check(label, io_name)


def _read_ready_by_check(
    label: str, io_name: str, *, warn_if_missing: bool
) -> LoxoneCheck:
    # FertigUm / ready-by: push inbox only (Q7 — Merker / SpecialState10 poll retired).
    raw = loxone_client.fetch_loxone_ready_by_time(io_name)
    if raw is None:
        detail = "Wert leer (Push-Inbox — noch kein Termin gepusht)"
        return LoxoneCheck(
            label,
            io_name,
            False,
            detail,
            severity="warning" if warn_if_missing else "error",
        )
    display = loxone_client.format_ready_by_display(raw)
    return LoxoneCheck(label, io_name, True, f"Wert={display}")


def _read_filter_start_hour_check(label: str, io_name: str) -> LoxoneCheck:
    hour, fmt, raw = loxone_client.fetch_filter_native_start_hour(io_name)
    if hour is None:
        detail = f"Start-Stunde nicht parsebar (raw={raw!r}, format={fmt})"
        return LoxoneCheck(label, io_name, False, detail)
    return LoxoneCheck(
        label,
        io_name,
        True,
        f"Start={hour:.0f} h, Format={fmt}, raw={raw!r}",
    )


_EXPORT_HINT = "Signalliste → Export"


def _never_received_warning(label: str, io_name: str, *, state: str | None) -> LoxoneCheck:
    """Activated binding without VO push yet (Binding Lx2) — soft warning."""
    base = "Kein frischer Push-Inbox-Wert"
    if state:
        base = f"{base} ({state})"
    return LoxoneCheck(
        label,
        io_name,
        False,
        f"{base} — {_EXPORT_HINT}",
        severity="warning",
        state=state or "nie empfangen",
    )


def _read_push_inbox_check(label: str, io_name: str) -> LoxoneCheck:
    from ehal.loxone_push_source import is_pushable_kind, resolve_push_binding
    from runtime_store.loxone_push_inbox import (
        STATE_ZERO_ASSUMED_NEVER,
        is_valid_ehal_id,
        read_push_value,
    )

    try:
        binding = resolve_push_binding(io_name)
    except Exception:  # noqa: BLE001
        binding = None

    if binding is not None and is_pushable_kind(binding.kind):
        try:
            value, state = read_push_value(binding.ehal_id)
        except Exception:  # noqa: BLE001 — no Merker poll fallback for push
            return _never_received_warning(label, io_name, state=None)
        if value is None:
            return _never_received_warning(label, io_name, state=state)
        if state == STATE_ZERO_ASSUMED_NEVER:
            # Soft: value assumed 0 because never pushed; still warn + export hint.
            return LoxoneCheck(
                label,
                io_name,
                False,
                f"Wert={value}; {state} — {_EXPORT_HINT}",
                severity="warning",
                state=state,
            )
        return LoxoneCheck(label, io_name, True, f"Wert={value}", state=state)

    # Activated empty keys use the qualified EHAL ID as io_name; treat that as
    # "never received" (Lx2), not a hard Merker-poll error.
    if is_valid_ehal_id(io_name):
        return _never_received_warning(label, io_name, state=None)

    # Q7: no Merker HTTP fallback — only push inbox (handled above) counts.
    return LoxoneCheck(
        label,
        io_name,
        False,
        "Kein Push-Inbox-Wert (kein Mapping / Hub-Poll entfernt)",
    )


def _is_ev_consumer(consumer: dict) -> bool:
    """True for EV — ``type`` may be missing after planning→MILP bridge."""
    if consumer.get("type") == "ev":
        return True
    sched = consumer.get("charging_schedule") or {}
    if not isinstance(sched, dict):
        return False
    if sched.get("enabled"):
        return True
    lox = sched.get("loxone") if isinstance(sched.get("loxone"), dict) else {}
    for key in (
        "plugged_in_name",
        "actual_soc_name",
        "ready_by_time_name",
        "battery_capacity_kwh_name",
        "nominal_power_kw_name",
        "sens_evcs_connected",
        "sens_evcs_soc_act",
        "get_evcs_ready_by_time",
    ):
        if str(lox.get(key) or "").strip():
            return True
    bindings = consumer.get("ehal_bindings")
    if isinstance(bindings, dict):
        for key, value in bindings.items():
            name = str(key or "")
            if name.startswith(("sens_evcs_", "get_evcs_", "set_evcs_")) and str(
                value or ""
            ).strip():
                return True
    return False


def _consumer_has_live_read_marker(consumer: dict) -> bool:
    from settings.ehal_marker_resolve import (
        marker_flex_power,
        marker_get_evcs_ready_by_time,
        marker_get_filter_remaining_hours,
        marker_get_temperature_tolerance_c,
        marker_get_temperature_water_setpoint,
        marker_sens_evcs_active_power,
        marker_sens_evcs_connected,
        marker_sens_heating_active,
        marker_sens_temperature_heat_storage,
        marker_sens_temperature_heat_storage_low,
        marker_sens_temperature_water,
    )

    if marker_flex_power(consumer) or marker_sens_evcs_active_power(consumer):
        return True
    if marker_sens_evcs_connected(consumer) or marker_get_evcs_ready_by_time(consumer):
        return True
    if marker_get_filter_remaining_hours(consumer):
        return True
    if (
        marker_sens_temperature_water(consumer)
        or marker_get_temperature_water_setpoint(consumer)
        or marker_get_temperature_tolerance_c(consumer)
        or marker_sens_heating_active(consumer)
    ):
        return True
    if marker_sens_temperature_heat_storage(
        consumer
    ) or marker_sens_temperature_heat_storage_low(consumer):
        return True
    return False


def _consumers_for_live_reads() -> list[dict]:
    """House-profile consumers first (keep ``ehal_bindings``), then flex-only rows.

    Planning→MILP bridge drops ``type`` / ``ehal_bindings``; Live-Lesen must use
    the house-profile record when both exist (e.g. greenfield EV mappings).
    """
    by_id: dict[str, dict] = {}
    resolved = config.CONFIG.get_resolved_runtime_settings()
    profile = resolved.get("_house_profile") if isinstance(resolved, dict) else None
    if isinstance(profile, dict):
        for consumer in profile.get("consumers") or []:
            if not isinstance(consumer, dict):
                continue
            cid = str(consumer.get("id") or "").strip()
            if cid and _consumer_has_live_read_marker(consumer):
                by_id[cid] = consumer

    for consumer in config.get_flexible_consumers():
        cid = str(consumer.get("id") or "").strip()
        if not cid or cid in by_id:
            continue
        if _consumer_has_live_read_marker(consumer):
            by_id[cid] = consumer
    return list(by_id.values())


def _append_io_check(
    checks: list[tuple[str, str, dict]],
    label: str,
    io_name: str,
    opts: dict | None = None,
) -> None:
    name = str(io_name or "").strip()
    if name:
        checks.append((label, name, opts or {}))


def _read_control_receipt_check(label: str, io_name: str) -> LoxoneCheck:
    """Live-Lesen row for rare daemon HTTP receipts (no zero-assumption)."""
    from runtime_store.loxone_push_inbox import read_control_receipt

    value, state, _last_ts = read_control_receipt(label)
    if value is None:
        return LoxoneCheck(
            label,
            io_name,
            False,
            state,
            severity="warning",
            state=state,
        )
    return LoxoneCheck(
        label, io_name, True, f"Wert={value}", state=state
    )


def _is_filter_consumer(consumer: dict) -> bool:
    cid = str(consumer.get("id") or "").strip()
    if cid == "pool_filter":
        return True
    if consumer.get("daily_target_source") == "loxone_remaining_hours":
        return True
    fsched = consumer.get("filter_schedule")
    return isinstance(fsched, dict) and bool(fsched.get("enabled"))


def _is_thermal_consumer(consumer: dict) -> bool:
    """True for Pool/SwimSpa thermal_rc (or water-temp EHAL bindings)."""
    if str(consumer.get("type") or "") == "thermal_rc":
        return True
    from settings.ehal_marker_resolve import (
        marker_get_temperature_tolerance_c,
        marker_get_temperature_water_setpoint,
        marker_sens_heating_active,
        marker_sens_temperature_water,
    )

    return bool(
        marker_sens_temperature_water(consumer)
        or marker_get_temperature_water_setpoint(consumer)
        or marker_get_temperature_tolerance_c(consumer)
        or marker_sens_heating_active(consumer)
    )


def _is_thermal_annual_consumer(consumer: dict) -> bool:
    """True for heat-pump thermal_annual (or heat-storage EHAL bindings)."""
    if str(consumer.get("type") or "") == "thermal_annual":
        return True
    from settings.ehal_marker_resolve import (
        marker_sens_temperature_heat_storage,
        marker_sens_temperature_heat_storage_low,
    )

    return bool(
        marker_sens_temperature_heat_storage(consumer)
        or marker_sens_temperature_heat_storage_low(consumer)
    )

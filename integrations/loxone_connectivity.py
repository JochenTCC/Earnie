"""Loxone-Verbindungsprüfung für Integrationstests und Installations-Checks."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Callable

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


def _check_counts_as_ok(item: LoxoneCheck) -> bool:
    """True wenn die Prüfung den Gesamtstatus nicht negativ beeinflusst."""
    return item.passed or item.severity == "warning"


def loxone_env_configured() -> bool:
    """True wenn Miniserver-Zugangsdaten in der Umgebung gesetzt sind."""
    from runtime_store.dotenv_io import loxone_credentials_configured

    return loxone_credentials_configured()


def probe_loxone_http_access(
    *,
    host: str,
    username: str,
    password: str,
    timeout_sec: float = 5.0,
) -> tuple[bool, str]:
    """Light LoxAPP3 GET (streamed) to verify Miniserver reachability + auth.

    Returns ``(ok, detail)``. Does not download the full structure JSON.
    """
    import requests
    from requests.auth import HTTPBasicAuth

    ip = str(host or "").strip().removeprefix("http://").removeprefix("https://")
    ip = ip.split("/")[0]
    if not ip:
        return False, "LOXONE_IP is empty"
    url = f"http://{ip}/data/LoxAPP3.json"
    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(username, password),
            timeout=timeout_sec,
            stream=True,
        )
    except (requests.RequestException, OSError, ValueError) as exc:
        return False, f"Loxone unreachable: {exc}"
    try:
        code = int(response.status_code)
    finally:
        response.close()
    if code == 200:
        return True, f"LoxAPP3 HTTP {code}"
    if code in (401, 403):
        return False, f"Loxone auth failed (HTTP {code})"
    return False, f"LoxAPP3 HTTP {code} from {url}"


def ensure_live_config(config_path: str = config.CONFIG_JSON_PATH) -> None:
    """Lädt config.json mit Pflicht auf Loxone-Credentials (kein Offline-Modus)."""
    config.CONFIG = config.Config(
        config_path=config_path,
        require_loxone_credentials=True,
    )


def _read_check(
    label: str,
    io_name: str,
    *,
    validate: Callable[[float], str | None] | None = None,
    read_raw: bool = False,
    warn_if_missing: bool = False,
    validate_filter_start_hour: bool = False,
) -> LoxoneCheck:
    io_name = str(io_name or "").strip()
    if not io_name:
        return LoxoneCheck(label, io_name, False, "IO-Name fehlt in config.json")

    if read_raw:
        # FertigUm: AlarmClock SpecialState10 (unix) via /all; Tna text as backup.
        raw = (
            loxone_client.fetch_loxone_ready_by_time(io_name)
            if warn_if_missing
            else loxone_client.fetch_loxone_raw_value(io_name)
        )
        if raw is None:
            # Empty SpecialState10 / Tna is common when no next alarm is set.
            detail = (
                "Wert leer (AlarmClock nextEntryTime / Tna — in Loxone noch kein Termin)"
                if warn_if_missing
                else "Lesen fehlgeschlagen (kein Wert)"
            )
            if warn_if_missing:
                return LoxoneCheck(label, io_name, False, detail, severity="warning")
            return LoxoneCheck(label, io_name, False, detail)
        display = (
            loxone_client.format_ready_by_display(raw)
            if warn_if_missing
            else repr(raw)
        )
        prefix = "Wert=" if warn_if_missing else "raw="
        return LoxoneCheck(label, io_name, True, f"{prefix}{display}")

    if validate_filter_start_hour:
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

    value = loxone_client.fetch_loxone_generic_value(io_name)
    if value is None:
        return LoxoneCheck(label, io_name, False, "Lesen oder Parsen fehlgeschlagen")
    if validate is not None:
        error = validate(float(value))
        if error:
            return LoxoneCheck(label, io_name, False, error)
    return LoxoneCheck(label, io_name, True, f"Wert={value}")


def _soc_valid(value: float) -> str | None:
    if not math.isfinite(value) or value < 0.0 or value > 100.0:
        return f"SoC außerhalb 0–100 %: {value}"
    return None


def _power_valid(value: float) -> str | None:
    if not math.isfinite(value):
        return f"Leistung nicht numerisch: {value}"
    if abs(value) > 500.0:
        return f"Leistung unrealistisch hoch: {value} kW"
    return None


def _temperature_valid(value: float) -> str | None:
    if not math.isfinite(value):
        return f"Temperatur nicht numerisch: {value}"
    if value < -60.0 or value > 80.0:
        return f"Temperatur unrealistisch: {value} °C"
    return None


def _binary_valid(value: float) -> str | None:
    if value in (0.0, 1.0):
        return None
    return f"Erwartet 0 oder 1, erhalten: {value}"


def _consumer_power_validate(consumer: dict) -> Callable[[float], str | None]:
    inputs = consumer.get("loxone_inputs") or {}
    signal = inputs.get("signal_type") or consumer.get("signal_type", "power")
    if signal == "binary":
        return _binary_valid
    return _power_valid


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
        marker_sens_evcs_active_power,
        marker_sens_evcs_connected,
    )

    if marker_flex_power(consumer) or marker_sens_evcs_active_power(consumer):
        return True
    if marker_sens_evcs_connected(consumer) or marker_get_evcs_ready_by_time(consumer):
        return True
    if marker_get_filter_remaining_hours(consumer):
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


def _append_ev_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from settings.ehal_marker_resolve import (
        marker_get_evcs_limit_soc,
        marker_get_evcs_ready_by_time,
        marker_get_evcs_soc_min_immediate,
        marker_sens_evcs_active_power,
        marker_sens_evcs_bat_capacity,
        marker_sens_evcs_connected,
        marker_get_evcs_nominal_current,
        marker_sens_evcs_soc_act,
    )

    cid = consumer["id"]
    _append_io_check(
        checks,
        f"{cid}:sens_evcs_active_power",
        marker_sens_evcs_active_power(consumer),
        {"validate": _consumer_power_validate(consumer)},
    )
    _append_io_check(
        checks,
        f"{cid}:sens_evcs_connected",
        marker_sens_evcs_connected(consumer),
        {"validate": _binary_valid},
    )
    _append_io_check(
        checks,
        f"{cid}:sens_evcs_soc_act",
        marker_sens_evcs_soc_act(consumer),
        {"validate": _soc_valid},
    )
    _append_io_check(
        checks,
        f"{cid}:sens_evcs_bat_capacity",
        marker_sens_evcs_bat_capacity(consumer),
    )
    _append_io_check(
        checks,
        f"{cid}:get_evcs_nominal_current",
        marker_get_evcs_nominal_current(consumer),
        {"validate": _power_valid},
    )
    _append_io_check(
        checks,
        f"{cid}:get_evcs_ready_by_time",
        marker_get_evcs_ready_by_time(consumer),
        {"read_raw": True, "warn_if_missing": True},
    )
    _append_io_check(
        checks,
        f"{cid}:get_evcs_limit_soc",
        marker_get_evcs_limit_soc(consumer),
        {"validate": _soc_valid},
    )
    _append_io_check(
        checks,
        f"{cid}:get_evcs_soc_min_immediate",
        marker_get_evcs_soc_min_immediate(consumer),
        {"validate": _soc_valid},
    )


def _append_flex_power_check(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from settings.ehal_marker_resolve import marker_flex_power

    from ehal.flex_fields import flex_sens_power_act

    cid = consumer["id"]
    _append_io_check(
        checks,
        f"{cid}:{flex_sens_power_act(cid)}",
        marker_flex_power(consumer),
        {"validate": _consumer_power_validate(consumer)},
    )


def _append_filter_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from settings.ehal_marker_resolve import (
        marker_get_filter_native_duration_hours,
        marker_get_filter_native_start_hour,
        marker_get_filter_remaining_hours,
        marker_sens_filter_active,
    )

    cid = consumer["id"]
    _append_flex_power_check(checks, consumer)
    _append_io_check(
        checks,
        f"{cid}:get_filter_remaining_hours",
        marker_get_filter_remaining_hours(consumer),
        {"validate": _power_valid},
    )
    _append_io_check(
        checks,
        f"{cid}:sens_filter_active",
        marker_sens_filter_active(consumer),
        {"validate": _binary_valid},
    )
    _append_io_check(
        checks,
        f"{cid}:get_filter_native_start_hour",
        marker_get_filter_native_start_hour(consumer),
    )
    _append_io_check(
        checks,
        f"{cid}:get_filter_native_duration_hours",
        marker_get_filter_native_duration_hours(consumer),
        {"validate": _power_valid},
    )


def _is_filter_consumer(consumer: dict) -> bool:
    cid = str(consumer.get("id") or "").strip()
    if cid == "pool_filter":
        return True
    if consumer.get("daily_target_source") == "loxone_remaining_hours":
        return True
    fsched = consumer.get("filter_schedule")
    return isinstance(fsched, dict) and bool(fsched.get("enabled"))


def collect_read_checks() -> list[tuple[str, str, dict]]:
    """(EHAL-Feld, Mapping/IO-Name) — plant ``sens_*`` + consumer reads."""
    from settings.ehal_marker_resolve import marker_sens_temperature_outside

    checks: list[tuple[str, str, dict]] = [
        ("sens_ess_soc", config.get("LOXONE_SOC_NAME"), {"validate": _soc_valid}),
        (
            "sens_pv_production_active",
            config.get("LOXONE_PV_POWER_NAME"),
            {"validate": _power_valid},
        ),
        (
            "sens_ess_power",
            config.get("LOXONE_BATTERY_POWER_NAME"),
            {"validate": _power_valid},
        ),
        (
            "sens_grid_power_active",
            config.get("LOXONE_GRID_POWER_NAME"),
            {"validate": _power_valid},
        ),
    ]
    consumers_power = config.get("LOXONE_CONSUMERS_POWER_NAME")
    if consumers_power:
        checks.append(
            ("sens_power_consumers", consumers_power, {"validate": _power_valid})
        )

    ambient_io = marker_sens_temperature_outside(
        house_doc=loxone_client._default_house_profiles_doc()
    )
    _append_io_check(
        checks,
        "sens_temperature_outside",
        ambient_io,
        {"validate": _temperature_valid},
    )

    for consumer in _consumers_for_live_reads():
        if _is_ev_consumer(consumer):
            _append_ev_read_checks(checks, consumer)
        elif _is_filter_consumer(consumer):
            _append_filter_read_checks(checks, consumer)
        else:
            _append_flex_power_check(checks, consumer)

    return checks


def run_read_checks() -> list[LoxoneCheck]:
    """Liest alle konfigurierten IOs live vom Miniserver."""
    results: list[LoxoneCheck] = []
    for label, io_name, opts in collect_read_checks():
        results.append(_read_check(label, io_name, **opts))
    return results


def verify_loxone_setup() -> tuple[bool, list[LoxoneCheck]]:
    """
    Führt alle Lese-Prüfungen gegen den Miniserver aus.

    Returns:
        (alle_ok, einzelergebnisse)
    """
    ensure_live_config()
    results = run_read_checks()
    return all(_check_counts_as_ok(item) for item in results), results

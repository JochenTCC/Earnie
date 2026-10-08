"""Loxone-Verbindungsprüfung für Integrationstests und Installations-Checks."""
from __future__ import annotations

import os
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


def _check_counts_as_ok(item: LoxoneCheck) -> bool:
    """True wenn die Prüfung den Gesamtstatus nicht negativ beeinflusst."""
    return item.passed or item.severity == "warning"


def loxone_env_configured() -> bool:
    """True wenn Miniserver-Zugangsdaten in der Umgebung gesetzt sind."""
    from runtime_store.dotenv_io import loxone_credentials_configured

    return loxone_credentials_configured()


class LoxoneAuthError(RuntimeError):
    """HTTP 401/403 against the Miniserver — credentials rejected."""

    def __init__(self, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.http_status = int(http_status)


def is_loxone_auth_http_status(code: int) -> bool:
    return int(code) in (401, 403)


def record_loxone_auth_http_error(
    exc: BaseException,
    *,
    source: str,
) -> bool:
    """Persist auth failure for HTTP 401/403; return True if recorded."""
    import requests

    if not isinstance(exc, requests.exceptions.RequestException):
        return False
    response = getattr(exc, "response", None)
    if response is None:
        return False
    code = int(response.status_code)
    if not is_loxone_auth_http_status(code):
        return False
    message = f"Loxone auth failed (HTTP {code})"
    from runtime_store.loxone_auth_error import persist_loxone_auth_error

    persist_loxone_auth_error(message=message, http_status=code, source=source)
    return True


def raise_if_loxone_auth_http_error(
    exc: BaseException,
    *,
    source: str,
) -> None:
    """Persist auth failure and raise ``LoxoneAuthError`` for HTTP 401/403."""
    if record_loxone_auth_http_error(exc, source=source):
        code = int(getattr(getattr(exc, "response", None), "status_code", 403))
        message = f"Loxone auth failed (HTTP {code})"
        raise LoxoneAuthError(message, http_status=code) from exc


def probe_current_loxone_credentials() -> tuple[bool, str]:
    """Probe LoxAPP3 with credentials from config."""
    return probe_loxone_http_access(
        host=config.get("LOXONE_IP"),
        username=config.get("LOXONE_USER"),
        password=config.get("LOXONE_PASS"),
    )


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
    return LoxoneCheck(label, io_name, True, f"Wert={value}")


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


def ev_ehal_binding_collisions(consumer: dict) -> list[tuple[str, str, list[str]]]:
    """Return (io_name, detail, fields) when distinct EV EHAL roles share one Merker."""
    from collections import defaultdict

    from settings.ehal_marker_resolve import (
        marker_get_evcs_nominal_current,
        marker_get_evcs_soc_min_immediate,
        marker_sens_evcs_active_power,
        marker_sens_evcs_connected,
        marker_set_evcs_max_current,
        marker_set_evcs_mode,
    )

    roles = {
        "sens_evcs_active_power": marker_sens_evcs_active_power(consumer),
        "sens_evcs_connected": marker_sens_evcs_connected(consumer),
        "set_evcs_max_current": marker_set_evcs_max_current(consumer),
        "set_evcs_mode": marker_set_evcs_mode(consumer),
        "get_evcs_nominal_current": marker_get_evcs_nominal_current(consumer),
        "get_evcs_soc_min_immediate": marker_get_evcs_soc_min_immediate(consumer),
    }
    by_io: dict[str, list[str]] = defaultdict(list)
    for field, io_name in roles.items():
        name = str(io_name or "").strip()
        if name:
            by_io[name].append(field)
    out: list[tuple[str, str, list[str]]] = []
    for io_name, fields in sorted(by_io.items()):
        if len(fields) < 2:
            continue
        detail = (
            f"EV ehal_bindings collision on '{io_name}': "
            + ", ".join(fields)
            + " (writes/reads must use distinct Merker)"
        )
        out.append((io_name, detail, fields))
    return out


def _append_ev_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from integrations.ehal_debug_mapping import live_read_consumer_field
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

    # Force EV namespace when type was dropped by the planning bridge.
    ev = dict(consumer)
    if not str(ev.get("type") or "").strip():
        ev["type"] = "ev"
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "sens_evcs_active_power"),
        marker_sens_evcs_active_power(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "sens_evcs_connected"),
        marker_sens_evcs_connected(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "sens_evcs_soc_act"),
        marker_sens_evcs_soc_act(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "sens_evcs_bat_capacity"),
        marker_sens_evcs_bat_capacity(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "get_evcs_nominal_current"),
        marker_get_evcs_nominal_current(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "get_evcs_ready_by_time"),
        marker_get_evcs_ready_by_time(consumer),
        {"read_raw": True, "warn_if_missing": True},
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "get_evcs_limit_soc"),
        marker_get_evcs_limit_soc(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(ev, "get_evcs_soc_min_immediate"),
        marker_get_evcs_soc_min_immediate(consumer),
    )


def _append_flex_power_check(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from ehal.flex_fields import flex_sens_consumer_active, flex_sens_power_act
    from integrations.ehal_debug_mapping import live_read_consumer_field
    from settings.ehal_marker_resolve import (
        marker_flex_power,
        marker_sens_consumer_active,
    )

    cid = consumer["id"]
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, flex_sens_power_act(cid)),
        marker_flex_power(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, flex_sens_consumer_active(cid)),
        marker_sens_consumer_active(consumer),
    )


def _append_filter_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from integrations.ehal_debug_mapping import live_read_consumer_field
    from settings.ehal_marker_resolve import (
        marker_get_filter_native_duration_hours,
        marker_get_filter_native_start_hour,
        marker_get_filter_remaining_hours,
        marker_sens_filter_active,
    )

    _append_flex_power_check(checks, consumer)
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_filter_remaining_hours"),
        marker_get_filter_remaining_hours(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_filter_active"),
        marker_sens_filter_active(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_filter_native_start_hour"),
        marker_get_filter_native_start_hour(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_filter_native_duration_hours"),
        marker_get_filter_native_duration_hours(consumer),
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


def _append_thermal_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from integrations.ehal_debug_mapping import live_read_consumer_field
    from settings.ehal_marker_resolve import (
        marker_get_temperature_tolerance_c,
        marker_get_temperature_water_setpoint,
        marker_sens_heating_active,
        marker_sens_temperature_water,
    )

    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_temperature_water"),
        marker_sens_temperature_water(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_temperature_water_setpoint"),
        marker_get_temperature_water_setpoint(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "get_temperature_tolerance_c"),
        marker_get_temperature_tolerance_c(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_heating_active"),
        marker_sens_heating_active(consumer),
    )


def _append_thermal_annual_read_checks(
    checks: list[tuple[str, str, dict]],
    consumer: dict,
) -> None:
    from integrations.ehal_debug_mapping import live_read_consumer_field
    from settings.ehal_marker_resolve import (
        marker_sens_temperature_heat_storage,
        marker_sens_temperature_heat_storage_low,
    )

    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_temperature_heat_storage"),
        marker_sens_temperature_heat_storage(consumer),
    )
    _append_io_check(
        checks,
        live_read_consumer_field(consumer, "sens_temperature_heat_storage_low"),
        marker_sens_temperature_heat_storage_low(consumer),
    )


def collect_read_checks() -> list[tuple[str, str, dict]]:
    """(EHAL-Feld, Mapping/IO-Name) — plant ``sens_*`` + consumer reads."""
    from settings.ehal_marker_resolve import (
        marker_get_ess_max_charge_power,
        marker_get_ess_max_discharge_power,
        marker_get_ess_soc_max,
        marker_get_ess_soc_min,
        marker_get_grid_export_power_limit,
        marker_sens_absent_mode,
        marker_sens_temperature_outside,
    )

    checks: list[tuple[str, str, dict]] = [
        ("sens_ess_soc", config.get("LOXONE_SOC_NAME"), {}),
        ("sens_pv_production_active", config.get("LOXONE_PV_POWER_NAME"), {}),
        ("sens_ess_power", config.get("LOXONE_BATTERY_POWER_NAME"), {}),
        ("sens_grid_power_active", config.get("LOXONE_GRID_POWER_NAME"), {}),
    ]
    consumers_power = config.get("LOXONE_CONSUMERS_POWER_NAME")
    if consumers_power:
        checks.append(("sens_power_consumers", consumers_power, {}))

    house_doc = loxone_client._default_house_profiles_doc()
    ambient_io = marker_sens_temperature_outside(house_doc=house_doc)
    _append_io_check(checks, "sens_temperature_outside", ambient_io)
    absent_io = marker_sens_absent_mode(house_doc=house_doc)
    _append_io_check(checks, "sens_absent_mode", absent_io)
    export_in_io = marker_get_grid_export_power_limit(house_doc=house_doc)
    _append_io_check(checks, "get_grid_export_power_limit", export_in_io)
    _append_io_check(
        checks, "get_ess_soc_min", marker_get_ess_soc_min(house_doc=house_doc)
    )
    _append_io_check(
        checks, "get_ess_soc_max", marker_get_ess_soc_max(house_doc=house_doc)
    )
    _append_io_check(
        checks,
        "get_ess_max_charge_power",
        marker_get_ess_max_charge_power(house_doc=house_doc),
    )
    _append_io_check(
        checks,
        "get_ess_max_discharge_power",
        marker_get_ess_max_discharge_power(house_doc=house_doc),
    )

    for consumer in _consumers_for_live_reads():
        if _is_ev_consumer(consumer):
            _append_ev_read_checks(checks, consumer)
        elif _is_filter_consumer(consumer):
            _append_filter_read_checks(checks, consumer)
        else:
            _append_flex_power_check(checks, consumer)
            if _is_thermal_consumer(consumer):
                _append_thermal_read_checks(checks, consumer)
            if _is_thermal_annual_consumer(consumer):
                _append_thermal_annual_read_checks(checks, consumer)

    _append_battery_ess_read_checks(checks)
    return checks


def _append_battery_ess_read_checks(checks: list[tuple[str, str, dict]]) -> None:
    """Per-battery Pattern B ESS reads from ``components.json`` (2.7.m)."""
    from ehal.ess_fields import binding_address
    from integrations.ehal_debug_mapping import BATTERY_ESS_LIVE_READ_KINDS

    try:
        from house_config.components_store import load_components_document
        from runtime_store.persist_paths import resolve_components_json_path

        path = resolve_components_json_path()
        if not path:
            return
        doc = load_components_document(path)
    except Exception:
        return
    from house_config.powerstation import ehal_mappable_batteries

    batteries = doc.get("batteries") if isinstance(doc, dict) else []
    for battery in ehal_mappable_batteries(
        batteries if isinstance(batteries, list) else []
    ):
        bid = str(battery.get("id") or "").strip()
        if not bid:
            continue
        bindings = battery.get("ehal_bindings")
        for kind in BATTERY_ESS_LIVE_READ_KINDS:
            from ehal.ess_fields import ess_field

            field = ess_field(bid, kind)
            io_name = binding_address(
                bindings if isinstance(bindings, dict) else None, bid, kind
            )
            _append_io_check(checks, field, io_name)


def run_read_checks() -> list[LoxoneCheck]:
    """Liest alle konfigurierten IOs live vom Miniserver."""
    results: list[LoxoneCheck] = []
    for label, io_name, opts in collect_read_checks():
        results.append(_read_check(label, io_name, **opts))
    for consumer in _consumers_for_live_reads():
        if not _is_ev_consumer(consumer):
            continue
        cid = consumer["id"]
        for io_name, detail, _fields in ev_ehal_binding_collisions(consumer):
            results.append(
                LoxoneCheck(
                    f"{cid}:ehal_binding_collision",
                    io_name,
                    False,
                    detail,
                    severity="warning",
                )
            )
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

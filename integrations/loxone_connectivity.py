"""Loxone-Verbindungsprüfung für Integrationstests und Installations-Checks."""
from __future__ import annotations


import config
from integrations import loxone_client
from integrations.loxone_connectivity_base import (  # noqa: F401  (re-exported)
    LoxoneCheck,
    _append_io_check,
    _check_counts_as_ok,
    _consumer_has_live_read_marker,
    _consumers_for_live_reads,
    _is_ev_consumer,
    _is_filter_consumer,
    _is_thermal_annual_consumer,
    _is_thermal_consumer,
    _read_check,
    _read_control_receipt_check,
)
from integrations.loxone_connectivity_checks import (  # noqa: F401  (re-exported)
    _append_battery_ess_read_checks,
    _append_ev_read_checks,
    _append_filter_read_checks,
    _append_flex_power_check,
    _append_inverter_read_checks,
    _append_plant_energy_read_checks,
    _append_pv_system_read_checks,
    _append_thermal_annual_read_checks,
    _append_thermal_read_checks,
    ev_ehal_binding_collisions,
)






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
    from runtime_store.shadow.replay import assert_not_shadow_backend

    assert_not_shadow_backend("loxone_connectivity.probe_loxone_http_access")
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


































def collect_read_checks() -> list[tuple[str, str, dict]]:
    """(EHAL-Feld, Mapping/IO-Name) — plant ``sens_*`` + consumer reads."""
    from ehal.qualified_ids import qualified_plant_id
    from house_config.ehal_bindings import resolve_plant_binding
    from settings.ehal_marker_resolve import (
        marker_get_grid_export_power_limit,
        marker_sens_absent_mode,
        marker_sens_temperature_outside,
    )

    checks: list[tuple[str, str, dict]] = []
    house_doc = loxone_client._default_house_profiles_doc()
    # ESS reads come from _append_battery_ess_read_checks (entity-scoped only).
    # Plant PV is retired — Live uses inv.*.sens_inv_power_pv (inverter checks).
    grid_io = resolve_plant_binding(house_doc, "sens_grid_power_active")
    if grid_io:
        checks.append(
            (qualified_plant_id("sens_grid_power_active"), grid_io, {})
        )
    consumers_io = resolve_plant_binding(house_doc, "sens_power_consumers")
    if consumers_io:
        checks.append(("sens_power_consumers", consumers_io, {}))

    ambient_io = marker_sens_temperature_outside(house_doc=house_doc)
    _append_io_check(checks, "sens_temperature_outside", ambient_io)
    absent_io = marker_sens_absent_mode(house_doc=house_doc)
    _append_io_check(checks, "sens_absent_mode", absent_io)
    export_in_io = marker_get_grid_export_power_limit(house_doc=house_doc)
    _append_io_check(
        checks, qualified_plant_id("get_grid_export_power_limit"), export_in_io
    )
    _append_plant_energy_read_checks(checks, house_doc)

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
    _append_inverter_read_checks(checks)
    _append_pv_system_read_checks(checks)
    from ehal.push_signals import REQUEST_OPTIMIZE_ID, REQUEST_OPTIMIZE_TITLE

    checks.append((REQUEST_OPTIMIZE_ID, REQUEST_OPTIMIZE_TITLE, {}))
    return checks








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

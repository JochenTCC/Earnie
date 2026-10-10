# loxone_client.py
import math
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

import config
import logging
from integrations.loxone_comm_trace import LoxoneWriteRecord
from settings.ehal_marker_resolve import (
    ehal_bindings,
    marker_flex_enable,
    marker_flex_power,
    marker_get_evcs_nominal_current,
    marker_sens_evcs_active_power,
    marker_sens_evcs_bat_capacity,
    marker_set_evcs_max_current,
    marker_set_evcs_mode,
)
from settings.ev_power import (
    ampere_to_kw,
    ev_nominal_power_conversion,
    kw_from_nominal_reading,
    kw_to_ampere,
)
from settings.flexible_consumers import runtime_consumer_id

logger = logging.getLogger(__name__)

_UNIT_SUFFIXES = (
    ("kWh", "kwh"),
    ("kW", "kw"),
    ("W", "w"),
    ("%", "pct"),
    ("°C", "c"),
    ("°", "c"),
    (" h", "h"),
    ("A", "a"),
)
def _loxone_auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(config.get("LOXONE_USER"), config.get("LOXONE_PASS"))


def _loxone_jdev_url(io_name: str) -> str:
    return f"http://{config.get('LOXONE_IP')}/jdev/sps/io/{io_name}"


def _loxone_jdev_all_url(io_name: str) -> str:
    return f"http://{config.get('LOXONE_IP')}/jdev/sps/io/{io_name}/all"


def _parse_loxone_value(raw_value: str) -> tuple[float, str | None]:
    """Parst Loxone-Werte wie '3.5 kW', '16 A' oder '16A' → (Zahl, Einheit|None)."""
    text = str(raw_value).strip().replace(",", ".")
    if not text:
        raise ValueError("leerer Wert")

    for suffix, unit in _UNIT_SUFFIXES:
        if text.endswith(suffix):
            return float(text[: -len(suffix)].strip()), unit
        if len(suffix) == 1 and text.lower().endswith(suffix.lower()):
            return float(text[:-1].strip()), unit

    parts = text.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].upper() == "A":
        return float(parts[0]), "a"

    return float(text), None


def _parse_loxone_numeric(raw_value: str) -> float:
    value, _ = _parse_loxone_value(raw_value)
    return value


def _parse_hour_minute_text(text: str) -> int | None:
    from datetime import datetime

    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text.strip(), fmt).hour
        except ValueError:
            continue
    return None


def parse_filter_native_start_hour(
    raw_value: str | float | int | None,
) -> tuple[float | None, str]:
    """
    Parst die Start-Stunde des nativen Filter-Duty-Cycles.

    Unterstützt Integer 0–23 (z. B. ``10``, ``10.0``, ``10 h``) und ``HH:MM``.
    Returns:
        (Stunde 0–23 oder None, Format: integer | hm | missing | unknown)
    """
    if raw_value is None:
        return None, "missing"
    if isinstance(raw_value, (int, float)):
        hour = float(raw_value)
        if 0.0 <= hour <= 23.0:
            return hour, "integer"
        return None, "unknown"

    text = str(raw_value).strip()
    if not text:
        return None, "missing"

    hm_hour = _parse_hour_minute_text(text)
    if hm_hour is not None:
        return float(hm_hour), "hm"

    clean = text
    if clean.lower().endswith(" h"):
        clean = clean[:-2].strip()
    elif clean.lower().endswith("h") and ":" not in clean:
        clean = clean[:-1].strip()

    try:
        hour = float(clean.replace(",", "."))
    except ValueError:
        return None, "unknown"
    if 0.0 <= hour <= 23.0:
        return hour, "integer"
    return None, "unknown"


def fetch_filter_native_start_hour(io_name: str) -> tuple[float | None, str, str | None]:
    """Liest und parst die native Filter-Start-Stunde live. Returns: (hour, format, raw).

    Pushable bindings read the inbox only (no Merker poll fallback).
    """
    io_name = str(io_name or "").strip()
    if not io_name:
        return None, "missing", None
    try:
        from ehal.loxone_push_source import resolve_push_binding
        from runtime_store.loxone_push_inbox import read_push_value

        binding = resolve_push_binding(io_name)
        if binding is not None:
            value, state = read_push_value(binding.ehal_id)
            if value is None:
                logger.warning(
                    "Loxone push: no filter start for '%s' (%s, state=%s)",
                    io_name,
                    binding.ehal_id,
                    state,
                )
                return None, "missing", None
            raw = str(int(value)) if float(value).is_integer() else str(value)
            hour, fmt = parse_filter_native_start_hour(raw)
            return hour, fmt, raw
    except Exception:  # noqa: BLE001
        logger.exception(
            "Loxone push filter start failed for '%s'; not falling back to poll",
            io_name,
        )
        return None, "missing", None

    raw = fetch_loxone_raw_value(io_name)
    if raw is None:
        return None, "missing", None
    hour, fmt = parse_filter_native_start_hour(raw)
    return hour, fmt, raw


def fetch_loxone_raw_value(io_name: str) -> Optional[str]:
    """GET ``/jdev/sps/io/<name>`` — Merker poll only.

    Pushable ``sens_*`` / ``get_*`` telemetry must use ``fetch_loxone_generic_value``
    (VO push inbox). Intentional remaining Merker polls: unbound / unindexed names
    via that helper's fallback; greenfield / structure presence probes; shadow or
    auth connectivity probes that are not optimizer telemetry. Writes use
    ``_loxone_jdev_url`` (not this read). Meter energy ``/all`` and FertigUm
    SpecialState10 are retired (Q6 / Q7).
    """
    io_name = str(io_name or "").strip()
    if not io_name:
        return None

    feed_key = f"loxone:io:{io_name}"
    from runtime_store.shadow.mode import is_shadow_mode

    if is_shadow_mode():
        from runtime_store.shadow.replay import replay_loxone_io

        return replay_loxone_io(feed_key)

    timeout_val = config.get_global_timeout(default=5)
    try:
        response = requests.get(
            _loxone_jdev_url(io_name),
            auth=_loxone_auth(),
            timeout=timeout_val,
        )
        status = int(response.status_code)
        raw_text = response.text
        try:
            payload = response.json()
        except ValueError:
            payload = raw_text
        response.raise_for_status()
        raw_value = (
            payload.get("LL", {}).get("value", "")
            if isinstance(payload, dict)
            else ""
        )
        if raw_value is None or str(raw_value).strip() == "":
            logger.warning("Loxone: Kein value für '%s'", io_name)
            _shadow_record(feed_key, ok=False, payload=payload, status=status, error="empty value")
            return None
        _shadow_record(feed_key, ok=True, payload=payload, status=status)
        return str(raw_value).strip()
    except requests.exceptions.Timeout:
        logger.error(
            "Loxone: Timeout (%ss) beim Abrufen von '%s'", timeout_val, io_name
        )
        _shadow_record(feed_key, ok=False, error=f"timeout {timeout_val}s")
    except requests.exceptions.RequestException as e:
        from integrations.loxone_connectivity import record_loxone_auth_http_error

        record_loxone_auth_http_error(e, source="loxone_client.read")
        logger.error("Loxone: Netzwerkfehler bei '%s': %s", io_name, e)
        status = getattr(getattr(e, "response", None), "status_code", None)
        _shadow_record(feed_key, ok=False, status=status, error=str(e))
    except (KeyError, TypeError) as e:
        logger.error("Loxone: Antwort-Fehler bei '%s': %s", io_name, e)
        _shadow_record(feed_key, ok=False, error=str(e))
    return None


def _shadow_record(
    key: str,
    *,
    ok: bool,
    payload: object = None,
    status: int | None = None,
    error: str | None = None,
) -> None:
    try:
        from runtime_store.shadow.hooks import record_transport

        record_transport(key, ok=ok, payload=payload, status=status, error=error)
    except Exception:  # noqa: BLE001 — never break Loxone reads
        pass


# AlarmClock nextEntryTime (SpecialState10): seconds since 2009-01-01.
# Unix = loxone_seconds + LOXONE_EPOCH_TO_UNIX (see loxforum / Structure File).
LOXONE_EPOCH_TO_UNIX = 1230768000


def normalize_loxone_time_to_unix(seconds: float) -> Optional[float]:
    """Loxone Counter (s since 2009-01-01) or Unix seconds → Unix seconds."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    if value > 1_000_000_000:
        return value
    return value + LOXONE_EPOCH_TO_UNIX


def format_ready_by_display(value: str | float) -> str:
    """Human-readable FertigUm for Live-Lesen (local datetime + unix, or Tna text)."""
    if isinstance(value, str):
        text = value.strip().strip("'\"")
        if not text:
            return text
        try:
            as_num = float(text.replace(",", "."))
        except ValueError:
            return text
    else:
        as_num = float(value)
        text = str(value)
    unix = normalize_loxone_time_to_unix(as_num)
    if unix is None:
        return text
    stamp = datetime.fromtimestamp(unix).strftime("%Y-%m-%d %H:%M:%S")
    return f"{stamp} (unix {int(unix)})"


def _fetch_loxone_io_all(io_name: str) -> Optional[dict]:
    """GET ``/jdev/sps/io/{name}/all`` → LL dict, or None on error / non-200."""
    io_name = str(io_name or "").strip()
    if not io_name:
        return None

    feed_key = f"loxone:io_all:{io_name}"
    from runtime_store.shadow.mode import is_shadow_mode

    if is_shadow_mode():
        from runtime_store.shadow.replay import replay_loxone_io_all

        return replay_loxone_io_all(feed_key)

    timeout_val = config.get_global_timeout(default=5)
    try:
        response = requests.get(
            _loxone_jdev_all_url(io_name),
            auth=_loxone_auth(),
            timeout=timeout_val,
        )
        status = int(response.status_code)
        try:
            body = response.json()
        except ValueError:
            body = response.text
        response.raise_for_status()
        ll = (body.get("LL") if isinstance(body, dict) else None) or {}
        if not isinstance(ll, dict):
            _shadow_record(feed_key, ok=False, payload=body, status=status, error="no LL")
            return None
        if str(ll.get("Code") or "") not in ("", "200"):
            _shadow_record(
                feed_key, ok=False, payload=ll, status=status, error=f"code {ll.get('Code')}"
            )
            return None
        _shadow_record(feed_key, ok=True, payload=ll, status=status)
        return ll
    except requests.exceptions.Timeout:
        logger.error(
            "Loxone: Timeout (%ss) bei AlarmClock/all '%s'", timeout_val, io_name
        )
        _shadow_record(feed_key, ok=False, error=f"timeout {timeout_val}s")
    except requests.exceptions.RequestException as e:
        from integrations.loxone_connectivity import record_loxone_auth_http_error

        record_loxone_auth_http_error(e, source="loxone_client.read_all")
        logger.error("Loxone: Netzwerkfehler bei AlarmClock/all '%s': %s", io_name, e)
        status = getattr(getattr(e, "response", None), "status_code", None)
        _shadow_record(feed_key, ok=False, status=status, error=str(e))
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Loxone: Antwort-Fehler bei AlarmClock/all '%s': %s", io_name, e)
        _shadow_record(feed_key, ok=False, error=str(e))
    return None


def _alarm_clock_next_entry_unix(ll: dict) -> Optional[float]:
    """SpecialState10 / nextEntryTime → Unix seconds, or None if unset."""
    item = ll.get("SpecialState10")
    if not isinstance(item, dict):
        return None
    raw = item.get("value")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        lox_seconds = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return normalize_loxone_time_to_unix(lox_seconds)


def _alarm_clock_tna_from_ll(ll: dict) -> Optional[str]:
    """Backup: AlarmClock output Tna text (e.g. ``Morgen, 06:15``)."""
    for item in ll.values():
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "") != "Tna":
            continue
        raw = item.get("value")
        if raw is None or str(raw).strip() == "":
            return None
        return str(raw).strip()
    return None


def fetch_loxone_alarm_clock_tna(io_name: str) -> Optional[str]:
    """Backup path: AlarmClock Tna text via ``/all``.

    Prefer ``fetch_loxone_ready_by_time`` (SpecialState10). Kept if Loxone
    renames SpecialState indices; Tna remains the human-readable output.
    """
    ll = _fetch_loxone_io_all(io_name)
    if not ll:
        return None
    return _alarm_clock_tna_from_ll(ll)


def _legacy_ready_by_value(raw: str | float | None) -> str | float | None:
    """Convert legacy Merker numeric Counter → Unix; leave text unchanged."""
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            as_num = float(text.replace(",", "."))
        except ValueError:
            return text
        unix = normalize_loxone_time_to_unix(as_num)
        return unix if unix is not None else text
    unix = normalize_loxone_time_to_unix(float(raw))
    return unix if unix is not None else raw


def fetch_loxone_ready_by_time(io_name: str) -> str | float | None:
    """FertigUm: push inbox only (Q7 — SpecialState10 / Tna / Merker poll retired).

    Returns numeric Unix or fresh Tna text for ``parse_loxone_ready_by_time``.
    ``io_name`` may be a Merker name (resolved to a push binding) or a qualified ID.
    """
    name = str(io_name or "").strip()
    if not name:
        return None
    try:
        from ehal.loxone_push_source import resolve_push_binding
        from runtime_store.loxone_push_inbox import read_push_ready_by_time

        binding = resolve_push_binding(name)
        ehal_id = binding.ehal_id if binding is not None else name
        value = read_push_ready_by_time(ehal_id)
        if value is None:
            logger.warning(
                "Loxone push: no ready_by_time for '%s' (%s)",
                name,
                ehal_id,
            )
        return value
    except Exception:  # noqa: BLE001 — no SpecialState10 / Merker poll fallback
        logger.exception(
            "Loxone push ready_by_time failed for '%s'; poll path removed (Q7)",
            name,
        )
        return None


def _looks_like_ehal_id(name: str) -> bool:
    """True for qualified/bare EHAL IDs (never Merker-poll; push-only since 2.7.o / F)."""
    from ehal.qualified_ids import field_kind, parse_qualified_id

    text = str(name or "").strip()
    if not text:
        return False
    if parse_qualified_id(text) is not None:
        return True
    kind = field_kind(text)
    return kind.startswith(("sens_", "get_", "set_"))


def fetch_loxone_generic_value(io_name: str) -> Optional[float]:
    """Holt einen numerischen Wert: push inbox for bound pushable fields, else Merker poll.

    Meter ``/all`` energy stays on poll (never calls this for energy IDs). FertigUm uses
    ``fetch_loxone_ready_by_time``. Bound pushable fields never fall back to Merker HTTP.
    Qualified/bare EHAL IDs are push-only: unbound → ``None`` (no Merker poll).
    ``io_name`` may be a Merker name or a qualified/bare EHAL ID.
    """
    name = str(io_name or "").strip()
    if name:
        try:
            from ehal.loxone_push_source import resolve_push_binding
            from runtime_store.loxone_push_inbox import read_push_value

            binding = resolve_push_binding(name)
            if binding is not None:
                value, state = read_push_value(binding.ehal_id)
                if value is None:
                    logger.warning(
                        "Loxone push: no value for '%s' (%s, state=%s)",
                        name,
                        binding.ehal_id,
                        state,
                    )
                return value
            if _looks_like_ehal_id(name):
                return None
        except Exception:  # noqa: BLE001 — do not fall back to poll for push bindings
            logger.exception(
                "Loxone push read failed for '%s'; not falling back to poll", name
            )
            return None

    raw_value = fetch_loxone_raw_value(io_name)
    if raw_value is None:
        return None
    try:
        return _parse_loxone_numeric(raw_value)
    except ValueError as e:
        logger.error("Loxone: Parsing-Fehler bei '%s' (raw=%r): %s", io_name, raw_value, e)
        return None



from integrations.loxone_live_power import (  # noqa: E402
    LiveFlexPowerResult,
    consumers_with_live_nominal_power,
    fetch_flexible_consumers_live_kw,
    fetch_loxone_live_power,
    resolve_consumer_battery_capacity_kwh,
    resolve_consumer_live_power_kw,
    resolve_consumer_nominal_power_kw,
    resolve_flexible_consumers_live_power,
    _apply_native_filter_inference,
    _binary_meter_kw,
    _build_chart_kw,
    _consumer_power_io_name,
    _default_live_power_consumers,
    _house_profile_power_consumers,
    _read_consumer_meter_kw,
    _shared_meter_heating_ids,
    _slot_in_native_filter_window,
    _subtract_shared_meter_loads,
)
from integrations.loxone_writes import (  # noqa: E402
    build_sent_loxone_snapshot,
    flex_consumer_enable_value,
    flex_consumer_power_setpoint_kw,
    flex_consumer_setpoint_amps,
    map_ess_setpoints,
    send_flexible_consumer_states,
    send_huawei_modbus_states,
    send_loxone_value,
    _append_evcs_mode_writes,
    _effective_consumer_power_kw,
    _enable_output_values,
    _evcs_current_output_values,
    _flexible_consumer_output_values,
    _immediate_skip_output_values,
    _send_loxone_value_traced,
    _skip_flexible_consumer_output,
    _write_flexible_consumer_output,
)

def _read_optional_temp_c(io_name: str) -> float | None:
    io_name = str(io_name or "").strip()
    if not io_name:
        return None
    return fetch_loxone_generic_value(io_name)


def _default_house_profiles_doc() -> dict | None:
    """Load house_profiles.json for plant ehal_bindings (e.g. sens_temperature_outside)."""
    try:
        from house_config.profiles_store import load_house_profiles_document
        from runtime_store.persist_paths import resolve_house_profiles_json_path

        path = resolve_house_profiles_json_path()
        if not path or not os.path.isfile(path):
            return None
        return load_house_profiles_document(path)
    except Exception as exc:
        logger.warning("house_profiles für Plant-Bindings nicht geladen: %s", exc)
        return None


def fetch_heat_storage_temps(
    consumer: dict,
    *,
    house_doc: dict | None = None,
) -> dict:
    """Read heat-storage T_eq / T_low for thermal_annual (missing → None)."""
    from settings.ehal_marker_resolve import (
        marker_sens_temperature_heat_storage,
        marker_sens_temperature_heat_storage_low,
    )

    _ = house_doc  # reserved for plant-scoped fallbacks
    eq_io = marker_sens_temperature_heat_storage(consumer)
    low_io = marker_sens_temperature_heat_storage_low(consumer)
    return {
        "temp_eq_c": _read_optional_temp_c(eq_io),
        "temp_low_c": _read_optional_temp_c(low_io),
    }


def fetch_thermal_readings(
    consumer: dict,
    *,
    house_doc: dict | None = None,
    config_doc: dict | None = None,
) -> dict:
    """Read thermal temps / heating flag via ehal_bindings; ambient from plant only."""
    from settings.ehal_marker_resolve import (
        marker_get_temperature_tolerance_c,
        marker_get_temperature_water_setpoint,
        marker_sens_heating_active,
        marker_sens_temperature_outside,
        marker_sens_temperature_water,
    )

    thermal = consumer.get("thermal_control") or {}
    missing: list[str] = []
    if house_doc is None:
        house_doc = _default_house_profiles_doc()

    actual_io = marker_sens_temperature_water(consumer)
    actual = _read_optional_temp_c(actual_io)
    if actual is None:
        missing.append("sens_temperature_water")

    setpoint_io = marker_get_temperature_water_setpoint(consumer)
    setpoint = _read_optional_temp_c(setpoint_io)
    if setpoint is None and thermal.get("setpoint_c") is None:
        missing.append("get_temperature_water_setpoint")

    ambient_io = marker_sens_temperature_outside(
        house_doc=house_doc, config_doc=config_doc
    )
    ambient = _read_optional_temp_c(ambient_io)
    if ambient is None:
        missing.append("sens_temperature_outside")

    tolerance_io = marker_get_temperature_tolerance_c(consumer)
    tolerance = _read_optional_temp_c(tolerance_io)
    if tolerance is None and thermal.get("tolerance_c") is None:
        missing.append("get_temperature_tolerance_c")

    heating_active = None
    heating_io = marker_sens_heating_active(consumer)
    if heating_io:
        raw = fetch_loxone_generic_value(heating_io)
        if raw is None:
            missing.append("sens_heating_active")
        else:
            heating_active = raw >= 0.5

    return {
        "actual_c": actual,
        "setpoint_c": setpoint,
        "ambient_c": ambient,
        "tolerance_c": tolerance,
        "heating_active": heating_active,
        "missing_signals": missing,
    }

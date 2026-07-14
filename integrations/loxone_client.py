# loxone_client.py
import math
import os
from dataclasses import dataclass
from datetime import datetime
from ftplib import FTP, all_errors as ftp_errors
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

import config
import logging
from settings.ev_power import kw_from_nominal_reading

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
    """Liest und parst die native Filter-Start-Stunde live. Returns: (hour, format, raw)."""
    io_name = str(io_name or "").strip()
    if not io_name:
        return None, "missing", None
    raw = fetch_loxone_raw_value(io_name)
    if raw is None:
        return None, "missing", None
    hour, fmt = parse_filter_native_start_hour(raw)
    return hour, fmt, raw


def fetch_loxone_raw_value(io_name: str) -> Optional[str]:
    """Holt den rohen LL.value-String live aus dem Loxone Miniserver."""
    io_name = str(io_name or "").strip()
    if not io_name:
        return None

    timeout_val = config.get_global_timeout(default=5)
    try:
        response = requests.get(
            _loxone_jdev_url(io_name),
            auth=_loxone_auth(),
            timeout=timeout_val,
        )
        response.raise_for_status()
        raw_value = response.json().get("LL", {}).get("value", "")
        if raw_value is None or str(raw_value).strip() == "":
            logger.warning("Loxone: Kein value für '%s'", io_name)
            return None
        return str(raw_value).strip()
    except requests.exceptions.Timeout:
        logger.error(
            "Loxone: Timeout (%ss) beim Abrufen von '%s'", timeout_val, io_name
        )
    except requests.exceptions.RequestException as e:
        logger.error("Loxone: Netzwerkfehler bei '%s': %s", io_name, e)
    except (KeyError, TypeError) as e:
        logger.error("Loxone: Antwort-Fehler bei '%s': %s", io_name, e)
    return None


def fetch_loxone_generic_value(io_name: str) -> Optional[float]:
    """Holt einen numerischen Wert live aus dem Loxone Miniserver (Einheiten werden abgeschnitten)."""
    raw_value = fetch_loxone_raw_value(io_name)
    if raw_value is None:
        return None
    try:
        return _parse_loxone_numeric(raw_value)
    except ValueError as e:
        logger.error("Loxone: Parsing-Fehler bei '%s' (raw=%r): %s", io_name, raw_value, e)
        return None


def resolve_consumer_nominal_power_kw(consumer: dict) -> float:
    """Nennleistung (kW): live aus Loxone, sonst Fallback aus config.json."""
    fallback = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    sched = consumer.get("charging_schedule") or {}
    lox = sched.get("loxone") or {}
    io_name = lox.get("nominal_power_kw_name", "")
    if not io_name:
        return fallback

    raw = fetch_loxone_raw_value(io_name)
    if raw is None:
        logger.warning(
            "Loxone: Keine gültige Nennleistung für '%s' (%s), Fallback %.2f kW",
            consumer.get("id"),
            io_name,
            fallback,
        )
        return fallback

    try:
        value, unit = _parse_loxone_value(raw)
    except ValueError as e:
        logger.error(
            "Loxone: Parsing-Fehler bei Nennleistung '%s' (raw=%r): %s",
            io_name,
            raw,
            e,
        )
        return fallback

    live = kw_from_nominal_reading(value, unit, consumer)

    if live <= 0:
        logger.warning(
            "Loxone: Keine gültige Nennleistung für '%s' (%s, raw=%r), Fallback %.2f kW",
            consumer.get("id"),
            io_name,
            raw,
            fallback,
        )
        return fallback
    return float(live)


def resolve_consumer_battery_capacity_kwh(consumer: dict) -> float | None:
    """Akkukapazität (kWh): Hausprofil-Bridge oder live aus Loxone."""
    direct = consumer.get("battery_capacity_kwh")
    if direct is not None and float(direct) > 0:
        return float(direct)
    sched = consumer.get("charging_schedule") or {}
    sched_cap = sched.get("battery_capacity_kwh")
    if sched_cap is not None and float(sched_cap) > 0:
        return float(sched_cap)

    lox = sched.get("loxone") or {}
    io_name = str(lox.get("battery_capacity_kwh_name", "")).strip()
    cid = consumer.get("id", "?")
    if not io_name:
        logger.error(
            "Verbraucher '%s': charging_schedule.loxone.battery_capacity_kwh_name fehlt.",
            cid,
        )
        return None

    raw = fetch_loxone_raw_value(io_name)
    if raw is None:
        logger.error(
            "Loxone: Akkukapazität für '%s' (%s) nicht lesbar.",
            cid,
            io_name,
        )
        return None

    try:
        value, unit = _parse_loxone_value(raw)
    except ValueError as e:
        logger.error(
            "Loxone: Parsing-Fehler bei Akkukapazität '%s' (raw=%r): %s",
            io_name,
            raw,
            e,
        )
        return None

    if unit is not None and unit not in ("kwh", "kw", ""):
        logger.error(
            "Loxone: Unbekannte Einheit '%s' bei Akkukapazität '%s' (%s).",
            unit,
            cid,
            io_name,
        )
        return None

    if value <= 0:
        logger.error(
            "Loxone: Ungültige Akkukapazität für '%s' (%s, raw=%r).",
            cid,
            io_name,
            raw,
        )
        return None
    return float(value)


def fetch_charge_immediate_remaining_seconds(consumer: dict) -> float | None:
    """Verbleibende Sofort-Ladezeit in Sekunden (Loxone-Countdown)."""
    sched = consumer.get("charging_schedule") or {}
    lox = sched.get("loxone") or {}
    io_name = str(lox.get("charge_immediate_remaining_name", "")).strip()
    if not io_name:
        logger.warning(
            "Verbraucher '%s': charge_immediate_remaining_name fehlt in der Config.",
            consumer.get("id"),
        )
        return None

    raw = fetch_loxone_generic_value(io_name)
    if raw is None:
        logger.warning(
            "Loxone: Keine Restladezeit für '%s' (%s).",
            consumer.get("id"),
            io_name,
        )
        return None

    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        logger.error(
            "Loxone: Parsing-Fehler bei Restladezeit '%s' (raw=%r).",
            io_name,
            raw,
        )
        return None

    if not math.isfinite(seconds) or seconds < 0:
        logger.warning(
            "Loxone: Ungültige Restladezeit für '%s' (%s, raw=%r).",
            consumer.get("id"),
            io_name,
            raw,
        )
        return None
    return seconds


def consumers_with_live_nominal_power(consumers: list | None = None) -> list:
    """Kopie der Verbraucher mit zur Laufzeit aus Loxone gelesener Nennleistung."""
    import copy
    source = consumers if consumers is not None else config.get_flexible_consumers(optimizer_only=True)
    updated = []
    for consumer in source:
        item = copy.copy(consumer)
        item["nominal_power_kw"] = resolve_consumer_nominal_power_kw(consumer)
        updated.append(item)
    return updated


def _binary_meter_kw(inputs: dict, nominal: float) -> float | None:
    """Binärer Verbraucher: 0/1-Merker × Nennleistung.

    Optional ``alternate_binary_power_name`` (z. B. natives Filter-Relais neben
    Gesamt-Filterstatus) — läuft, wenn mindestens ein Merker ≥ 0,5 ist.
    """
    io_name = str(inputs.get("power_name", "")).strip()
    if not io_name:
        return None
    alt_name = str(inputs.get("alternate_binary_power_name", "")).strip()
    readings: list[float | None] = [fetch_loxone_generic_value(io_name)]
    if alt_name:
        readings.append(fetch_loxone_generic_value(alt_name))
    if all(value is None for value in readings):
        return None
    if any(value is not None and float(value) >= 0.5 for value in readings):
        return round(nominal, 3)
    return 0.0


def _read_consumer_meter_kw(consumer: dict) -> float | None:
    """Reine Zähler-Messung (kW) ohne Fallback.

    None, wenn der Merker fehlt oder Loxone nicht antwortet — so lässt sich
    „gemessen" von „Fallback verwendet" unterscheiden.
    binary: Merker 0/1 × Nennleistung; power: direkter kW-Wert (≥ 0).
    """
    inputs = consumer.get("loxone_inputs") or {}
    io_name = inputs.get("power_name", "")
    if not io_name:
        return None
    signal_type = str(inputs.get("signal_type") or consumer.get("signal_type", "power")).lower()
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    if signal_type == "binary":
        return _binary_meter_kw(inputs, nominal)
    raw = fetch_loxone_generic_value(io_name)
    if raw is None:
        return None
    return round(max(0.0, float(raw)), 3)


def resolve_consumer_live_power_kw(
    consumer: dict,
    *,
    fallback_kw: float | None = None,
) -> float | None:
    """
    Aktuelle Leistung (kW) eines flexiblen Verbrauchers live aus Loxone.
    binary: Merker 0/1 × Nennleistung; power: direkter kW-Wert (≥ 0).
    """
    measured = _read_consumer_meter_kw(consumer)
    if measured is not None:
        return measured
    io_name = (consumer.get("loxone_inputs") or {}).get("power_name", "")
    if io_name:
        logger.warning(
            "Loxone: Keine Live-Leistung für '%s' (%s), Fallback %s kW",
            consumer.get("id"),
            io_name,
            fallback_kw,
        )
    return fallback_kw


FILTER_INFERENCE_TOLERANCE_KW = 0.05
SWIMSPA_FILTER_ID = "swimspa_filter"
SWIMSPA_HEATING_ID = "swimspa"


@dataclass(frozen=True)
class LiveFlexPowerResult:
    """Live-Leistungen flexibler Verbraucher: operativ (mit Fallback) vs. Chart-Ist."""

    kw: dict[str, float]
    chart_kw: dict[str, float]
    measured_ids: frozenset[str]


def _build_chart_kw(result: dict[str, float], measured_ids: set[str]) -> dict[str, float]:
    return {
        cid: round(float(result[cid]), 3)
        for cid in measured_ids
        if cid in result
    }


def _slot_in_native_filter_window(
    filter_contexts: dict[str, dict] | None,
    filter_consumer_id: str,
    slot_dt: datetime,
) -> bool:
    if not filter_contexts or slot_dt is None:
        return False
    ctx = filter_contexts.get(filter_consumer_id) or {}
    start = ctx.get("native_start_hour")
    duration = ctx.get("native_duration_hours")
    if start is None or duration is None:
        return False
    from optimizer.filter_context import slot_in_native_window

    return slot_in_native_window(slot_dt, float(start), float(duration))


def _apply_native_filter_inference(
    result: dict[str, float],
    measured_ids: set[str],
    consumers: list,
    *,
    filter_contexts: dict[str, dict] | None,
    slot_datetime: datetime | None,
) -> None:
    """Filter-Ist aus Gesamtzähler, wenn Binär-Merker 0 sind aber natives Fenster + Last passt."""
    if slot_datetime is None:
        return
    if not _slot_in_native_filter_window(
        filter_contexts, SWIMSPA_FILTER_ID, slot_datetime
    ):
        return
    if SWIMSPA_HEATING_ID not in measured_ids:
        return
    if float(result.get(SWIMSPA_FILTER_ID, 0.0) or 0.0) > 1e-9:
        return

    filter_consumer = next(
        (item for item in consumers if item.get("id") == SWIMSPA_FILTER_ID),
        None,
    )
    if filter_consumer is None:
        return
    nominal = float(filter_consumer.get("nominal_power_kw", 0.0) or 0.0)
    if nominal <= 1e-9:
        return

    total = float(result.get(SWIMSPA_HEATING_ID, 0.0) or 0.0)
    if total <= 1e-9 or abs(total - nominal) > FILTER_INFERENCE_TOLERANCE_KW:
        return

    result[SWIMSPA_FILTER_ID] = round(nominal, 3)
    result[SWIMSPA_HEATING_ID] = round(max(0.0, total - nominal), 3)
    measured_ids.add(SWIMSPA_FILTER_ID)
    logger.info(
        "Loxone: natives Filterfenster — Filter %.3f kW aus Gesamtzähler %.3f kW "
        "inferiert (Binär-Merker 0).",
        nominal,
        total,
    )


def _subtract_shared_meter_loads(
    result: dict[str, float],
    consumers: list,
    measured_ids: set[str],
) -> dict[str, float]:
    """Zieht bei gemeinsamer Leistungsmessung enthaltene Verbraucher-Anteile ab.

    Misst der ``power_name`` eines Verbrauchers die Gesamtleistung mehrerer Lasten
    am selben Zähler (z. B. SwimSpa-Heizung inkl. Filter), listet er die enthaltenen
    IDs unter ``loxone_inputs.subtract_consumer_ids``. Der Abzug wird nur angewandt,
    wenn der Gesamtwert tatsächlich vom Zähler stammt (nicht aus dem Fallback) —
    sonst würde ein bereits filterfreier Fallback-Sollwert doppelt gekürzt.
    """
    corrected = dict(result)
    for consumer in consumers:
        subtract_ids = (consumer.get("loxone_inputs") or {}).get("subtract_consumer_ids") or []
        cid = consumer["id"]
        if not subtract_ids or cid not in measured_ids or cid not in corrected:
            continue
        deduction = sum(float(result.get(sub_id, 0.0) or 0.0) for sub_id in subtract_ids)
        if deduction <= 0:
            continue
        new_value = round(max(0.0, corrected[cid] - deduction), 3)
        logger.info(
            "Loxone: '%s' Gesamtmessung %.3f kW − enthaltene Last(en) %s (%.3f kW) "
            "= %.3f kW.",
            cid,
            corrected[cid],
            list(subtract_ids),
            deduction,
            new_value,
        )
        corrected[cid] = new_value
    return corrected


def resolve_flexible_consumers_live_power(
    fallbacks: dict[str, float] | None = None,
    consumers: list | None = None,
    *,
    filter_contexts: dict[str, dict] | None = None,
    slot_datetime: datetime | None = None,
) -> LiveFlexPowerResult:
    """
    Live-Leistungen aller flexiblen Verbraucher.

    ``kw`` enthält Fallbacks für cons_data/Delivery; ``chart_kw`` nur gemessene
    (und inferierte) Werte — ohne MILP-Soll — für Chart/Log-Ist.
    """
    fallbacks = fallbacks or {}
    source = consumers if consumers is not None else config.get_flexible_consumers()
    result: dict[str, float] = {}
    measured_ids: set[str] = set()

    for consumer in source:
        cid = consumer["id"]
        fallback = float(fallbacks.get(cid, 0.0) or 0.0)
        io_name = (consumer.get("loxone_inputs") or {}).get("power_name", "")
        measured = _read_consumer_meter_kw(consumer)
        if measured is not None:
            measured_ids.add(cid)
            result[cid] = round(float(measured), 3)
            if io_name:
                logger.debug(
                    "Loxone Live-Leistung %s: %.3f kW (%s)", cid, result[cid], io_name
                )
        else:
            result[cid] = round(fallback, 3)
            if io_name:
                logger.warning(
                    "Loxone: Keine Live-Leistung für '%s' (%s), Fallback %s kW",
                    cid,
                    io_name,
                    fallback,
                )

    corrected = _subtract_shared_meter_loads(result, source, measured_ids)
    _apply_native_filter_inference(
        corrected,
        measured_ids,
        source,
        filter_contexts=filter_contexts,
        slot_datetime=slot_datetime,
    )
    chart_kw = _build_chart_kw(corrected, measured_ids)
    return LiveFlexPowerResult(
        kw=corrected,
        chart_kw=chart_kw,
        measured_ids=frozenset(measured_ids),
    )


def fetch_flexible_consumers_live_kw(
    fallbacks: dict[str, float] | None = None,
    consumers: list | None = None,
    *,
    filter_contexts: dict[str, dict] | None = None,
    slot_datetime: datetime | None = None,
) -> dict[str, float]:
    """
    Live-Leistungen aller flexiblen Verbraucher für cons_data_hourly.
    Fallback (z. B. Optimizer-Sollwerte) wenn Merker fehlt oder Loxone nicht antwortet.
    """
    return resolve_flexible_consumers_live_power(
        fallbacks,
        consumers,
        filter_contexts=filter_contexts,
        slot_datetime=slot_datetime,
    ).kw


def send_loxone_value(input_name: str, value: float) -> bool:
    """
    Sendet einen berechneten Steuerwert an einen Virtuellen Eingang des Loxone Miniservers.

    Args:
        input_name (str): Name des virtuellen Eingangs in Loxone (z.B. 'Ernie_Mode')
        value (float): Der zu setzende Wert (z.B. 1, 0, 2.5)

    Returns:
        bool: True bei Erfolg, False bei Fehlern.
    """
    url = f"http://{config.get('LOXONE_IP')}/dev/sps/io/{input_name}/{value}"
    timeout_val = config.get_global_timeout(default=5)

    try:
        response = requests.get(
            url,
            auth=_loxone_auth(),
            timeout=timeout_val,
        )
        response.raise_for_status()
        print(f"   ↳ Loxone API: {input_name} erfolgreich auf {value} gesetzt.")
        return True
    except requests.exceptions.Timeout:
        print(f"🚨 Loxone-Fehler: Timeout ({timeout_val}s) beim Senden an {input_name}.")
    except requests.exceptions.RequestException as e:
        print(f"🚨 Loxone-Fehler: Fehler beim Senden an {input_name}: {e}")
    return False


def fetch_loxone_csv_file(local_path: str = "live_consumption.csv") -> Optional[str]:
    """
    Lädt die historische CSV-Logdatei über FTP vom Miniserver herunter.
    Wird für die regelmäßige Neuerstellung des Verbrauchsprofils benötigt.

    Args:
        local_path (str): Lokaler Zielpfad für die temporär gespeicherte Datei.

    Returns:
        Optional[str]: Der lokale Dateipfad bei Erfolg, None bei Fehlern.
    """
    remote_filename = config.get("LOXONE_LOG_FILENAME")
    print(f"🌐 FTP-Verbindung: Verbinde mit Miniserver ({config.get('LOXONE_IP')})...")

    ftp = None
    try:
        ftp = FTP(config.get("LOXONE_IP"), timeout=15)
        ftp.login(user=config.get("LOXONE_USER"), passwd=config.get("LOXONE_PASS"))
        ftp.cwd("log")

        print(f"📥 FTP-Download: Downloade '{remote_filename}'...")
        with open(local_path, "wb") as local_file:
            ftp.retrbinary(f"RETR {remote_filename}", local_file.write)

        print(f"   ↳ FTP: Logdatei erfolgreich unter '{local_path}' gesichert.")
        return local_path

    except ftp_errors as e:
        print(f"🚨 Loxone-FTP-Fehler: Problem bei der FTP-Übertragung: {e}")
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
    except Exception as e:
        print(f"🚨 Loxone-FTP-Fehler: Unerwarteter Systemfehler beim FTP-Download: {e}")
    finally:
        if ftp:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass
    return None


def fetch_loxone_live_power() -> Optional[dict]:
    """
    Holt Echtzeit-Leistungswerte aus Loxone, normiert sie und prüft Vorzeichen.
    """
    pv = fetch_loxone_generic_value(config.get("LOXONE_PV_POWER_NAME"))
    battery_raw = fetch_loxone_generic_value(config.get("LOXONE_BATTERY_POWER_NAME"))
    grid_raw = fetch_loxone_generic_value(config.get("LOXONE_GRID_POWER_NAME"))

    if pv is None or grid_raw is None or battery_raw is None:
        return None

    pv = max(0.0, float(pv))
    battery = float(battery_raw)
    grid = float(grid_raw)
    house = pv + battery + grid

    return {
        "pv": round(pv, 2),
        "house": round(house, 2),
        "battery": round(battery, 2),
        "grid": round(grid, 2),
    }


def map_huawei_modbus_values(mode: int, target_power_kw: float) -> tuple[float, float, int]:
    """
    Interner Modus → (Lade-kW, Entlade-kW, Steuerbefehl).

    Steuerbefehl (Huawei-Register 47100): 0=Automatik, 1=Zwangsladen/Entladesperre, 2=Zwangs-Entladen.
    """
    if mode == 1:
        return target_power_kw, 0.0, 1
    if mode == 2:
        return 0.0, 0.0, 1
    if mode == 3:
        return 0.0, target_power_kw, 2
    return 0.0, 0.0, 0


def flex_consumer_enable_value(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
) -> int | None:
    """Freigabe 0/1 für einen flexiblen Verbraucher (None wenn kein enable_name)."""
    enable_name = (consumer.get("loxone_outputs") or {}).get("enable_name", "")
    if not enable_name:
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
    """kW-Sollwert für Loxone (None wenn kein power_setpoint_name)."""
    from optimizer.consumer_power import loxone_control_outputs

    setpoint_name = (consumer.get("loxone_outputs") or {}).get("power_setpoint_name", "")
    if not setpoint_name:
        return None

    cid = consumer["id"]
    planned_kw = _effective_consumer_power_kw(consumer, consumer_powers, charging_contexts, cid)
    pv_follow = int((consumer_pv_follow or {}).get(cid, 0) or 0)
    setpoint_kw, _ = loxone_control_outputs(consumer, planned_kw, pv_follow)
    return setpoint_kw


def flex_consumer_pv_follow_value(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> int | None:
    """PV-Überschuss-Modus 0/1 für Loxone (None wenn kein pv_follow_name)."""
    from optimizer.consumer_power import loxone_control_outputs

    pv_follow_name = (consumer.get("loxone_outputs") or {}).get("pv_follow_name", "")
    if not pv_follow_name:
        return None

    cid = consumer["id"]
    planned_kw = _effective_consumer_power_kw(consumer, consumer_powers, charging_contexts, cid)
    pv_follow = int((consumer_pv_follow or {}).get(cid, 0) or 0)
    _, pv_out = loxone_control_outputs(consumer, planned_kw, pv_follow)
    return pv_out


def _skip_flexible_consumer_output(
    consumer: dict,
    charging_contexts: dict[str, dict],
) -> bool:
    ctx = charging_contexts.get(consumer["id"]) or {}
    return bool(ctx.get("skip_loxone_output"))


def _flexible_consumer_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> dict[str, float]:
    """Berechnet Loxone-Merker → Wert für einen flexiblen Verbraucher (ohne HTTP)."""
    outputs = consumer.get("loxone_outputs") or {}
    pv_follow_name = str(outputs.get("pv_follow_name", "")).strip()

    if _skip_flexible_consumer_output(consumer, charging_contexts):
        if pv_follow_name:
            logger.info(
                "Flex consumer %s -> Sofort laden: %s=0 (kein Lade-Sollwert von Earnie).",
                consumer["name"],
                pv_follow_name,
            )
            return {pv_follow_name: 0.0}
        logger.info(
            "Flex consumer %s -> keine Steuerung (Sofort laden aktiv, Loxone regelt).",
            consumer["name"],
        )
        return {}

    enable_name = outputs.get("enable_name", "")
    setpoint_name = outputs.get("power_setpoint_name", "")
    cid = consumer["id"]
    values: dict[str, float] = {}

    if setpoint_name:
        setpoint_kw = flex_consumer_power_setpoint_kw(
            consumer, consumer_powers, charging_contexts, consumer_pv_follow
        )
        if setpoint_kw is None:
            return values
        values[str(setpoint_name)] = float(setpoint_kw)
        pv_out = flex_consumer_pv_follow_value(
            consumer, consumer_powers, charging_contexts, consumer_pv_follow
        )
        if pv_follow_name and pv_out is not None:
            values[str(pv_follow_name)] = float(pv_out)
        planned_kw = max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0))
        logger.info(
            "Flex consumer %s -> Soll=%.2f kW, pv_follow=%s "
            "(geplant %.2f kW, Loxone: %s%s)",
            consumer["name"],
            setpoint_kw,
            pv_out if pv_follow_name else "n/a",
            planned_kw,
            setpoint_name,
            f", {pv_follow_name}" if pv_follow_name else "",
        )
        return values

    if not enable_name:
        return values

    enabled = flex_consumer_enable_value(consumer, consumer_powers, charging_contexts)
    if enabled is None:
        return values

    values[str(enable_name)] = float(enabled)
    power_kw = max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0))
    logger.info(
        "Flex consumer %s -> Freigabe=%s (optimiert %.2f kW, Loxone: %s)",
        consumer["name"],
        enabled,
        power_kw,
        enable_name,
    )
    return values


def _write_flexible_consumer_output(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    snapshot: dict[str, float] | None,
    consumer_pv_follow: dict[str, int] | None = None,
    *,
    send: bool,
) -> None:
    """Schreibt Freigabe/kW-Sollwert/pv_follow an Loxone und/oder in den Snapshot."""
    values = _flexible_consumer_output_values(
        consumer, consumer_powers, charging_contexts, consumer_pv_follow
    )
    if send:
        for io_name, value in values.items():
            send_loxone_value(io_name, value)
    if snapshot is not None:
        snapshot.update(values)


def build_sent_loxone_snapshot(
    mode: int,
    target_power_kw: float,
    target_soc: float,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> dict[str, float]:
    """Alle an Loxone gesendeten Steuerwerte: Merkername → Zahl."""
    charge_kw, discharge_kw, control_cmd = map_huawei_modbus_values(mode, target_power_kw)
    contexts = charging_contexts or {}
    snapshot: dict[str, float] = {}

    for cfg_name, value in (
        (config.get("LOXONE_TARGET_SOC_NAME"), float(target_soc)),
        (config.get("LOXONE_TARGET_CHARGE_POWER_NAME"), charge_kw),
        (config.get("LOXONE_TARGET_DISCHARGE_POWER_NAME"), discharge_kw),
        (config.get("LOXONE_CONTROL_CMD_NAME"), float(control_cmd)),
    ):
        if cfg_name:
            snapshot[str(cfg_name)] = value

    for consumer in config.get_flexible_consumers(optimizer_only=True):
        _write_flexible_consumer_output(
            consumer, consumer_powers, contexts, snapshot, consumer_pv_follow, send=False
        )

    return snapshot


def send_huawei_modbus_states(mode: int, target_power_kw: float, target_soc: float):
    """Übersetzt Optimierungsmodi und schreibt Huawei-Steuerwerte an Loxone."""
    charge_kw, discharge_kw, control_cmd = map_huawei_modbus_values(mode, target_power_kw)

    logger.info(
        "Sending Modbus Mapping -> SoC: %s, Ladung: %s kW, Entladung: %s kW, Cmd: %s",
        target_soc,
        charge_kw,
        discharge_kw,
        control_cmd,
    )

    send_loxone_value(config.get("LOXONE_TARGET_SOC_NAME"), target_soc)
    send_loxone_value(config.get("LOXONE_TARGET_CHARGE_POWER_NAME"), charge_kw)
    send_loxone_value(config.get("LOXONE_TARGET_DISCHARGE_POWER_NAME"), discharge_kw)
    send_loxone_value(config.get("LOXONE_CONTROL_CMD_NAME"), control_cmd)


def send_flexible_consumer_states(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumer_pv_follow: dict[str, int] | None = None,
) -> None:
    """Sendet Freigabe (0/1), kW-Sollwert und optional pv_follow an Loxone."""
    contexts = charging_contexts or {}
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        _write_flexible_consumer_output(
            consumer, consumer_powers, contexts, None, consumer_pv_follow, send=True
        )


def _read_optional_temp_c(io_name: str) -> float | None:
    io_name = str(io_name or "").strip()
    if not io_name:
        return None
    return fetch_loxone_generic_value(io_name)


def fetch_thermal_readings(consumer: dict) -> dict:
    """
    Liest Ist-/Soll-/Außen-Temperatur und Toleranz für thermal_control.
    Config-Fallbacks werden nur genutzt, wenn der jeweilige Merker leer ist.
    """
    thermal = consumer.get("thermal_control") or {}
    lox = thermal.get("loxone") or {}
    missing: list[str] = []

    actual = _read_optional_temp_c(lox.get("actual_temp_name", ""))
    if actual is None:
        missing.append("actual_temp_name")

    setpoint = _read_optional_temp_c(lox.get("setpoint_temp_name", ""))
    if setpoint is None:
        if thermal.get("setpoint_c") is None:
            missing.append("setpoint_temp_name")

    ambient = _read_optional_temp_c(lox.get("ambient_temp_name", ""))
    if ambient is None:
        missing.append("ambient_temp_name")

    tolerance = _read_optional_temp_c(lox.get("tolerance_c_name", ""))
    if tolerance is None:
        if thermal.get("tolerance_c") is None:
            missing.append("tolerance_c_name")

    return {
        "actual_c": actual,
        "setpoint_c": setpoint,
        "ambient_c": ambient,
        "tolerance_c": tolerance,
        "missing_signals": missing,
    }

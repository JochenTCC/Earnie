# loxone_client.py
import os
from ftplib import FTP, all_errors as ftp_errors
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

import config
import logging

logger = logging.getLogger(__name__)

_UNIT_SUFFIXES = (
    ("kWh", "kwh"),
    ("kW", "kw"),
    ("W", "w"),
    ("%", "pct"),
    ("A", "a"),
)
_DEFAULT_CHARGING_VOLTAGE_V = 230.0


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


def _ampere_to_kw(amps: float, *, voltage_v: float, phases: int) -> float:
    return amps * voltage_v * max(1, phases) / 1000.0


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

    if unit == "a":
        voltage_v = float(lox.get("nominal_power_voltage_v", _DEFAULT_CHARGING_VOLTAGE_V))
        phases = int(lox.get("nominal_power_phases", 1))
        live = _ampere_to_kw(value, voltage_v=voltage_v, phases=phases)
    else:
        live = value

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


def resolve_consumer_live_power_kw(
    consumer: dict,
    *,
    fallback_kw: float | None = None,
) -> float | None:
    """
    Aktuelle Leistung (kW) eines flexiblen Verbrauchers live aus Loxone.
    binary: Merker 0/1 × Nennleistung; power: direkter kW-Wert (≥ 0).
    """
    io_name = (consumer.get("loxone_inputs") or {}).get("power_name", "")
    if not io_name:
        return fallback_kw

    raw = fetch_loxone_generic_value(io_name)
    if raw is None:
        logger.warning(
            "Loxone: Keine Live-Leistung für '%s' (%s), Fallback %s kW",
            consumer.get("id"),
            io_name,
            fallback_kw,
        )
        return fallback_kw

    inputs = consumer.get("loxone_inputs") or {}
    signal_type = str(inputs.get("signal_type") or consumer.get("signal_type", "power")).lower()
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    if signal_type == "binary":
        return round(nominal if float(raw) >= 0.5 else 0.0, 3)

    return round(max(0.0, float(raw)), 3)


def fetch_flexible_consumers_live_kw(
    fallbacks: dict[str, float] | None = None,
    consumers: list | None = None,
) -> dict[str, float]:
    """
    Live-Leistungen aller flexiblen Verbraucher für cons_data_hourly.
    Fallback (z. B. Optimizer-Sollwerte) wenn Merker fehlt oder Loxone nicht antwortet.
    """
    fallbacks = fallbacks or {}
    source = consumers if consumers is not None else config.get_flexible_consumers()
    result: dict[str, float] = {}

    for consumer in source:
        cid = consumer["id"]
        fallback = float(fallbacks.get(cid, 0.0) or 0.0)
        live = resolve_consumer_live_power_kw(consumer, fallback_kw=fallback)
        result[cid] = round(float(live if live is not None else fallback), 3)
        io_name = (consumer.get("loxone_inputs") or {}).get("power_name", "")
        if io_name and live is not None:
            logger.debug(
                "Loxone Live-Leistung %s: %.3f kW (%s)",
                cid,
                result[cid],
                io_name,
            )

    return result


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


def _flexible_consumer_output_values(
    consumer: dict,
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict],
    consumer_pv_follow: dict[str, int] | None = None,
) -> dict[str, float]:
    """Berechnet Loxone-Merker → Wert für einen flexiblen Verbraucher (ohne HTTP)."""
    outputs = consumer.get("loxone_outputs") or {}
    enable_name = outputs.get("enable_name", "")
    setpoint_name = outputs.get("power_setpoint_name", "")
    pv_follow_name = outputs.get("pv_follow_name", "")
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

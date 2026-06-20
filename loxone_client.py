# loxone_client.py
import os
from ftplib import FTP, all_errors as ftp_errors
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

import config
import logging

logger = logging.getLogger(__name__)

_UNIT_SUFFIXES = ("%", "kWh", "kW", "W")


def _loxone_auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(config.get("LOXONE_USER"), config.get("LOXONE_PASS"))


def _loxone_jdev_url(io_name: str) -> str:
    return f"http://{config.get('LOXONE_IP')}/jdev/sps/io/{io_name}"


def _parse_loxone_numeric(raw_value: str) -> float:
    clean_value = str(raw_value)
    for suffix in _UNIT_SUFFIXES:
        clean_value = clean_value.replace(suffix, "")
    return float(clean_value.strip())


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
    io_name = (sched.get("loxone") or {}).get("nominal_power_kw_name", "")
    if not io_name:
        return fallback
    live = fetch_loxone_generic_value(io_name)
    if live is None or live <= 0:
        logger.warning(
            "Loxone: Keine gültige Nennleistung für '%s' (%s), Fallback %.2f kW",
            consumer.get("id"),
            io_name,
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


def send_huawei_modbus_states(mode: int, target_power_kw: float, target_soc: float):
    """
    Übersetzt die Ernie-Optimierungsmodi in die vier exakten Huawei-Modbus-Steuerwerte
    und überträgt sie an die virtuellen Eingänge des Loxone Miniservers.
    """
    if mode == 1:
        forced_power_kw = target_power_kw
        control_cmd = 1
    elif mode == 2:
        forced_power_kw = 0
        control_cmd = 1
    else:
        forced_power_kw = 0
        control_cmd = 0

    logger.info(
        "Sending Modbus Mapping -> SoC: %d, Power: %d W, Cmd: %d",
        target_soc,
        forced_power_kw,
        control_cmd,
    )

    send_loxone_value("Ernie_Ziel_SoC", target_soc)
    send_loxone_value("Ernie_Ziel_Leistung", forced_power_kw)
    send_loxone_value("Ernie_Steuerbefehl", control_cmd)


def send_flexible_consumer_states(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
) -> None:
    """Sendet Freigabe-Signale (0/1) der flexiblen Verbraucher an Loxone."""
    charging_contexts = charging_contexts or {}
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        enable_name = (consumer.get("loxone_outputs") or {}).get("enable_name", "")
        if not enable_name:
            continue

        cid = consumer["id"]
        power_kw = max(0.0, float(consumer_powers.get(cid, 0.0) or 0.0))
        ctx = charging_contexts.get(cid)
        if ctx is not None and not ctx.get("active", True):
            power_kw = 0.0

        enabled = 1 if power_kw > 1e-3 else 0
        send_loxone_value(enable_name, enabled)
        logger.info(
            "Flex consumer %s -> Freigabe=%s (optimiert %.2f kW, Loxone: %s)",
            consumer["name"],
            enabled,
            power_kw,
            enable_name,
        )

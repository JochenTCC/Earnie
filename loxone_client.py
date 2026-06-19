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


def fetch_loxone_generic_value(io_name: str) -> Optional[float]:
    """Holt einen einzelnen analogen Wert live aus dem Loxone Miniserver via HTTP-REST."""
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
        if not raw_value:
            logger.warning("Loxone: Kein value für '%s'", io_name)
            return None
        return _parse_loxone_numeric(raw_value)
    except requests.exceptions.Timeout:
        logger.error(
            "Loxone: Timeout (%ss) beim Abrufen von '%s'", timeout_val, io_name
        )
    except requests.exceptions.RequestException as e:
        logger.error("Loxone: Netzwerkfehler bei '%s': %s", io_name, e)
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Loxone: Parsing-Fehler bei '%s': %s", io_name, e)
    return None


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

# loxone_client.py
import os
from ftplib import FTP, all_errors as ftp_errors
from typing import Optional
import requests
from requests.auth import HTTPBasicAuth
import config
import logging

logger = logging.getLogger(__name__)

def fetch_loxone_soc() -> Optional[float]:
    """
    Holt den aktuellen Batterie-SoC live aus dem Loxone Miniserver via HTTP-REST.
    
    Returns:
        Optional[float]: Der SoC in % (0.0 bis 100.0) oder None im Fehlerfall.
    """
    url = f"http://{config.get('LOXONE_IP')}/jdev/sps/io/{config.get('LOXONE_SOC_NAME')}"
    
    # Timeout aus der Config ziehen, falls vorhanden, sonst Fallback auf 5s
    timeout_val = config.get_global_timeout(default=5)
    
    try:
        response = requests.get(
            url, 
            auth=HTTPBasicAuth(config.get('LOXONE_USER'), config.get('LOXONE_PASS')),
            timeout=timeout_val
        )
        response.raise_for_status()
        
        # Parsing der Loxone JSON-Struktur
        data = response.json()
        raw_value = data.get('LL', {}).get('value', '')
        
        if not raw_value:
            print(f"⚠️ Loxone-Warnung: Keine Daten im 'value'-Feld für {config.get('LOXONE_SOC_NAME')} gefunden.")
            return None
            
        # Bereinigung (Loxone liefert oft Strings wie "85%" oder "85.0")
        clean_value = raw_value.replace('%', '').strip()
        return float(clean_value)
        
    except requests.exceptions.Timeout:
        print(f"🚨 Loxone-Fehler: Timeout ({timeout_val}s) beim Abrufen des SoC ({config.get('LOXONE_SOC_NAME')}).")
    except requests.exceptions.RequestException as e:
        print(f"🚨 Loxone-Fehler: Netzwerkfehler beim REST-Abruf des SoC: {e}")
    except (ValueError, KeyError, TypeError) as e:
        print(f"🚨 Loxone-Fehler: Parsing-Fehler der JSON-Antwort von Loxone: {e}")
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
            auth=HTTPBasicAuth(config.get('LOXONE_USER'), config.get('LOXONE_PASS')),
            timeout=timeout_val
        )
        response.raise_for_status()
        print(f"   ↳ Loxone API: {input_name} erfolgreich auf {value} gesetzt.")
        return True
    except requests.exceptions.Timeout:
        print(f"🚨 Loxone-Fehler: Timeout ({timeout_val}s) beim Senden an {input_name}.")
    except requests.exceptions.RequestException as e:
        print(f"🚨 Loxone-Fehler: Fehler beim Senden an {input_name}: {e}")
    return False

def fetch_loxone_csv_file(local_path: str = 'live_consumption.csv') -> Optional[str]:
    """
    Lädt die historische CSV-Logdatei über FTP vom Miniserver herunter.
    Wird für die regelmäßige Neuerstellung des Verbrauchsprofils benötigt.
    
    Args:
        local_path (str): Lokaler Zielpfad für die temporär gespeicherte Datei.
        
    Returns:
        Optional[str]: Der lokale Dateipfad bei Erfolg, None bei Fehlern.
    """
    remote_filename = config.get('LOXONE_LOG_FILENAME')
    print(f"🌐 FTP-Verbindung: Verbinde mit Miniserver ({config.get('LOXONE_IP')})...")
    
    ftp = None
    try:
        ftp = FTP(config.get('LOXONE_IP'), timeout=15)
        ftp.login(user=config.get('LOXONE_USER'), passwd=config.get('LOXONE_PASS'))
        ftp.cwd('log')
        
        print(f"📥 FTP-Download: Downloade '{remote_filename}'...")
        with open(local_path, 'wb') as local_file:
            ftp.retrbinary(f"RETR {remote_filename}", local_file.write)
            
        print(f"   ↳ FTP: Logdatei erfolgreich unter '{local_path}' gesichert.")
        return local_path
        
    except ftp_errors as e:
        print(f"🚨 Loxone-FTP-Fehler: Problem bei der FTP-Übertragung: {e}")
        # Aufräumen: Teilweise geschriebene, korrupte Datei löschen
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
                    pass  # Fail-silent beim Schließen der Verbindung
    return None

def fetch_loxone_pv_counter() -> Optional[float]:
    """
    Holt den aktuellen kumulierten PV-Gesamtertrag (Zählerstand in kWh) live aus dem Loxone Miniserver.
    Säubert den String von Einheiten wie 'kWh', um einen validen Float zurückzugeben.
    """
    url = f"http://{config.get('LOXONE_IP')}/jdev/sps/io/{config.get('LOXONE_PV_COUNTER_NAME')}"
    timeout_val = config.get_global_timeout(default=5)
    
    try:
        response = requests.get(
            url, 
            auth=HTTPBasicAuth(config.get('LOXONE_USER'), config.get('LOXONE_PASS')),
            timeout=timeout_val
        )
        response.raise_for_status()
        data = response.json()
        raw_value = data.get('LL', {}).get('value', '')
        
        if not raw_value:  # Erreicht so auch None oder leere Strings sauberer
            print(f"⚠️ Loxone-Warnung: Keine Daten im 'value'-Feld für {config.get('LOXONE_PV_COUNTER_NAME')} gefunden.")
            return None
            
        # Bereinigung: Entfernt 'kWh' und schneidet überschüssige Leerzeichen ab
        clean_value = raw_value.replace('kWh', '').strip()
        
        return float(clean_value)
        
    except requests.exceptions.Timeout:
        print(f"🚨 Loxone-Fehler: Timeout ({timeout_val}s) beim Abrufen des PV-Zählerstands ({config.get('LOXONE_PV_COUNTER_NAME')}).")
    except requests.exceptions.RequestException as e:
        print(f"🚨 Loxone-Fehler: Netzwerkfehler beim REST-Abruf des PV-Zählerstands: {e}")
    except (ValueError, KeyError, TypeError) as e:
        print(f"🚨 Loxone-Fehler: Parsing-Fehler des PV-Zählerstands (Rohwert: '{raw_value}'): {e}")
        
    return None

def fetch_loxone_generic_value(io_name: str) -> Optional[float]:
    """Holt einen einzelnen analogen Wert live aus dem Loxone Miniserver via HTTP-REST."""
    url = f"http://{config.get('LOXONE_IP')}/jdev/sps/io/{io_name}"
    timeout_val = config.get_global_timeout(default=5)
    
    try:
        response = requests.get(
            url, 
            auth=HTTPBasicAuth(config.get('LOXONE_USER'), config.get('LOXONE_PASS')),
            timeout=timeout_val
        )
        response.raise_for_status()
        data = response.json()
        raw_value = data.get('LL', {}).get('value', '')
        
        if not raw_value:
            return None
            
        # Bereinigung von Einheiten falls Loxone diese mitsendet
        clean_value = raw_value.replace('%', '').replace('kW', '').replace('W', '').strip()
        return float(clean_value)
    except Exception as e:
        logger.error(f"🚨 Loxone-Fehler beim Abrufen von '{io_name}': {e}")
        return None

def fetch_loxone_live_power() -> Optional[dict]:
    """
    Holt alle Echtzeit-Leistungswerte aus Loxone und bereitet sie für das Sankey-Diagramm vor.
    Erwartet Werte standardmäßig in kW.
    """
    pv = fetch_loxone_generic_value(config.get('LOXONE_PV_POWER_NAME'))
    house_raw = fetch_loxone_generic_value(config.get('LOXONE_HOUSE_POWER_NAME'))
    battery = fetch_loxone_generic_value(config.get('LOXONE_BATTERY_POWER_NAME'))
    grid = fetch_loxone_generic_value(config.get('LOXONE_GRID_POWER_NAME'))
    
    # Kritische Basiswerte prüfen
    if pv is None or house_raw is None or battery is None:
        return None
        
    # Vorzeichen-Harmonisierung:
    # 1. Hausverbrauch wird im Sankey intern negativ erwartet (Verbrauch)
    house = -abs(house_raw)
    
    # 2. Wenn der Netz-Wert fehlt/Fehler wirft, berechnen wir ihn mathematisch als Fallback
    if grid is None:
        grid = -pv - house - battery
        
    return {
        "pv": round(pv, 2),
        "house": round(house, 2),
        "battery": round(battery, 2),
        "grid": round(grid, 2)
    }

def send_huawei_modbus_states(mode: int, target_power_kw: float, target_soc: float):
    """
    Übersetzt die Ernie-Optimierungsmodi in die vier exakten Huawei-Modbus-Steuerwerte
    und überträgt sie an die virtuellen Eingänge des Loxone Miniservers.
    """
    # 2. Modus-Übersetzung anwenden
    if mode == 1:  # Zwangsladen aus dem Netz
        forced_power_kw = target_power_kw  
        control_cmd = 1    # 1 = Charge (Laden)

    elif mode == 2:  # Entladesperre (Entladen blockieren, PV-Laden erlauben)
        forced_power_kw = 0 # 0 Watt Netzbezug erzwingen
        control_cmd = 1    # Laden mit 0W sperrt das Entladen, lässt aber PV-Überschuss zu
    else:
        forced_power_kw = 0 # Im Automatikmodus wird die Leistung dynamisch durch den Miniserver geregelt
        control_cmd = 0    # 0 = Automatikbetrieb (Miniserver entscheidet basierend auf Echtzeitdaten)  

    # 3. Werte aktiv an Loxone übertragen
    logger.info(
        "Sending Modbus Mapping -> SoC: %d, Power: %d W, Cmd: %d",
        target_soc, forced_power_kw, control_cmd
    )

    send_loxone_value("Ernie_Ziel_SoC", target_soc)
    send_loxone_value("Ernie_Ziel_Leistung", forced_power_kw)
    send_loxone_value("Ernie_Steuerbefehl", control_cmd)
# loxone_client.py
import os
from ftplib import FTP, all_errors as ftp_errors
from typing import Optional
import requests
from requests.auth import HTTPBasicAuth
import config

def fetch_loxone_soc() -> Optional[float]:
    """
    Holt den aktuellen Batterie-SoC live aus dem Loxone Miniserver via HTTP-REST.
    
    Returns:
        Optional[float]: Der SoC in % (0.0 bis 100.0) oder None im Fehlerfall.
    """
    url = f"http://{config.LOXONE_IP}/jdev/sps/io/{config.LOXONE_SOC_NAME}"
    
    # Timeout aus der Config ziehen, falls vorhanden, sonst Fallback auf 5s
    timeout_val = getattr(config, 'GLOBAL_TIMEOUT', 5)
    
    try:
        response = requests.get(
            url, 
            auth=HTTPBasicAuth(config.LOXONE_USER, config.LOXONE_PASS),
            timeout=timeout_val
        )
        response.raise_for_status()
        
        # Parsing der Loxone JSON-Struktur
        data = response.json()
        raw_value = data.get('LL', {}).get('value', '')
        
        if not raw_value:
            print(f"⚠️ Loxone-Warnung: Keine Daten im 'value'-Feld für {config.LOXONE_SOC_NAME} gefunden.")
            return None
            
        # Bereinigung (Loxone liefert oft Strings wie "85%" oder "85.0")
        clean_value = raw_value.replace('%', '').strip()
        return float(clean_value)
        
    except requests.exceptions.Timeout:
        print(f"🚨 Loxone-Fehler: Timeout ({timeout_val}s) beim Abrufen des SoC ({config.LOXONE_SOC_NAME}).")
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
    url = f"http://{config.LOXONE_IP}/dev/sps/io/{input_name}/{value}"
    timeout_val = getattr(config, 'GLOBAL_TIMEOUT', 5)
    
    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(config.LOXONE_USER, config.LOXONE_PASS),
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
    remote_filename = getattr(config, 'LOXONE_LOG_FILENAME', 'Verbrauch.csv')
    print(f"🌐 FTP-Verbindung: Verbinde mit Miniserver ({config.LOXONE_IP})...")
    
    ftp = None
    try:
        ftp = FTP(config.LOXONE_IP, timeout=15)
        ftp.login(user=config.LOXONE_USER, passwd=config.LOXONE_PASS)
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
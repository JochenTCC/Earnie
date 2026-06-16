# config.py
import os
import json
from dotenv import load_dotenv

# Lädt die .env Datei falls vorhanden
load_dotenv()

# =========================================================================
# STATISCHE KONFIGURATIONEN (Unverändert)
# =========================================================================

# API Konfiguration Awattar
AWATTAR_URL = "https://api.awattar.at/v1/marketdata"

# Globaler HTTP-Timeout in Sekunden für alle API-Anfragen
GLOBAL_TIMEOUT = 10

# Loxone Konfiguration (Sensible Daten und Infrastruktur kommen aus der .env)
LOXONE_IP = os.getenv("LOXONE_IP", "192.168.178.1")
LOXONE_USER = os.getenv("LOXONE_USER", "Fallback_User")
LOXONE_PASS = os.getenv("LOXONE_PASS", "Fallback_Pass")

LOXONE_SOC_NAME = "B004-Battery_SOC"
LOXONE_PV_COUNTER_NAME = "48 - Accumulated energy yield"  
LOXONE_LOG_FILENAME = 'Verbrauch.csv'
PV_TUNING_LOG_FILE = "pv_accuracy_log.csv"

# PV-ANLAGEN PARAMETER (Statischer Teil)
LATITUDE = 47.404          
LONGITUDE = 9.743          


# =========================================================================
# DYNAMISCHE PARAMETER (Werden live aus runtime_settings.json gelesen)
# =========================================================================

SETTINGS_PATH = "runtime_settings.json"

# Standardwerte (Fallbacks), falls die JSON-Datei noch nicht existiert
_DEFAULTS = {
    "K_PUSH": 3.7,
    "PV_TILT": 18,
    "PV_AZIMUTH": 28,
    "PV_KWP": 9.4
}

def _get_runtime_setting(name: str):
    """Liest einen Wert live aus der JSON-Datei oder gibt den Standardwert zurück."""
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if name in data:
                    return data[name]
        except Exception:
            # Bei Fehlern (z.B. temporärer Schreibkonflikt durch die UI) Fallback auf Default
            pass
    return _DEFAULTS[name]

def __getattr__(name: str):
    """
    Magic-Function auf Modulebene: Wird automatisch aufgerufen, wenn ein 
    Attribut (z.B. config.PV_TILT) im Modul nicht statisch existiert.
    """
    if name in _DEFAULTS:
        return _get_runtime_setting(name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
# pv_tuner.py (Neu erstellen)
import json
import logging
import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import config
import loxone_client
from file_metadata import PV_COUNTER_STATE_SCHEMA, read_schema_version, stamp_payload, strip_metadata

logger = logging.getLogger(__name__)

LOG_FILE = config.get('PV_TUNING_LOG_FILE')
STATE_FILE = "pv_counter_state.json"

def _save_state_atomic(file_path: str, data: dict):
    """
    Schreibt Daten direkt in die JSON-Datei (Docker Bind-Mount kompatibel).
    Nutzt das direkte Überschreiben ('w'), damit die Inode für Docker intakt bleibt.
    """
    payload = stamp_payload(strip_metadata(data), schema_version=PV_COUNTER_STATE_SCHEMA)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)
    except Exception as e:
        logger.error(f"🚨 Fehler beim Schreiben der State-Datei {file_path}: {e}")
        raise e

def log_pv_comparison(forecasted_kw: float, actual_kw: float):
    """
    Schreibt den prognostizierten und den echten PV-Wert der aktuellen Stunde in die CSV.
    """
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    
    data = {
        "Timestamp": [now.strftime("%Y-%m-%d %H:%M:%S")],
        "Hour": [now.hour],
        "Forecasted_kW": [round(forecasted_kw, 3)],
        "Actual_kW": [round(actual_kw, 3)]
    }
    df_new = pd.DataFrame(data)
    
    file_exists = os.path.exists(LOG_FILE)
    df_new.to_csv(LOG_FILE, mode='a', index=False, sep=';', header=not file_exists)

def get_pv_delta_and_update() -> Optional[float]:
    """
    Holt den aktuellen PV-Zählerstand, berechnet das Delta zur vorherigen Stunde
    und aktualisiert den Zustand atomar.
    """
    current_total_pv = loxone_client.fetch_loxone_generic_value(
        config.get("LOXONE_PV_COUNTER_NAME")
    )
    if current_total_pv is None:
        logger.error("🚨 Fehler beim Abrufen des PV-Zählerstands von Loxone. Tuning ausgesetzt.")
        return None

    # Falls die Datei nicht existiert oder leer (0 Bytes) ist, initialisieren
    if not os.path.exists(STATE_FILE) or os.path.getsize(STATE_FILE) == 0:
        initial_state = {
            "last_total_pv": current_total_pv,
            "last_updated": datetime.now().isoformat()
        }
        try:
            _save_state_atomic(STATE_FILE, initial_state)
            logger.info("⏳ Erststart-Wert erfolgreich atomar gesichert. Das Feintuning wird für diese Stunde ausgesetzt.")
        except Exception as e:
            logger.exception(f"🚨 Fehler beim Erstellen der State-Datei: {e}")
        return None

    # Bestehenden Zustand laden
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        schema_version = read_schema_version(state, default=1)
        if schema_version > PV_COUNTER_STATE_SCHEMA:
            logger.warning(
                "pv_counter_state: neuere Schema-Version %s (aktuell %s) – lese best effort",
                schema_version,
                PV_COUNTER_STATE_SCHEMA,
            )
        state = strip_metadata(state)
    except Exception as e:
        logger.exception(f"🚨 Fehler beim Lesen von pv_counter_state.json: {e}")
        return None

    last_total_pv = state.get("last_total_pv", current_total_pv)
    
    # Delta (realer Stundenertrag) berechnen
    pv_delta = current_total_pv - last_total_pv
    
    # Plausibilitätsprüfung
    if pv_delta < 0:
        logger.warning(f"⚠️ Negatives PV-Delta festgestellt ({pv_delta:.3f} kWh). Setze Zustand zurück.")
        pv_delta = 0.0

    # Zustand für die nächste Stunde aktualisieren
    state["last_total_pv"] = current_total_pv
    state["last_updated"] = datetime.now().isoformat()
    
    # Zustand atomar zurückspeichern
    try:
        _save_state_atomic(STATE_FILE, state)
        logger.info(f"💾 PV-Zustand erfolgreich atomar aktualisiert. Delta: {pv_delta:.3f} kWh")
    except Exception as e:
        logger.exception(f"🚨 Fehler beim Aktualisieren der State-Datei: {e}")
        
    return pv_delta

def calculate_tuning_factor(days_back: int = 14) -> float:
    """
    Analysiert die Daten der letzten X Tage und berechnet den Korrekturfaktor.
    Faktor > 1.0 -> API unterschätzt die Anlage (reale PV ist höher).
    Faktor < 1.0 -> API überschätzt die Anlage (reale PV ist niedriger).
    """
    if not os.path.exists(LOG_FILE):
        return 1.0  # Kein Log vorhanden -> Neutraler Faktor
        
    try:
        df = pd.read_csv(LOG_FILE, sep=';')
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        
        # Nur Daten der letzten X Tage betrachten
        cutoff_date = datetime.now() - timedelta(days=days_back)
        df_filtered = df[df['Timestamp'] >= cutoff_date].copy()
        
        # Wichtig: Nachtstunden und extremes Rauschen filtern (z.B. Forecast nahe 0), 
        # da Divisionen durch Minimalwerte den Faktor verzerren.
        df_filtered = df_filtered[df_filtered['Forecasted_kW'] > 0.1]
        
        if len(df_filtered) < 24: 
            # Zu wenig Datenpunkte für eine valide statistische Aussage
            return 1.0
            
        total_forecast = df_filtered['Forecasted_kW'].sum()
        total_actual = df_filtered['Actual_kW'].sum()
        
        if total_forecast == 0:
            return 1.0
            
        raw_factor = total_actual / total_forecast
        
        # Sicherheits-Leitplanken (Clipping): Schützt vor absurden Anpassungen
        # z.B. wenn die Module tagelang im Winter unter Schnee begraben waren.
        tuned_factor = max(0.5, min(1.5, raw_factor))
        return round(tuned_factor, 3)
        
    except Exception as e:
        print(f"⚠️ Fehler bei der Berechnung des PV-Tuning-Faktors: {e}")
        return 1.0
    

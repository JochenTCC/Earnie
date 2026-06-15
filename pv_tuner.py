# pv_tuner.py (Neu erstellen)
import os
import pandas as pd
from datetime import datetime, timedelta
import config

LOG_FILE = getattr(config, 'PV_TUNING_LOG_FILE', 'pv_accuracy_log.csv')

def log_pv_comparison(forecasted_kw: float, actual_kw: float):
    """
    Schreibt den prognostizierten und den echten PV-Wert der aktuellen Stunde in die CSV.
    """
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    
    # Datenzeile vorbereiten
    data = {
        "Timestamp": [now.strftime("%Y-%m-%d %H:%M:%S")],
        "Hour": [now.hour],
        "Forecasted_kW": [round(forecasted_kw, 3)],
        "Actual_kW": [round(actual_kw, 3)]
    }
    df_new = pd.DataFrame(data)
    
    # Falls Datei noch nicht existiert, mit Header schreiben, sonst anhängen
    file_exists = os.path.exists(LOG_FILE)
    df_new.to_csv(LOG_FILE, mode='a', index=False, sep=';', header=not file_exists)

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
    
STATE_FILE = "pv_counter_state.json"

def get_pv_delta_and_update() -> float | None:
    """
    Liest den aktuellen Gesamtzählerstand der PV-Anlage aus Loxone,
    vergleicht ihn mit dem gespeicherten Wert aus der vorherigen Stunde,
    berechnet das reale Ertrags-Delta und aktualisiert den Zustand 
    persistent in der pv_counter_state.json.
    
    Returns:
        Optional[float]: Das berechnete Ertrags-Delta in kWh oder None beim Erststart/Fehler.
    """
    # Live-Zählerstand über das loxone_client-Modul abrufen
    current_total_pv = loxone_client.fetch_loxone_pv_counter()
    if current_total_pv is None:
        logger.warning("⚠️ Abbruch des PV-Abgleichs: Gesamtzählerstand konnte nicht von Loxone geladen werden.")
        return None

    # Falls die State-Datei noch nicht existiert (Erststart des Features)
    if not os.path.exists(STATE_FILE):
        logger.info("ℹ️ Keine 'pv_counter_state.json' gefunden. Initialisiere Zustand für den Erststart...")
        initial_state = {
            "last_total_pv": current_total_pv,
            "last_timestamp": datetime.now().isoformat()
        }
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(initial_state, f, indent=4)
            logger.info("⏳ Erststart-Wert erfolgreich gesichert. Das Feintuning wird für diese Stunde ausgesetzt.")
        except Exception as e:
            logger.error(f"🚨 Fehler beim Erstellen der State-Datei: {e}")
        return None

    # Bestehenden Zustand laden
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        logger.error(f"🚨 Fehler beim Lesen von pv_counter_state.json: {e}")
        return None

    last_total_pv = state.get("last_total_pv", current_total_pv)
    
    # Delta (realer Stundenertrag) berechnen
    pv_delta = current_total_pv - last_total_pv
    
    # Plausibilitätsprüfung (Abfang bei Wechselrichter-Reset oder Zählertausch)
    if pv_delta < 0:
        logger.warning(f"⚠️ Negatives PV-Delta festgestellt ({pv_delta:.3f} kWh). Setze Zustand zurück.")
        pv_delta = 0.0

    # Zustand für die nächste Stunde aktualisieren
    state["last_total_pv"] = current_total_pv
    state["last_timestamp"] = datetime.now().isoformat()
    
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logger.error(f"🚨 Fehler beim Schreiben der pv_counter_state.json: {e}")

    return pv_delta

# main.py
import time
from datetime import datetime
import logging

# Import der eigenen Sub-Module
import logger_config
import awattar_client
import loxone_client
import profile_manager
import optimizer
import pv_tuner
import os
import csv

# Logger für dieses spezifische Modul instanziieren
logger = logging.getLogger("main")

def log_to_csv(soc, price, pv_forecast, cons_forecast, mode, target_power):
    """Schreibt die Systemzustände und Loxone-Ausgangswerte in eine strukturierte CSV-Datei."""
    file_name = "system_history_log.csv"
    file_exists = os.path.exists(file_name)
    
    # Datenzeile vorbereiten
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        soc,
        round(price, 4),
        round(pv_forecast, 3),
        round(cons_forecast, 3),
        mode,
        round(target_power, 3)
    ]
    
    try:
        with open(file_name, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                # Header schreiben, falls Datei nagelneu ist
                writer.writerow([
                    "Timestamp", "SoC_%", "Awattar_Price", 
                    "PV_Forecast_kW", "Consumption_Forecast_kW", 
                    "Ernie_Mode", "Target_Power_kW"
                ])
            writer.writerow(row)
    except Exception as e:
        logger.error(f"Fehler beim Schreiben in die CSV-Historie (evtl. Datei durch Streamlit blockiert): {e}")

def main():
    # 0. Logging-System starten
    logger_config.setup_logging(log_file="energy_optimizer.log", level=logging.INFO)
    
    logger.info("--- Energy Optimizer Live-Abfrage gestartet ---")
    
    # 1. Monats-Profil prüfen/aktualisieren
    profile_manager.check_and_update_profile_if_new_month()
    
    # 2. Live-Werte von Loxone & Awattar laden
    current_soc = loxone_client.fetch_loxone_soc()
    if current_soc is None:
        logger.error("Optimierung abgebrochen: Kein Zugriff auf Loxone SoC.")
        return

    market_data = awattar_client.fetch_awattar_prices()
    if not market_data:
        logger.error("Optimierung abgebrochen: Keine Awattar-Preise empfangen.")
        return
        
    # Neu: PV-Zähler abfragen und reales Delta ermitteln
    pv_delta = pv_tuner.get_pv_delta_and_update()
    if pv_delta is None:
        logger.warning("⚠️ Tuning/Optimierungsdurchlauf für diese Stunde ausgesetzt (Warten auf valides Delta).")
        return
        
    logger.info("📊 Tatsächlicher PV-Ertrag der letzten Stunde: %.3f kWh", pv_delta)
    
    # 3. Prognose-Vektoren (Verbrauch & PV) laden
    forecast_consumption, forecast_pv, optimization_matrix = profile_manager.get_forecast_vectors(market_data)
    
    # 4. Optimierung berechnen
    current_hour = datetime.now().hour
    mode, target_power = optimizer.heuristic_optimizer(optimization_matrix, current_hour, current_soc)
    
    logger.info("Berechnete Werte für Loxone -> MODE: %s | TARGET_POWER: %s kW", mode, target_power)

    current_market_item = market_data[0] # Aktuelle Stunde
    log_to_csv(
        soc=current_soc,
        price=current_market_item['price_buy'],
        pv_forecast=forecast_pv[0],
        cons_forecast=forecast_consumption[0],
        mode=mode,
        target_power=target_power
    )
    
    # 6. Werte aktiv an Loxone übertragen
    logger.info("📤 Sende Werte an Loxone...")
    loxone_client.send_loxone_value("Ernie_Mode", mode)
    loxone_client.send_loxone_value("Ernie_Ziel_Leistung", target_power)


if __name__ == "__main__":
    # Da die Schleife primär für Testzwecke dient, halten wir die Taktung pragmatisch und robust:
    while True:
        try:
            # Führe die oben definierte Routine aus
            main()
            
            # Nach einem erfolgreichen Durchlauf warten wir standardmäßig 15 Minuten (900 Sekunden)
            logger.info("✅ Durchlauf erfolgreich beendet. Schlafe für 15 Minuten...")
            time.sleep(900)
            
        except Exception as e:
            # Verhindert den Absturz des Skripts bei API-Fehlern, Timeouts oder Netzwerkabrissen
            # Nutzt den Logger (sofern initialisiert) oder Fallback auf Print
            msg = f"🚨 Unerwarteter Fehler während des Durchlaufs: {e}"
            if logger.handlers:
                logger.exception(msg)
            else:
                print(msg)
                
            print("🔄 Skript läuft weiter. Schneller Wiederholungsversuch in 60 Sekunden...")
            # Bei einem Fehler warten wir nur 60 Sekunden für einen schnellen Retry (statt 15 Min CPU-Saturierung oder ewigem Warten)
            time.sleep(60)

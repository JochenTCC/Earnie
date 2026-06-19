# main.py
import time
from datetime import datetime
import logging
import config
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

def log_to_csv(soc, price, pv_forecast, cons_forecast, mode, target_power, target_soc):
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
        round(target_power, 3),
        round(target_soc, 0)
    ]
    
    try:
        with open(file_name, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                # Header schreiben, falls Datei nagelneu ist
                writer.writerow([
                    "Timestamp", "SoC_%", "Awattar_Price", 
                    "PV_Forecast_kW", "Consumption_Forecast_kW", 
                    "Ernie_Mode", "Target_Power_kW", "Target_SoC_%"
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
    consumer_targets = profile_manager.resolve_consumer_daily_targets(matrix=optimization_matrix)
    charging_contexts = optimizer.resolve_charging_contexts(
        optimization_matrix, consumer_targets
    )
    consumer_remaining = optimizer.get_consumer_remaining_kwh(
        consumer_daily_targets_kwh=consumer_targets,
        optimization_matrix=optimization_matrix,
    )
    mode, target_power, target_soc, consumer_powers, _ = optimizer.heuristic_optimizer(
        optimization_matrix,
        current_hour,
        current_soc,
        consumer_remaining_kwh=consumer_remaining,
        charging_contexts=charging_contexts,
    )
    optimizer.register_consumer_hours(consumer_powers)

    logger.info(
        "Berechnete Werte für Loxone -> MODE: %s | TARGET_POWER: %s kW | TARGET_SOC: %s | Verbraucher: %s",
        mode, target_power, target_soc, consumer_powers,
    )

    current_market_item = market_data[0] # Aktuelle Stunde
    log_to_csv(
        soc=current_soc,
        price=current_market_item['price_buy'],
        pv_forecast=forecast_pv[0],
        cons_forecast=forecast_consumption[0],
        mode=mode,
        target_power=target_power,
        target_soc=target_soc
    )
    
    logger.info("📤 Sende gemappte Huawei-Modbus-Werte an Loxone...")
    loxone_client.send_huawei_modbus_states(mode, target_power, target_soc)

if __name__ == "__main__":
    while True:
        try:
            # Führe die oben definierte Routine aus
            main()
            
            # Strikter Zugriff auf das konfigurierte Intervall ohne versteckte Defaults
            loop_timeout = config.get('LOOP_TIMEOUT', cast=int)
            
            logger.info(f"✅ Durchlauf erfolgreich beendet. Schlafe für {loop_timeout} Sekunden...")
            time.sleep(loop_timeout)
            
        except Exception as e:
            # Verhindert den Absturz des Skripts bei API-Fehlern, Timeouts oder Netzwerkabrissen
            msg = f"🚨 Unerwarteter Fehler während des Durchlaufs: {e}"
            if logger.handlers:
                logger.exception(msg)
            else:
                print(msg)
                
            print("🔄 Skript läuft weiter. Schneller Wiederholungsversuch in 60 Sekunden...")
            time.sleep(60)
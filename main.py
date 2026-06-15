# main.py
import os
import json
from datetime import datetime
import logging

# Import der eigenen Sub-Module
import logger_config
import awattar_client
import loxone_client
import profile_manager
import optimizer
import pv_tuner

# Logger für dieses spezifische Modul instanziieren
logger = logging.getLogger("main")

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
    forecast_consumption, forecast_pv = profile_manager.get_forecast_vectors()
    
    # 4. Matrix aufbauen
    optimization_matrix = []
    for item in market_data[:24]:
        hour = item['hour']
        optimization_matrix.append({
            "hour": hour,
            "k_act": item['price_buy'],
            "expected_p_act": forecast_consumption[hour],
            "expected_p_pv": forecast_pv[hour]
        })

    # 5. Optimierung berechnen
    current_hour = datetime.now().hour
    mode, target_power = optimizer.heuristic_optimizer(optimization_matrix, current_hour, current_soc)
    
    logger.info("Berechnete Werte für Loxone -> MODE: %s | TARGET_POWER: %s kW", mode, target_power)
    
    # 6. Werte aktiv an Loxone übertragen
    logger.info("📤 Sende Werte an Loxone...")
    loxone_client.send_loxone_value("Ernie_Mode", mode)
    loxone_client.send_loxone_value("Ernie_Ziel_Leistung", target_power)


if __name__ == "__main__":
    main()
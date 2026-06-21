# main.py
import time
from datetime import datetime
import logging
import config
import logger_config
import awattar_client
import loxone_client
import profile_manager
import consumer_targets
import optimizer
import pv_tuner
import cons_data_store
import live_consumption
import run_state
import optimization_history
import optimization_schedule
import os
import csv
from version import __version__

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
    config.reload_config()

    logger.info("--- Energy Optimizer Live-Abfrage gestartet (v%s) ---", __version__)
    
    # 1. Monats-Profil prüfen/aktualisieren
    profile_manager.check_and_update_profile_if_new_month()
    
    # 2. Live-Werte von Loxone & Awattar laden
    current_soc = loxone_client.fetch_loxone_generic_value(config.get("LOXONE_SOC_NAME"))
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
    _, _, optimization_matrix = profile_manager.get_forecast_vectors(market_data)

    live_power = loxone_client.fetch_loxone_live_power()
    flex_kw_for_matrix: dict[str, float] = {}
    if live_power:
        flex_kw_for_matrix = loxone_client.fetch_flexible_consumers_live_kw()
        matrix_snapshot = live_consumption.build_consumption_snapshot(
            live_power, flex_kw_for_matrix
        )
        optimization_matrix = live_consumption.apply_live_snapshot_to_matrix(
            optimization_matrix, matrix_snapshot, hour_index=0
        )
        logger.info(
            "Live-Snapshot in Optimierungsmatrix: PV=%.2f kW, Grundlast=%.2f kW",
            matrix_snapshot["pv_kw"],
            matrix_snapshot["baseload_kw"],
        )

    # 4. Optimierung berechnen
    current_hour = datetime.now().hour
    targets = consumer_targets.resolve_consumer_daily_targets(matrix=optimization_matrix)
    charging_contexts = optimizer.resolve_charging_contexts(
        optimization_matrix, targets
    )
    consumer_remaining = optimizer.get_consumer_remaining_kwh(
        consumer_daily_targets_kwh=targets,
        optimization_matrix=optimization_matrix,
    )
    live_consumers = loxone_client.consumers_with_live_nominal_power()
    for consumer in live_consumers:
        lox = (consumer.get("charging_schedule") or {}).get("loxone") or {}
        if lox.get("nominal_power_kw_name"):
            logger.info(
                "Verbraucher %s: Nennleistung live = %.2f kW (Loxone: %s)",
                consumer["name"],
                consumer["nominal_power_kw"],
                lox["nominal_power_kw_name"],
            )
    mode, target_power, target_soc, consumer_powers, _ = optimizer.heuristic_optimizer(
        optimization_matrix,
        current_hour,
        current_soc,
        consumers=live_consumers,
        consumer_remaining_kwh=consumer_remaining,
        charging_contexts=charging_contexts,
    )
    battery_params = config.get_battery_params()
    battery_plan_kw = optimizer.battery_plan_kw_from_control(
        mode,
        target_power,
        optimization_matrix[0]["expected_p_pv"],
        optimization_matrix[0]["expected_p_act"],
        sum(consumer_powers.values()),
        battery_params["max_power_kw"],
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
        pv_forecast=optimization_matrix[0]["expected_p_pv"],
        cons_forecast=optimization_matrix[0]["expected_p_act"],
        mode=mode,
        target_power=target_power,
        target_soc=target_soc
    )
    
    logger.info("📤 Sende gemappte Huawei-Modbus-Werte an Loxone...")
    loxone_client.send_huawei_modbus_states(mode, target_power, target_soc)
    logger.info("📤 Sende flexible Verbraucher-Sollwerte an Loxone...")
    loxone_client.send_flexible_consumer_states(consumer_powers, charging_contexts)

    if live_power is None:
        live_power = loxone_client.fetch_loxone_live_power()
    total_kw = live_power["house"] if live_power else None
    flex_kw = loxone_client.fetch_flexible_consumers_live_kw(fallbacks=consumer_powers)
    logger.info("cons_data Flex live (kW): %s", flex_kw)
    try:
        written = cons_data_store.record_and_maybe_flush(
            total_kw=total_kw,
            pv_kwh_interval=pv_delta,
            flex_kw=flex_kw,
        )
        if written:
            logger.info("cons_data: %s Stunde(n) in cons_data_hourly.csv geschrieben.", written)
    except Exception as e:
        logger.warning("cons_data: Messwerte konnten nicht gespeichert werden: %s", e)

    consumption_snapshot = None
    if live_power:
        consumption_snapshot = live_consumption.build_consumption_snapshot(live_power, flex_kw)

    try:
        run_payload = {
            "source": "main.py",
            "success": True,
            "optimization_interval_sec": optimization_schedule.optimization_interval_seconds(),
            "soc_percent": round(float(current_soc), 2),
            "pv_delta_kwh": round(float(pv_delta), 4),
            "market_price_cent": round(float(current_market_item["price_buy"]), 4),
            "forecast_pv_kw": round(float(optimization_matrix[0]["expected_p_pv"]), 3),
            "forecast_consumption_kw": round(float(optimization_matrix[0]["expected_p_act"]), 3),
            "mode": int(mode),
            "target_power_kw": round(float(target_power), 3),
            "target_soc_percent": round(float(target_soc), 1),
            "battery_plan_kw": battery_plan_kw,
            "consumer_powers_kw": {
                k: round(float(v), 3) for k, v in consumer_powers.items()
            },
            "flex_live_kw": flex_kw,
            "consumption_snapshot": consumption_snapshot,
            "current_hour": int(current_hour),
        }
        run_state.save_run_state(run_payload)
        try:
            optimization_history.append_production_run(run_payload)
        except OSError as exc:
            logger.warning("optimization_history: Anhängen fehlgeschlagen: %s", exc)
        logger.info("run_state: Durchlauf in optimizer_run_state.json gespeichert.")
    except Exception as e:
        logger.warning("run_state: Zustand konnte nicht gespeichert werden: %s", e)

if __name__ == "__main__":
    logger_config.setup_logging(log_file="energy_optimizer.log", level=logging.INFO)
    while True:
        try:
            main()
            
            wait_sec = optimization_schedule.seconds_until_next_quarter_hour()
            next_run = optimization_schedule.next_quarter_hour_datetime()
            logger.info(
                "✅ Durchlauf erfolgreich beendet. Nächster Lauf um %s (in %.0f s).",
                next_run.strftime("%H:%M:%S"),
                wait_sec,
            )
            time.sleep(wait_sec)
            
        except Exception as e:
            msg = f"🚨 Unerwarteter Fehler während des Durchlaufs: {e}"
            if logger.handlers:
                logger.exception(msg)
            else:
                print(msg)
                
            print("🔄 Skript läuft weiter. Schneller Wiederholungsversuch in 60 Sekunden...")
            time.sleep(60)

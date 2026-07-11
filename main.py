# main.py
import sys
import time
from datetime import datetime
import logging

from runtime_store.config_load import load_config_or_exit, reinit_config_or_exit

config = load_config_or_exit()
import logger_config
from integrations import awattar_client, loxone_client
from data import profile_manager, consumer_targets, pv_tuner, cons_data_store, live_consumption
from data.feed_in_prices import k_push_act_for_matrix_row
from runtime_store import run_state, optimization_history
from runtime_store.single_instance import SingleInstanceError, ensure_single_instance
from optimizer import schedule as optimization_schedule
from optimizer.thermal_targets import collect_thermal_observability
from optimizer.event_trigger import (
    TRIGGER_QUARTER_HOUR,
    fetch_trigger_snapshot,
    is_event_trigger,
    snapshot_from_run_state,
    wait_until_next_run,
)
import optimizer
from version import __version__

logger = logging.getLogger("main")


def _baseline_trigger_snapshot() -> dict:
    state = run_state.load_run_state()
    snapshot = snapshot_from_run_state(state)
    if snapshot:
        return snapshot
    return fetch_trigger_snapshot(config.get_event_triggers())


def main(run_trigger: str = TRIGGER_QUARTER_HOUR):
    config.reload_config()
    config.require_runtime_params_loaded()
    event_run = is_event_trigger(run_trigger)
    trigger_specs = config.get_event_triggers()

    if event_run:
        logger.info(
            "--- Earnie Event-Lauf (v%s, Trigger: %s) ---",
            __version__,
            run_trigger,
        )
    else:
        logger.info("--- Earnie Live-Abfrage gestartet (v%s) ---", __version__)
    if config.is_loxone_silent_mode():
        logger.warning(
            "Loxone Silent-Modus aktiv: Optimierung ohne Schreibzugriffe auf den Miniserver."
        )

    profile_manager.check_and_update_profile_if_new_month()

    current_soc = loxone_client.fetch_loxone_generic_value(config.get("LOXONE_SOC_NAME"))
    if current_soc is None:
        logger.error("Optimierung abgebrochen: Kein Zugriff auf Loxone SoC.")
        return

    config.is_sunset_planning_horizon()
    planning_window = profile_manager.compute_live_planning_window()
    logger.info(
        "Planungsfenster: %s → %s (%d h), SU₁=%s, SU₂=%s, Sonnenaufgang-Anker=%s",
        planning_window.start.strftime("%Y-%m-%d %H:%M"),
        planning_window.end.strftime("%Y-%m-%d %H:%M"),
        planning_window.horizon_hours,
        planning_window.sunset_1.strftime("%Y-%m-%d %H:%M"),
        planning_window.sunset_2.strftime("%Y-%m-%d %H:%M"),
        planning_window.sunrise_anchor.strftime("%Y-%m-%d %H:%M"),
    )

    market_data = awattar_client.fetch_awattar_prices(planning_end=planning_window.end)
    if not market_data:
        logger.error("Optimierung abgebrochen: Keine Awattar-Preise empfangen.")
        return

    if event_run:
        pv_delta = pv_tuner.get_pv_delta_peek()
    else:
        pv_delta = pv_tuner.get_pv_delta_and_update()
    if pv_delta is None:
        if event_run:
            logger.warning(
                "Event-Lauf: Kein PV-Stunden-Delta verfügbar – Optimierung läuft ohne PV-Tuning."
            )
            pv_delta = 0.0
        else:
            logger.warning(
                "⚠️ Tuning/Optimierungsdurchlauf für diese Stunde ausgesetzt "
                "(Warten auf valides Delta)."
            )
            return

    logger.info("📊 Tatsächlicher PV-Ertrag der letzten Stunde: %.3f kWh", pv_delta)

    optimization_matrix = profile_manager.build_live_planning_matrix(
        market_data, planning_window
    )
    from data.planning_window import sunrise_anchor_slot_index

    sunrise_soc_min_index = sunrise_anchor_slot_index(planning_window)
    pv_forecast_kw_for_log = float(optimization_matrix[0]["expected_p_pv"])

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

    current_hour = datetime.now().hour
    targets = consumer_targets.resolve_consumer_daily_targets(matrix=optimization_matrix)
    live_consumers = loxone_client.consumers_with_live_nominal_power()
    baseline_targets = consumer_targets.resolve_historical_baseline_targets_kwh(
        matrix=optimization_matrix,
    )
    thermal_observability = collect_thermal_observability(
        live_consumers,
        active_targets_kwh=targets,
        baseline_targets_kwh=baseline_targets,
        horizon=len(optimization_matrix),
    )
    for item in thermal_observability:
        if item.get("error"):
            logger.warning(
                "Thermisch %s: %s",
                item.get("consumer_id", "?"),
                item["error"],
            )
            continue
        logger.info(
            "Thermisch %s (mode=%s): aktiv %.2f kWh, thermisch %.2f kWh, Delta %+.2f kWh, "
            "Heizstunden %s, Ist %.1f °C, Band %.1f–%.1f °C%s",
            item["consumer_id"],
            item.get("mode"),
            item.get("active_target_kwh", 0.0),
            item.get("thermal_target_kwh", 0.0),
            item.get("delta_kwh", 0.0),
            item.get("heating_hours", 0),
            (item.get("readings_c") or {}).get("actual"),
            (item.get("readings_c") or {}).get("band_min"),
            (item.get("readings_c") or {}).get("band_max"),
            (
                f", historical {item['baseline_target_kwh']:.2f} kWh"
                if item.get("baseline_target_kwh") is not None
                else ""
            ),
        )
    optimization_matrix, charging_contexts, targets = optimizer.prepare_optimization_matrix(
        optimization_matrix,
        targets,
        consumers=live_consumers,
    )
    event_trigger_snapshot = fetch_trigger_snapshot(trigger_specs)
    delivery_plausibility: dict = {}
    filter_contexts = optimizer.resolve_filter_contexts(optimization_matrix, live_consumers)
    consumer_remaining = optimizer.get_consumer_remaining_kwh(
        consumer_daily_targets_kwh=targets,
        optimization_matrix=optimization_matrix,
        charging_contexts=charging_contexts,
        filter_contexts=filter_contexts,
        live_flex_kw=flex_kw_for_matrix,
        trigger_snapshot=event_trigger_snapshot,
        delivery_plausibility=delivery_plausibility,
    )
    for consumer in live_consumers:
        lox = (consumer.get("charging_schedule") or {}).get("loxone") or {}
        if lox.get("nominal_power_kw_name"):
            logger.info(
                "Verbraucher %s: Nennleistung live = %.2f kW (Loxone: %s)",
                consumer["name"],
                consumer["nominal_power_kw"],
                lox["nominal_power_kw_name"],
            )
    mode, target_power, target_soc, consumer_powers, consumer_pv_follow, _, urgent_obs = optimizer.milp_optimizer(
        optimization_matrix,
        current_hour,
        current_soc,
        consumers=live_consumers,
        consumer_remaining_kwh=consumer_remaining,
        charging_contexts=charging_contexts,
        filter_contexts=filter_contexts,
        sunrise_soc_min_index=sunrise_soc_min_index,
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

    logger.info(
        "Berechnete Werte für Loxone -> MODE: %s | TARGET_POWER: %s kW | "
        "TARGET_SOC: %s | Verbraucher: %s | pv_follow: %s",
        mode, target_power, target_soc, consumer_powers, consumer_pv_follow,
    )

    current_market_item = optimization_matrix[0]

    if config.is_loxone_silent_mode():
        logger.info(
            "Silent-Modus: Steuerwerte (Huawei-Modbus, flexible Verbraucher) "
            "werden nicht an Loxone gesendet."
        )
    else:
        logger.info("📤 Sende gemappte Huawei-Modbus-Werte an Loxone...")
        loxone_client.send_huawei_modbus_states(mode, target_power, target_soc)
        logger.info("📤 Sende flexible Verbraucher-Sollwerte an Loxone...")
        loxone_client.send_flexible_consumer_states(
            consumer_powers, charging_contexts, consumer_pv_follow
        )

    if live_power is None:
        live_power = loxone_client.fetch_loxone_live_power()
    total_kw = live_power["house"] if live_power else None
    from optimizer.charging_context import matrix_slot_datetime

    live_flex = loxone_client.resolve_flexible_consumers_live_power(
        fallbacks=consumer_powers,
        consumers=live_consumers,
        filter_contexts=filter_contexts,
        slot_datetime=matrix_slot_datetime(optimization_matrix, 0),
    )
    flex_kw = live_flex.kw
    flex_chart_kw = live_flex.chart_kw
    logger.info("cons_data Flex live (kW): %s", flex_kw)
    logger.info("Chart-Ist Flex (kW): %s | gemessen: %s", flex_chart_kw, sorted(live_flex.measured_ids))

    loxone_sent = loxone_client.build_sent_loxone_snapshot(
        mode,
        target_power,
        target_soc,
        consumer_powers,
        charging_contexts,
        consumer_pv_follow,
    )
    sent_flex_kw: dict[str, float] = {}
    for consumer in live_consumers:
        outputs = consumer.get("loxone_outputs") or {}
        setpoint_name = outputs.get("power_setpoint_name", "")
        if not setpoint_name:
            continue
        sent_flex_kw[consumer["id"]] = float(loxone_sent.get(setpoint_name, 0.0) or 0.0)

    delivery_compliance = optimizer.register_consumer_delivery(
        consumer_powers,
        charging_contexts=charging_contexts,
        consumers=live_consumers,
        live_flex_kw=flex_kw,
        sent_flex_kw=sent_flex_kw,
        book_planned=not event_run,
    )

    savings_snapshot = None
    try:
        savings_info = optimizer.calculate_optimization_savings(
            optimization_matrix,
            float(current_soc),
            consumer_daily_targets_kwh=targets,
            sunrise_soc_min_index=sunrise_soc_min_index,
            filter_contexts=filter_contexts,
        )
        savings_snapshot = optimizer.build_savings_snapshot(savings_info)
        logger.info(
            "Prognostizierte Ersparnis (%d h): %.3f € vs BL Ziel "
            "(%.3f € optimiert / %.3f € BL Ziel)",
            len(optimization_matrix),
            savings_snapshot["savings_matched_euro"],
            savings_snapshot["optimized_cost_euro"],
            savings_snapshot["matched_baseline_cost_euro"],
        )
    except Exception as exc:
        logger.warning("Einsparungs-Prognose konnte nicht berechnet werden: %s", exc)

    if not event_run:
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
        consumption_snapshot = live_consumption.build_consumption_snapshot(
            live_power, flex_chart_kw
        )

    try:
        run_payload = {
            "source": "main.py",
            "success": True,
            "run_trigger": run_trigger,
            "loxone_silent_mode": config.is_loxone_silent_mode(),
            "optimization_interval_sec": optimization_schedule.optimization_interval_seconds(),
            "event_trigger_snapshot": event_trigger_snapshot,
            "loxone_sent": loxone_sent,
            "soc_percent": round(float(current_soc), 2),
            "pv_delta_kwh": round(float(pv_delta), 4),
            "market_price_cent": round(float(current_market_item["price_buy"]), 4),
            "k_push_act": round(
                k_push_act_for_matrix_row(
                    current_market_item,
                    config.get_push_price_cent(),
                ),
                4,
            ),
            "forecast_pv_kw": round(pv_forecast_kw_for_log, 3),
            "forecast_consumption_kw": round(float(optimization_matrix[0]["expected_p_act"]), 3),
            "mode": int(mode),
            "target_power_kw": round(float(target_power), 3),
            "target_soc_percent": round(float(target_soc), 1),
            "battery_plan_kw": battery_plan_kw,
            "consumer_powers_kw": {
                k: round(float(v), 3) for k, v in consumer_powers.items()
            },
            "consumer_remaining_kwh": {
                k: round(float(v), 3) for k, v in consumer_remaining.items()
            },
            "charging_contexts": optimizer.serialize_charging_contexts(charging_contexts),
            "filter_contexts": optimizer.serialize_filter_contexts(filter_contexts),
            "urgent_rule_observability": urgent_obs,
            "consumer_pv_follow": {
                k: int(v) for k, v in consumer_pv_follow.items()
            },
            "flex_live_kw": flex_chart_kw,
            "flex_measured_ids": sorted(live_flex.measured_ids),
            "delivery_compliance": delivery_compliance,
            "delivery_plausibility": delivery_plausibility,
            "thermal_observability": thermal_observability,
            "savings_snapshot": savings_snapshot,
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
    from runtime_store import bootstrap
    from runtime_store.config_drift import log_config_drift
    from runtime_store.persist_paths import log_file

    bootstrap.run()
    reinit_config_or_exit(config)
    logger_config.setup_logging(log_file=log_file(), level=logging.INFO)
    log_config_drift(logging.getLogger("main"))
    from scripts.startup_checks import run_loxone_verify_on_startup

    run_loxone_verify_on_startup()
    try:
        ensure_single_instance("main")
    except SingleInstanceError as exc:
        logger.error("%s", exc)
        print(f"Abbruch: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if config.is_event_trigger_enabled() and not config.get_event_triggers():
        logger.warning(
            "event_trigger_enabled ist true, aber system.event_triggers ist leer – "
            "kein Event-Polling zwischen den regulären Läufen."
        )

    from runtime_store.dotenv_io import (
        loxone_credentials_configured,
        loxone_setup_deferred,
        needs_loxone_setup,
    )
    from runtime_store.dotenv_loader import load_app_dotenv
    from ui.setup_readiness import is_planning_ready, needs_planning_onboarding

    _SETUP_WAIT_SEC = 60
    next_trigger = TRIGGER_QUARTER_HOUR
    known_snapshot: dict = {}
    trigger_specs = config.get_event_triggers()

    while True:
        if needs_loxone_setup():
            logger.warning(
                "Loxone-Zugangsdaten fehlen oder sind noch Platzhalter. "
                "Bitte in der Streamlit-UI (Port %s) die Ersteinrichtung abschließen. "
                "Erneuter Versuch in %s Sekunden.",
                config.get_ui_streamlit_port(),
                _SETUP_WAIT_SEC,
            )
            time.sleep(_SETUP_WAIT_SEC)
            load_app_dotenv(override=True)
            config.reinit_config()
            continue

        if loxone_setup_deferred() and not loxone_credentials_configured():
            logger.info(
                "Loxone-Zugangsdaten noch nicht hinterlegt (optional bis Live-/Silent-Betrieb). "
                "Planung/Backtesting in der UI (Port %s) möglich. "
                "Erneuter Versuch in %s Sekunden.",
                config.get_ui_streamlit_port(),
                _SETUP_WAIT_SEC,
            )
            time.sleep(_SETUP_WAIT_SEC)
            config.reinit_config()
            continue

        if needs_planning_onboarding() and not is_planning_ready():
            logger.warning(
                "Planungs-Konfiguration unvollständig. "
                "Bitte in der Streamlit-UI (Port %s) Hauskonfigurator und Runtime-Szenario abschließen. "
                "Erneuter Versuch in %s Sekunden.",
                config.get_ui_streamlit_port(),
                _SETUP_WAIT_SEC,
            )
            time.sleep(_SETUP_WAIT_SEC)
            config.reinit_config()
            continue

        if not known_snapshot:
            known_snapshot = _baseline_trigger_snapshot()
            trigger_specs = config.get_event_triggers()

        try:
            main(run_trigger=next_trigger)
            next_trigger = TRIGGER_QUARTER_HOUR
            trigger_specs = config.get_event_triggers()

            state = run_state.load_run_state()
            if state and state.get("success") and isinstance(state.get("event_trigger_snapshot"), dict):
                known_snapshot = snapshot_from_run_state(state)
            else:
                known_snapshot = fetch_trigger_snapshot(trigger_specs)

            wait_sec = optimization_schedule.seconds_until_next_quarter_hour()
            next_run = optimization_schedule.next_quarter_hour_datetime()
            logger.info(
                "✅ Durchlauf erfolgreich beendet. Nächster regulärer Lauf um %s (in %.0f s).",
                next_run.strftime("%H:%M:%S"),
                wait_sec,
            )
            event_trigger, known_snapshot = wait_until_next_run(
                previous_snapshot=known_snapshot,
                trigger_specs=trigger_specs,
                total_wait_sec=wait_sec,
                poll_interval_sec=config.get_event_poll_interval_sec(),
                event_trigger_enabled=config.is_event_trigger_enabled(),
            )
            if event_trigger:
                next_trigger = event_trigger

        except Exception as e:
            msg = f"🚨 Unerwarteter Fehler während des Durchlaufs: {e}"
            if logger.handlers:
                logger.exception(msg)
            else:
                print(msg)

            print("🔄 Skript läuft weiter. Schneller Wiederholungsversuch in 60 Sekunden...")
            time.sleep(60)

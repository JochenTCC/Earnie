# main.py
import os
import sys
import time
from datetime import datetime, timedelta
import logging

from runtime_store.config_load import load_config_or_exit, reinit_config_or_exit
from runtime_store import power_interval_sampler

config = load_config_or_exit()
import logger_config
from integrations import ehal_live
from integrations.loxone_comm_trace import serialize_write_records
from data import profile_manager, consumer_targets, pv_tuner, cons_data_store, live_consumption, pv_forecast
from data.edibert_live_market import fetch_live_day_ahead_prices
from data.feed_in_prices import k_push_act_for_matrix_row
from runtime_store import run_state, optimization_history
from runtime_store import cycle_recorder
from runtime_store.soc_plausibility import (
    closed_interval_confirms_reported,
    count_consecutive_reported_soc,
    sanitize_soc_reading,
)
from runtime_store import live_optimization_debug
from runtime_store import cycle_duration_stats
from runtime_store.cycle_timing import CycleTimer
from optimizer.live_cycle_scope import live_cycle_scope
from runtime_store.live_display_loader import serialize_planning_window
from runtime_store.single_instance import SingleInstanceError, ensure_single_instance
from optimizer import schedule as optimization_schedule
from optimizer.thermal_targets import (
    collect_thermal_observability,
    thermal_horizon_hours_from_slots,
)
from optimizer.thermal_live_store import collect_heat_storage_observability
from optimizer.start_scheduler import (
    LEAD_MAX_SEC,
    decide_lead,
    early_start_enabled,
    next_regular_start,
)
from optimizer.run_trigger import (
    TRIGGER_QUARTER_HOUR,
    TRIGGER_REQUEST_OPTIMIZE,
    is_out_of_band_trigger,
    wait_until_next_run,
)
import optimizer
from settings.ehal_marker_resolve import marker_set_evcs_max_current
from settings.ev_power import ampere_to_kw, ev_nominal_power_conversion
from version import __version__
from runtime_store.planning_clock import planning_anchor, planning_now

logger = logging.getLogger("main")

# Wait after a cycle that aborted before planning (no SoC / no prices yet). Not shorter than
# the HA push interval (10 s): a retry cannot see newer inputs earlier.
ABORTED_CYCLE_RETRY_SEC = 30.0

# Closed interval finalized by the previous regular cycle. An early-started cycle
# plans before its own interval [T-15, T) is closed, so its SoC plausibility
# check uses [T-30, T-15) (spec early-start-scheduling.md §4).
_last_closed_interval: dict | None = None



def main(
    run_trigger: str = TRIGGER_QUARTER_HOUR,
    *,
    woke_at: datetime | None = None,
    cold_start: bool = False,
    tick: datetime | None = None,
    lead_sec: float = 0.0,
):
    """One optimization cycle.

    ``tick``: early start (EarlyStart P1) — the cycle runs before this
    quarter-hour boundary, plans for slot ``[tick, tick+15)`` and writes no
    setpoint before ``tick``. ``None``: plan for the current slot, write when
    ready (out-of-band runs, first run after start, ``EARNIE_EARLY_START=off``).

    Returns ``False`` when the cycle aborted before planning (no SoC, no prices): the
    caller must neither report success nor restart at once (L12).
    """
    if tick is not None and is_out_of_band_trigger(run_trigger):
        raise ValueError("Out-of-band runs are never early-started (tick must be None).")
    with planning_anchor(tick), cycle_duration_stats.cycle_stats_session(
        trigger=run_trigger,
        version=__version__,
        woke_at=woke_at,
        cold_start=cold_start,
        tick=tick,
        lead_sec=lead_sec if tick is not None else 0.0,
    ):
        timing = CycleTimer(slot_key=optimization_schedule.quarter_hour_slot_key())
        timing.activate()
        try:
            # One Live store plan (readings + forecast) per cycle: ThermalHorizon P2.
            with live_cycle_scope():
                return _main_cycle(run_trigger, timing, tick=tick)
        finally:
            timing.finish()


def _finalize_previous_interval() -> dict | None:
    """Close ``[slot-15, slot)`` of the current (planning) slot in the sampler."""
    global _last_closed_interval
    previous_slot = optimization_schedule.quarter_hour_slot_start() - timedelta(
        minutes=optimization_schedule.QUARTER_HOUR_MINUTES
    )
    _last_closed_interval = power_interval_sampler.finalize_closed_interval(previous_slot)
    return _last_closed_interval


def _daemon_wait_poll() -> None:
    """Heartbeat + power-interval sampler tick while the daemon waits."""
    from runtime_store.daemon_heartbeat import touch_daemon_heartbeat
    from runtime_store.usage_ping import spawn_maybe_send_ping

    touch_daemon_heartbeat()
    spawn_maybe_send_ping()
    if power_interval_sampler.tick():
        from runtime_store.shadow import maybe_flush_after_sampler

        maybe_flush_after_sampler()


def _wait_after_aborted_cycle() -> str:
    """Back off after a cycle that aborted before planning; returns the next trigger.

    Without it the scheduler restarts at once inside the lead window (L12). An
    ``Earnie_Request_Optimize`` wake ends the wait early.
    """
    from runtime_store.shadow import resolve_next_trigger

    early = wait_until_next_run(
        total_wait_sec=ABORTED_CYCLE_RETRY_SEC,
        on_poll=_daemon_wait_poll,
    )
    return resolve_next_trigger(
        early,
        TRIGGER_QUARTER_HOUR,
        optimize_trigger=TRIGGER_REQUEST_OPTIMIZE,
    )


def _hold_until_tick(
    tick: datetime,
    *,
    poll_interval_sec: float = 1.0,
    on_poll=_daemon_wait_poll,
    sleep_fn=time.sleep,
    clock_fn=time.monotonic,
    now_fn=datetime.now,
) -> None:
    """Block until ``tick`` (real clock) so no setpoint is written before it.

    A plan that is ready only after the tick is written at once (late, as
    without early start). Later than ``LATE_WARN_SEC`` after the tick →
    warning, otherwise info.
    """
    from optimizer.start_scheduler import LATE_WARN_SEC

    remaining = (tick - now_fn()).total_seconds()
    if remaining <= 0:
        late = -remaining
        level = logging.WARNING if late > LATE_WARN_SEC else logging.INFO
        logger.log(
            level,
            "Plan für %s %.0f s nach dem Takt fertig%s — "
            "Sollwerte werden sofort geschrieben.",
            tick.strftime("%H:%M"),
            late,
            f" (> {LATE_WARN_SEC:.0f} s)" if late > LATE_WARN_SEC else "",
        )
        return
    logger.info(
        "Plan für %s fertig — Sollwerte werden in %.0f s zum Takt geschrieben.",
        tick.strftime("%H:%M"),
        remaining,
    )
    deadline = clock_fn() + remaining
    while True:
        left = deadline - clock_fn()
        if left <= 0:
            return
        sleep_fn(min(poll_interval_sec, left))
        if on_poll is not None:
            on_poll()


def _prefetch_for_next_cycle(tick: datetime, start_at: datetime) -> None:
    """Warm slow input caches for the next cycle in the idle time (spec §8)."""
    from data.live_prefetch import MIN_IDLE_SEC, prefetch_live_inputs

    idle = (start_at - datetime.now()).total_seconds()
    if idle < MIN_IDLE_SEC:
        logger.info("Prefetch übersprungen: nur %.0f s bis zum nächsten Start.", idle)
        return
    try:
        prefetch_live_inputs(tick, start_at)
    except Exception as exc:  # noqa: BLE001 — the cycle fetches its inputs itself
        logger.warning("Prefetch für %s abgebrochen (%s).", tick.strftime("%H:%M"), exc)


def _read_pv_delta(out_of_band: bool) -> float:
    if out_of_band:
        pv_delta = pv_tuner.get_pv_delta_peek()
    else:
        pv_delta = pv_tuner.get_pv_delta_and_update()
    if pv_delta is None:
        logger.warning(
            "Kein PV-Zähler-Delta verfügbar — cons_data nutzt 0.0 kWh für dieses Intervall."
        )
        pv_delta = 0.0
    logger.info(
        "PV-Energie-Delta (Integral letztes Intervall): %.3f kWh", pv_delta
    )
    return pv_delta


def _main_cycle(
    run_trigger: str, timing: CycleTimer, *, tick: datetime | None = None
) -> bool:
    config.reload_config()
    config.require_runtime_params_loaded()
    out_of_band = is_out_of_band_trigger(run_trigger)
    early_start = tick is not None
    closed_interval = None
    if early_start:
        # [T-15, T) is still open; finalized after the hold, right before the writes.
        plausibility_interval = _last_closed_interval
    elif not out_of_band:
        closed_interval = _finalize_previous_interval()
        plausibility_interval = closed_interval
    else:
        plausibility_interval = None

    if out_of_band:
        logger.info(
            "--- Earnie außerplanmäßiger Lauf (v%s, Trigger: %s) ---",
            __version__,
            run_trigger,
        )
    else:
        logger.info("--- Earnie Live-Abfrage gestartet (v%s) ---", __version__)
    from runtime_store.shadow.mode import is_shadow_mode as _shadow_startup

    if _shadow_startup():
        logger.warning(
            "Shadow: cycle setpoints go through the write path for would-write "
            "logging only (no backend send; see shadow_writes.jsonl)."
        )
    elif config.is_loxone_silent_mode():
        if ehal_live.is_ehal_network_backend():
            logger.warning(
                "Silent-Modus aktiv: Optimierung ohne Schreibzugriffe auf EHAL-Southbound."
            )
        else:
            logger.warning(
                "Loxone Silent-Modus aktiv: Optimierung ohne Schreibzugriffe auf den Miniserver."
            )

    profile_manager.check_and_update_profile_if_new_month()

    with timing.phase("ehal_read"):
        current_soc = ehal_live.read_ess_soc()
        if current_soc is None:
            if ehal_live.is_ehal_network_backend():
                logger.warning(
                    "Optimierung wartet auf den EHAL-SoC (noch kein SoC-Wert im "
                    "Push-Posteingang); neuer Versuch in %.0f s.",
                    ABORTED_CYCLE_RETRY_SEC,
                )
            else:
                logger.error("Optimierung abgebrochen: Kein Zugriff auf Loxone SoC.")
            return False
        current_soc_by_id = ehal_live.read_ess_soc_by_id()

    config.is_sunrise_planning_horizon()
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

    with timing.phase("prices_matrix"):
        market_data = fetch_live_day_ahead_prices(planning_end=planning_window.end)
        if not market_data:
            logger.error("Optimierung abgebrochen: Keine Day-Ahead-Preise empfangen.")
            return False

        optimization_matrix = profile_manager.build_live_planning_matrix(
            market_data, planning_window
        )
        cycle_duration_stats.set_horizon_slots(len(optimization_matrix))
        pv_api_status = pv_forecast.get_api_status()
        if pv_api_status["retry_at"]:
            logger.warning(
                "forecast.solar Rate-Limit (HTTP 429): Nächster API-Aufruf erlaubt ab %s "
                "(PV-Quelle: %s, Cache: %s).",
                pv_api_status["retry_at"],
                pv_api_status["source"],
                "ja" if pv_api_status["cache_available"] else "nein",
            )
        elif pv_api_status["using_synthetic_fallback"]:
            logger.warning(
                "forecast.solar: Synthetischer PV-Fallback aktiv (keine API-Daten)."
            )
        from data.planning_window import sunrise_anchor_slot_index

        sunrise_soc_min_index = sunrise_anchor_slot_index(planning_window)
        pv_forecast_kw_for_log = float(optimization_matrix[0]["expected_p_pv"])

    with timing.phase("ehal_read"):
        live_power = ehal_live.read_live_power_kw()
        flex_kw_for_matrix: dict[str, float] = {}
        if live_power:
            if ehal_live.is_ehal_network_backend():
                flex_kw_for_matrix = {}
            else:
                flex_kw_for_matrix = ehal_live.fetch_flexible_consumers_live_kw()
            matrix_snapshot = live_consumption.build_consumption_snapshot(
                live_power, flex_kw_for_matrix
            )
            reject_reason = live_consumption.reject_live_matrix_snapshot_reason(
                matrix_snapshot
            )
            if reject_reason == "all_zero":
                logger.warning(
                    "Live-Telemetrie liefert Nullwerte (PV/Haus/Netz/Batterie) — "
                    "Optimierungsmatrix behält Prognose-Werte."
                )
            elif reject_reason == "negative_house":
                logger.warning(
                    "Live-Telemetrie: house_kw=%.3f ungültig (negativ) — "
                    "Optimierungsmatrix behält Prognose-Werte.",
                    float(matrix_snapshot.get("house_kw") or 0.0),
                )
            elif reject_reason is None:
                optimization_matrix = live_consumption.apply_live_snapshot_to_matrix(
                    optimization_matrix, matrix_snapshot, hour_index=0
                )
                logger.info(
                    "Live-Snapshot in Optimierungsmatrix: PV=%.2f kW, Grundlast=%.2f kW",
                    matrix_snapshot["pv_kw"],
                    matrix_snapshot["baseload_kw"],
                )
            else:
                logger.warning(
                    "Live-Telemetrie abgelehnt (%s) — Optimierungsmatrix behält Prognose-Werte.",
                    reject_reason,
                )


    reported_soc = float(current_soc)
    prev_logged_soc = optimization_history.latest_logged_soc_percent()
    if prev_logged_soc is not None:
        battery_kw = float(live_power["battery"]) if live_power else 0.0
        history_rows = optimization_history._sorted_history_rows(
            optimization_history._load_jsonl_history()
        )
        history_raw = [
            (row.get("_raw") or row)
            for row in history_rows
            if isinstance(row.get("_raw") or row, dict)
        ]
        consecutive_reported = count_consecutive_reported_soc(
            history_raw, reported_soc
        )
        closed_confirms = closed_interval_confirms_reported(
            plausibility_interval, reported_soc, prev_logged_soc
        )
        if closed_confirms:
            consecutive_reported = max(consecutive_reported, 2)
        current_soc, soc_corrected = sanitize_soc_reading(
            prev_logged_soc,
            reported_soc,
            battery_kw,
            consecutive_same_reported=consecutive_reported,
        )
        if soc_corrected and abs(float(current_soc) - reported_soc) > 0.05:
            logger.warning(
                "SoC-Lesung korrigiert: Miniserver %.1f%% → %.1f%% "
                "(Integration aus %.1f%%, Batterie %.2f kW).",
                reported_soc,
                current_soc,
                prev_logged_soc,
                battery_kw,
            )
        elif closed_confirms and abs(reported_soc - float(prev_logged_soc)) > 1.0:
            logger.info(
                "SoC-Kette verworfen: Miniserver %.1f%% bestätigt durch "
                "Intervall-Sampler (Start %.1f%% → Ende %.1f%%), Historie war %.1f%%.",
                reported_soc,
                float((plausibility_interval or {}).get("soc_start_percent") or reported_soc),
                float((plausibility_interval or {}).get("soc_end_percent") or reported_soc),
                float(prev_logged_soc),
            )

    current_hour = planning_now().hour
    targets = consumer_targets.resolve_consumer_daily_targets(matrix=optimization_matrix)
    if ehal_live.is_ehal_network_backend():
        live_consumers = config.get_flexible_consumers()
    else:
        live_consumers = ehal_live.consumers_with_live_nominal_power()
    from optimizer.absent_mode import (
        apply_absent_mode_to_live_flex,
        resolve_absent_status,
    )

    house_profile = (config.get_resolved_runtime_settings() or {}).get(
        "_house_profile"
    ) or {}
    absent_status = resolve_absent_status(house_profile)
    if absent_status["effective"]:
        logger.info(
            "Abwesenheitsmodus wirksam (Quelle: %s).",
            absent_status["source"] or "?",
        )
        live_consumers = apply_absent_mode_to_live_flex(
            live_consumers,
            house_profile,
            active=True,
        )
    live_ids = {str(c.get("id") or "") for c in live_consumers}
    targets = {
        cid: value for cid, value in (targets or {}).items() if cid in live_ids
    }
    baseline_targets = consumer_targets.resolve_historical_baseline_targets_kwh(
        matrix=optimization_matrix,
    )
    thermal_horizon = thermal_horizon_hours_from_slots(len(optimization_matrix))
    thermal_observability = collect_thermal_observability(
        live_consumers,
        active_targets_kwh=targets,
        baseline_targets_kwh=baseline_targets,
        horizon=thermal_horizon,
    )
    thermal_observability.extend(
        collect_heat_storage_observability(
            list(house_profile.get("consumers") or []),
            house_profile=house_profile,
            horizon=thermal_horizon,
        )
    )
    for item in thermal_observability:
        if item.get("error"):
            logger.warning(
                "Thermisch %s: %s",
                item.get("consumer_id", "?"),
                item["error"],
            )
            continue
        _rc = item.get("readings_c") or {}
        # Optional °C may be None (missing live Ist / heat_storage uses temp_eq).
        _ist_c = _rc.get("actual")
        if _ist_c is None:
            _ist_c = _rc.get("temp_eq")
        _band_min = _rc.get("band_min")
        _band_max = _rc.get("band_max")
        logger.info(
            "Thermisch %s (mode=%s): aktiv %.2f kWh, thermisch %.2f kWh, Delta %+.2f kWh, "
            "Heizstunden %s, Ist %s °C, Band %s–%s °C%s",
            item["consumer_id"],
            item.get("mode"),
            item.get("active_target_kwh", 0.0),
            item.get("thermal_target_kwh", 0.0),
            item.get("delta_kwh", 0.0),
            item.get("heating_hours", 0),
            "n/a" if _ist_c is None else f"{float(_ist_c):.1f}",
            "n/a" if _band_min is None else f"{float(_band_min):.1f}",
            "n/a" if _band_max is None else f"{float(_band_max):.1f}",
            (
                f", historical {item['baseline_target_kwh']:.2f} kWh"
                if item.get("baseline_target_kwh") is not None
                else ""
            ),
        )
    recorder_token = None
    try:
        recorder_token = cycle_recorder.begin_cycle(
            optimization_matrix=optimization_matrix,
            planning_window=planning_window,
            soc_percent=float(current_soc),
            soc_percent_by_ess={
                str(ess_id): float(soc)
                for ess_id, soc in (current_soc_by_id or {}).items()
            },
            targets=targets,
        )
    except Exception as exc:  # noqa: BLE001 — never abort live run
        logger.warning("cycle_recorder: begin_cycle failed: %s", exc)
        recorder_token = None
    with timing.phase("prepare"):
        optimization_matrix, charging_contexts, targets = optimizer.prepare_optimization_matrix(
            optimization_matrix,
            targets,
            consumers=live_consumers,
        )
        delivery_plausibility: dict = {}
        filter_contexts = optimizer.resolve_filter_contexts(optimization_matrix, live_consumers)
        consumer_remaining = optimizer.get_consumer_remaining_kwh(
            consumer_daily_targets_kwh=targets,
            optimization_matrix=optimization_matrix,
            charging_contexts=charging_contexts,
            filter_contexts=filter_contexts,
            live_flex_kw=flex_kw_for_matrix,
            trigger_snapshot=None,
            delivery_plausibility=delivery_plausibility,
        )
        for consumer in live_consumers:
            lox = (consumer.get("charging_schedule") or {}).get("loxone") or {}
            if lox.get("get_evcs_nominal_current") or lox.get(
                "sens_evcs_nominal_current"
            ) or lox.get("nominal_power_kw_name"):
                marker = (
                    lox.get("get_evcs_nominal_current")
                    or lox.get("sens_evcs_nominal_current")
                    or lox.get("nominal_power_kw_name")
                )
                logger.info(
                    "Verbraucher %s: Nennleistung live = %.2f kW (Loxone: %s)",
                    consumer["name"],
                    consumer["nominal_power_kw"],
                    marker,
                )
        from optimizer.live_export_limit import resolve_live_export_context

        telemetry_for_export = None
        try:
            telemetry_for_export = ehal_live.get_adapter().read_telemetry()
        except Exception as exc:  # noqa: BLE001 — Live continues without inbound cap
            logger.warning("Export-Limit Telemetrie nicht lesbar: %s", exc)
        try:
            from integrations.ehal_live_ess_limits import (
                enrich_telemetry_with_ess_live_limits,
            )

            telemetry_for_export = enrich_telemetry_with_ess_live_limits(
                telemetry_for_export
            )
        except Exception as exc:  # noqa: BLE001 — limits stay HK when enrich fails
            logger.warning("ESS live-limit Telemetrie-Anreicherung fehlgeschlagen: %s", exc)
        from settings.ess_limits_resolve import apply_effective_ess_limits

        get_battery_list = getattr(config, "get_battery_params_list", None)
        listed_batteries = get_battery_list() if callable(get_battery_list) else None
        if listed_batteries and len(listed_batteries) > 1:
            battery_params = [
                apply_effective_ess_limits(bat, telemetry=telemetry_for_export)
                for bat in listed_batteries
                if isinstance(bat, dict)
            ]
        else:
            battery_params = apply_effective_ess_limits(
                config.get_battery_params(), telemetry=telemetry_for_export
            )
        from optimizer.powerstation_live import (
            advance_virtual_reserves_from_plan,
            apply_reserves_to_battery_params,
            cycle_powerstation_charge_kw,
            cycle_standby_source_selects,
            load_active_reserves,
            load_standby_packs,
            physical_charge_setpoints_kw,
            planned_powerstation_loxone_sent,
            sync_triggers_from_telemetry,
            write_cycle_powerstation_setpoints,
        )
        from optimizer.powerstation_standby import (
            apply_standby_load_relief,
            live_source_and_charge,
            plan_standby_horizon,
        )
        from optimizer.slot_duration import DEFAULT_DT_H

        active_reserves = load_active_reserves()
        sync_triggers_from_telemetry(telemetry_for_export, active_reserves)
        # Re-load after trigger updates so MILP sees discharging state.
        active_reserves = load_active_reserves()
        battery_params = apply_reserves_to_battery_params(
            battery_params, active_reserves
        )
        battery_params = ehal_live.filter_planning_batteries_with_soc(
            battery_params, current_soc_by_id
        )
        standby_packs = load_standby_packs(telemetry=telemetry_for_export)
        standby_plans = plan_standby_horizon(
            optimization_matrix,
            standby_packs,
            current_soc_by_id=current_soc_by_id or None,
            dt_h=DEFAULT_DT_H,
        )
        if standby_plans:
            optimization_matrix = apply_standby_load_relief(
                optimization_matrix, standby_plans
            )
            logger.info(
                "standby_backup plans: %s",
                {
                    ps: {
                        "slot0_source": (plan.get("source_select") or [None])[0],
                        "load_kw": plan.get("load_kw"),
                        "slot0_charge_kw": (plan.get("charge_kw") or [None])[0],
                    }
                    for ps, plan in standby_plans.items()
                },
            )
        export_ctx = resolve_live_export_context(
            matrix_row=optimization_matrix[0] if optimization_matrix else None,
            telemetry=telemetry_for_export,
        )
    with timing.phase("milp_live"):
        mode, target_power, target_soc, consumer_powers, consumer_pv_follow, milp_plan, urgent_obs = optimizer.milp_optimizer(
            optimization_matrix,
            current_hour,
            current_soc,
            battery_params=battery_params,
            consumers=live_consumers,
            consumer_remaining_kwh=consumer_remaining,
            charging_contexts=charging_contexts,
            filter_contexts=filter_contexts,
            sunrise_soc_min_index=sunrise_soc_min_index,
            consumer_continue_on=optimizer.get_generic_flex_continue_on(
                charging_contexts, live_consumers
            ),
            hk_max_export_kw=export_ctx["hk_max_export_kw"],
            inbound_export_limit_kw=export_ctx["inbound_export_limit_kw"],
            current_soc_by_id=current_soc_by_id or None,
        )
    cycle_duration_stats.mark_ready()
    if early_start:
        with timing.phase("hold"):
            _hold_until_tick(tick)
        closed_interval = _finalize_previous_interval()
    pv_delta = _read_pv_delta(out_of_band)

    with timing.phase("writes"):
        plant_curtail_kw = float((milp_plan or {}).get("p_pv_curtail") or 0.0)
        # Export cap travels only on set_grid_export_power_limit; set_ess_mode stays battery-only.
        export_cap = export_ctx["effective_export_cap_kw"]
        if isinstance(battery_params, list):
            from optimizer.milp_horizon import aggregate_battery_params_for_load

            primary_battery = aggregate_battery_params_for_load(battery_params)
        else:
            primary_battery = battery_params
        battery_plan_kw = optimizer.battery_plan_kw_from_control(
            mode,
            target_power,
            optimization_matrix[0]["expected_p_pv"],
            optimization_matrix[0]["expected_p_act"],
            sum(consumer_powers.values()),
            primary_battery["max_power_kw"],
        )
        advance_virtual_reserves_from_plan(
            battery_plan_kw=float(battery_plan_kw),
            dt_h=DEFAULT_DT_H,
            reserves=active_reserves,
        )
        reserve_charges = physical_charge_setpoints_kw(active_reserves)
        standby_sources, standby_charges = live_source_and_charge(standby_plans, slot=0)
        # Hard clamp to effective pack max (HK ∩ live) — never write above resolve.
        max_by_ps = {
            str(p["powerstation_id"]): float(p.get("max_charge_power_kw") or 0.0)
            for p in standby_packs
            if str(p.get("powerstation_id") or "").strip()
        }
        for ps_id, kw in list(standby_charges.items()):
            cap = max_by_ps.get(str(ps_id))
            if cap is not None:
                standby_charges[ps_id] = min(max(0.0, float(kw)), max(0.0, cap))
        # Refresh all mapped PS set_* Merkers every cycle (idle → charge 0 / mode 0 / grid).
        phys_charge = cycle_powerstation_charge_kw(reserve_charges, standby_charges)
        standby_sources = cycle_standby_source_selects(standby_sources)
        if standby_sources:
            logger.info(
                "standby_backup source_select (0=grid/1=battery): %s", standby_sources
            )
        powerstation_writes = write_cycle_powerstation_setpoints(
            phys_charge, standby_sources
        )

        logger.info(
            "Berechnete Werte für Loxone -> MODE: %s | TARGET_POWER: %s kW | "
            "TARGET_SOC: %s | Verbraucher: %s | pv_follow: %s",
            mode, target_power, target_soc, consumer_powers, consumer_pv_follow,
        )

        current_market_item = optimization_matrix[0]

        ehal_writes: list[dict] | None = None
        from runtime_store.shadow.writes import should_invoke_setpoint_writes

        if not should_invoke_setpoint_writes(silent=config.is_loxone_silent_mode()):
            if ehal_live.is_ehal_network_backend():
                logger.info(
                    "Silent-Modus: Steuerwerte (EHAL ESS+EVCS) werden nicht gesendet."
                )
            else:
                logger.info(
                    "Silent-Modus: Steuerwerte (Huawei-Modbus, flexible Verbraucher) "
                    "werden nicht an Loxone gesendet."
                )
            loxone_writes: list[dict] | None = None
        elif ehal_live.is_ehal_network_backend():
            backend = "HA" if ehal_live.is_ha_backend() else "OpenEMS"
            logger.info("Sende EHAL ESS-Limits an %s...", backend)
            err_ess, ess_records = ehal_live.write_ess_setpoints_from_control(
                mode,
                target_power,
                export_cap_kw=export_cap,
                telemetry=telemetry_for_export,
            )
            logger.info("Sende EHAL EVCS-Maxstrom an %s...", backend)
            err_evcs, evcs_records = ehal_live.write_evcs_max_current_from_consumers(
                consumer_powers, charging_contexts, consumer_pv_follow
            )
            logger.info("Sende EHAL WR-AC-Limits an %s...", backend)
            err_inv, inv_records = ehal_live.write_inv_ac_limits_from_plan(
                plant_curtail_kw=plant_curtail_kw,
                matrix_row=optimization_matrix[0] if optimization_matrix else None,
                milp_plan=milp_plan if isinstance(milp_plan, dict) else None,
            )
            flex_enable_records: list[dict] = []
            if ehal_live.is_ha_backend():
                # Heat pump / pool / generic enables; the EV current went out above.
                logger.info("Sende EHAL Flex-Freigaben an %s...", backend)
                flex_enable_records = ehal_live.write_flex_enables_for_ha(
                    consumer_powers, charging_contexts, consumer_pv_follow
                )
            if err_ess is None and err_evcs is None and err_inv is None:
                ehal_live.clear_write_error()
            ehal_writes = (
                list(ess_records)
                + list(evcs_records)
                + list(inv_records)
                + list(flex_enable_records)
            )
            loxone_writes = None
        else:
            logger.info("📤 Sende gemappte Huawei-Modbus-Werte an Loxone...")
            huawei_writes = ehal_live.write_huawei_modbus_states(
                mode, target_power, target_soc, export_cap_kw=export_cap
            )
            logger.info("📤 Sende flexible Verbraucher-Sollwerte an Loxone...")
            flex_writes = ehal_live.write_flexible_consumer_states(
                consumer_powers, charging_contexts, consumer_pv_follow
            )
            logger.info("📤 Sende WR-AC-Limits an Loxone...")
            _err_inv, inv_rows = ehal_live.write_inv_ac_limits_from_plan(
                plant_curtail_kw=plant_curtail_kw,
                matrix_row=optimization_matrix[0] if optimization_matrix else None,
                milp_plan=milp_plan if isinstance(milp_plan, dict) else None,
            )
            loxone_writes = serialize_write_records(
                list(huawei_writes) + list(flex_writes) + list(powerstation_writes)
            ) + list(inv_rows)

        if live_power is None:
            live_power = ehal_live.read_live_power_kw()
        total_kw = live_power["house"] if live_power else None
        from optimizer.charging_context import matrix_slot_datetime

        if ehal_live.is_ehal_network_backend():
            flex_kw = {c["id"]: 0.0 for c in live_consumers}
            flex_chart_kw = dict(flex_kw)
            live_flex_measured: set[str] = set()
        else:
            live_flex = ehal_live.resolve_flexible_consumers_live_power(
                fallbacks=consumer_powers,
                consumers=live_consumers,
                filter_contexts=filter_contexts,
                slot_datetime=matrix_slot_datetime(optimization_matrix, 0),
            )
            flex_kw = live_flex.kw
            flex_chart_kw = live_flex.chart_kw
            live_flex_measured = live_flex.measured_ids
        logger.info("cons_data Flex live (kW): %s", flex_kw)
        logger.info(
            "Chart-Ist Flex (kW): %s | gemessen: %s",
            flex_chart_kw,
            sorted(live_flex_measured),
        )

        loxone_sent = ehal_live.build_sent_loxone_snapshot(
            mode,
            target_power,
            target_soc,
            consumer_powers,
            charging_contexts,
            consumer_pv_follow,
            export_cap_kw=export_cap,
        )
        loxone_sent.update(
            planned_powerstation_loxone_sent(phys_charge, standby_sources)
        )
        sent_flex_kw: dict[str, float] = {}
        for consumer in live_consumers:
            setpoint_name = marker_set_evcs_max_current(consumer)
            if not setpoint_name:
                continue
            amps = float(loxone_sent.get(setpoint_name, 0.0) or 0.0)
            voltage_v, phases = ev_nominal_power_conversion(consumer)
            sent_flex_kw[consumer["id"]] = round(
                ampere_to_kw(amps, voltage_v=voltage_v, phases=phases), 3
            )

        delivery_compliance = optimizer.register_consumer_delivery(
            consumer_powers,
            charging_contexts=charging_contexts,
            consumers=live_consumers,
            live_flex_kw=flex_kw,
            sent_flex_kw=sent_flex_kw,
            book_planned=not out_of_band,
        )
    cycle_duration_stats.mark_writes_done()

    savings_snapshot = None
    savings_info = None
    with timing.phase("savings"):
        try:
            savings_info = optimizer.calculate_optimization_savings(
                optimization_matrix,
                float(current_soc),
                consumer_daily_targets_kwh=targets,
                sunrise_soc_min_index=sunrise_soc_min_index,
                filter_contexts=filter_contexts,
                consumers=live_consumers,
                current_soc_by_id=current_soc_by_id or None,
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

    with timing.phase("persist"):
        if not out_of_band:
            try:
                written = cons_data_store.record_and_maybe_flush(
                    total_kw=total_kw,
                    pv_kwh_interval=pv_delta,
                    flex_kw=flex_kw,
                )
                if written:
                    logger.info(
                        "cons_data: %s Stunde(n) in cons_data.csv geschrieben.", written
                    )
            except Exception as e:
                logger.warning(
                    "cons_data: Messwerte konnten nicht gespeichert werden: %s", e
                )

        consumption_snapshot = None
        if live_power:
            consumption_snapshot = live_consumption.build_consumption_snapshot(
                live_power, flex_chart_kw
            )
            if live_consumption.is_dead_telemetry_snapshot(consumption_snapshot):
                logger.warning(
                    "Live-Telemetrie liefert Nullwerte (PV/Haus/Netz/Batterie) — "
                    "consumption_snapshot wird nicht ins Produktiv-Log geschrieben."
                )
                consumption_snapshot = None

        try:
            if "k_act" not in current_market_item:
                raise KeyError(
                    "optimization_matrix[0] fehlt 'k_act' (Bezugspreis Cent/kWh) "
                    "für market_price_cent im Produktiv-Log."
                )
            market_price_cent = round(float(current_market_item["k_act"]), 4)
            epex_price_cent = round(float(current_market_item["price_buy"]), 4)
            from integrations.ehal_write import load_published_records
            from optimizer.powerstation_soc_chart import load_virtual_soc_by_id

            soc_percent_by_ess = {
                str(ess_id): round(float(soc), 2)
                for ess_id, soc in (current_soc_by_id or {}).items()
            }
            soc_percent_by_ess.update(load_virtual_soc_by_id())

            run_payload = {
                "source": "main.py",
                "success": True,
                "run_trigger": run_trigger,
                "silent_mode": config.is_silent_mode(),
                "optimization_interval_sec": optimization_schedule.optimization_interval_seconds(),
                "event_trigger_snapshot": {},
                "loxone_sent": loxone_sent,
                "loxone_writes": loxone_writes,
                "ehal_writes": ehal_writes,
                "ehal_published": load_published_records(),
                "soc_percent": round(float(current_soc), 2),
                "soc_percent_by_ess": soc_percent_by_ess,
                "reported_soc_percent": round(float(reported_soc), 2),
                "pv_delta_kwh": round(float(pv_delta), 4),
                "market_price_cent": market_price_cent,
                "epex_price_cent": epex_price_cent,
                "k_push_act": round(
                    k_push_act_for_matrix_row(
                        current_market_item,
                        config.get_push_price_cent(),
                    ),
                    4,
                ),
                "forecast_pv_kw": round(pv_forecast_kw_for_log, 3),
                "forecast_consumption_kw": round(
                    float(optimization_matrix[0]["expected_p_act"]), 3
                ),
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
                "charging_contexts": optimizer.serialize_charging_contexts(
                    charging_contexts
                ),
                "filter_contexts": optimizer.serialize_filter_contexts(filter_contexts),
                "urgent_rule_observability": urgent_obs,
                "consumer_pv_follow": {
                    k: int(v) for k, v in consumer_pv_follow.items()
                },
                "flex_live_kw": flex_chart_kw,
                "flex_measured_ids": sorted(live_flex_measured),
                "delivery_compliance": delivery_compliance,
                "delivery_plausibility": delivery_plausibility,
                "thermal_observability": thermal_observability,
                "savings_snapshot": savings_snapshot,
                "consumption_snapshot": consumption_snapshot,
                "closed_interval": closed_interval,
                "current_hour": int(current_hour),
            }
            if consumption_snapshot is not None:
                power_interval_sampler.note_decision_sample(
                    consumption_snapshot,
                    soc_percent=float(current_soc),
                )
            run_state.save_run_state(run_payload)
            if run_payload.get("success"):
                from runtime_store.usage_ping import note_live_cycle_success

                note_live_cycle_success()
            if savings_info:
                try:
                    overlaid_rows = optimizer.overlay_main_run_on_rows(
                        savings_info["optimized_rows"],
                        run_payload,
                    )
                    debug_payload = live_optimization_debug.build_debug_payload(
                        savings_info,
                        overlaid_rows,
                        savings_info["baseline_rows"],
                        kind="live",
                        initial_soc=float(current_soc),
                        main_state=run_payload,
                        quarter_hour_slot=optimization_schedule.quarter_hour_slot_key(),
                        sync_reason="main_synced",
                        optimized_rows_raw=savings_info["optimized_rows"],
                        matched_baseline_rows=savings_info.get("matched_baseline_rows"),
                        baseline_same_flex_rows=savings_info.get(
                            "baseline_same_flex_rows"
                        ),
                        source="main.py",
                        planning_matrix=optimization_matrix,
                        planning_window=serialize_planning_window(planning_window),
                    )
                    live_optimization_debug.save_debug_snapshot(debug_payload)
                    logger.info(
                        "live_optimization_debug: Anzeige-Snapshot gespeichert (%d Sim-Zeilen).",
                        len(overlaid_rows),
                    )
                except Exception as exc:
                    logger.warning(
                        "live_optimization_debug: Snapshot konnte nicht gespeichert werden: %s",
                        exc,
                    )
            try:
                optimization_history.append_production_run(run_payload)
            except OSError as exc:
                logger.warning("optimization_history: Anhängen fehlgeschlagen: %s", exc)
            logger.info("run_state: Durchlauf in optimizer_run_state.json gespeichert.")
        except Exception as e:
            logger.warning("run_state: Zustand konnte nicht gespeichert werden: %s", e)

        try:
            immediate = any(
                bool((ctx or {}).get("immediate_charge"))
                for ctx in (charging_contexts or {}).values()
            )
            cycle_recorder.finish_cycle(
                recorder_token,
                mode=int(mode),
                target_power_kw=round(float(target_power), 3),
                battery_plan_kw=battery_plan_kw,
                consumer_powers_kw={
                    k: round(float(v), 3) for k, v in consumer_powers.items()
                },
                flags={
                    "override": bool(config.is_silent_mode()),
                    "immediate_charging": immediate,
                    "outage": bool(out_of_band),
                    "manual_intervention": False,
                },
            )
        except Exception as exc:  # noqa: BLE001 — never abort live run
            logger.warning("cycle_recorder: finish_cycle failed: %s", exc)
    return True


if __name__ == "__main__":
    from runtime_store import bootstrap
    from runtime_store.config_drift import log_config_drift
    from runtime_store.persist_paths import log_file

    bootstrap.run()
    reinit_config_or_exit(config)
    logger_config.setup_logging(log_file=log_file(), level=logging.INFO)
    log_config_drift(logging.getLogger("main"))
    from runtime_store.shadow import refuse_shadow_startup_or_exit

    refuse_shadow_startup_or_exit()
    try:
        ensure_single_instance("main")
    except SingleInstanceError as exc:
        logger.error("%s", exc)
        print(f"Abbruch: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    _sep = "=" * 72
    logger.info(_sep)
    logger.info(
        "main.py started — pid=%s — Earnie %s",
        os.getpid(),
        __version__,
    )
    logger.info(_sep)

    from scripts.startup_checks import (
        prepare_loxone_push_inbox_for_startup,
        run_live_scenario_entity_check_on_startup,
        run_loxone_verify_on_startup,
        run_tariff_plausibility_on_startup,
    )
    from integrations.ehal_request_http import start_ehal_request_http

    from runtime_store.clock_skew import install_requests_hook

    # Clock-skew diagnostics from Date headers of responses the cycle receives anyway.
    install_requests_hook()
    run_tariff_plausibility_on_startup()
    run_live_scenario_entity_check_on_startup()
    prepare_loxone_push_inbox_for_startup(
        start_http_fn=lambda: start_ehal_request_http(config.get_ehal_http_port()),
    )
    run_loxone_verify_on_startup()
    ehal_live.push_safe_setpoints_on_startup()

    from runtime_store.dotenv_io import (
        deferred_loxone_blocks_live,
        needs_loxone_setup,
    )
    from runtime_store.dotenv_loader import load_app_dotenv
    from runtime_store.daemon_heartbeat import touch_daemon_heartbeat
    from runtime_store.env_vars import is_planning_offline_gated
    from runtime_store.setup_gate_log import log_setup_gate_wait
    from ui.setup_readiness import is_planning_ready, needs_planning_onboarding

    _SETUP_WAIT_SEC = 60
    _setup_gate_state: dict = {}
    next_trigger = TRIGGER_QUARTER_HOUR
    cold_start = True
    woke_at: datetime | None = None
    # Early start (EarlyStart P1): tick + lead of the next regular cycle; None for
    # the first run after start and after an out-of-band wake.
    early_start_on = early_start_enabled()
    pending_tick: datetime | None = None
    pending_lead_sec = 0.0
    lead_was_capped = False

    while True:
        touch_daemon_heartbeat()
        if needs_loxone_setup():
            log_setup_gate_wait(
                _setup_gate_state,
                "loxone_setup",
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

        if deferred_loxone_blocks_live():
            log_setup_gate_wait(
                _setup_gate_state,
                "loxone_deferred",
                "Loxone-Zugangsdaten noch nicht hinterlegt (optional bis Live-/Silent-Betrieb). "
                "Planung/Backtesting in der UI (Port %s) möglich. "
                "Erneuter Versuch in %s Sekunden.",
                config.get_ui_streamlit_port(),
                _SETUP_WAIT_SEC,
                level=logging.INFO,
            )
            time.sleep(_SETUP_WAIT_SEC)
            config.reinit_config()
            continue

        if is_planning_offline_gated():
            log_setup_gate_wait(
                _setup_gate_state,
                "planning_offline",
                "Live-Szenario unvollständig (Planung offline). "
                "Bitte in der Streamlit-UI (Port %s) das Live-Szenario im "
                "Szenarienkonfigurator vervollständigen (Entitäts-Referenzen speichern). "
                "Erneuter Versuch in %s Sekunden.",
                config.get_ui_streamlit_port(),
                _SETUP_WAIT_SEC,
            )
            time.sleep(_SETUP_WAIT_SEC)
            config.reinit_config()
            continue

        if needs_planning_onboarding() and not is_planning_ready():
            log_setup_gate_wait(
                _setup_gate_state,
                "planning_onboarding",
                "Planungs-Konfiguration unvollständig. "
                "Bitte in der Streamlit-UI (Port %s) Hauskonfigurator und Runtime-Szenario abschließen. "
                "Erneuter Versuch in %s Sekunden.",
                config.get_ui_streamlit_port(),
                _SETUP_WAIT_SEC,
            )
            time.sleep(_SETUP_WAIT_SEC)
            config.reinit_config()
            continue

        from integrations.loxone_connectivity import (
            LoxoneAuthError,
            probe_current_loxone_credentials,
        )
        from runtime_store.loxone_auth_error import (
            clear_loxone_auth_error,
            needs_loxone_auth_recovery,
            persist_loxone_auth_error,
        )

        if needs_loxone_auth_recovery():
            from runtime_store.shadow import maybe_clear_auth_gate

            if not maybe_clear_auth_gate():
                ok, detail = probe_current_loxone_credentials()
                if ok:
                    clear_loxone_auth_error()
                else:
                    if detail.startswith("Loxone auth failed"):
                        code = 401 if "HTTP 401" in detail else 403
                        persist_loxone_auth_error(
                            message=detail,
                            http_status=code,
                            source="main_gate",
                        )
                    log_setup_gate_wait(
                        _setup_gate_state,
                        "loxone_auth",
                        "Loxone-Zugang verweigert (%s). "
                        "Bitte Zugangsdaten in der Streamlit-UI (Port %s) unter "
                        "Smarthome-Backend prüfen. Erneuter Versuch in %s Sekunden.",
                        detail,
                        config.get_ui_streamlit_port(),
                        _SETUP_WAIT_SEC,
                    )
                    time.sleep(_SETUP_WAIT_SEC)
                    load_app_dotenv(override=True)
                    config.reinit_config()
                    continue

        _setup_gate_state.clear()
        try:
            from runtime_store.shadow import (
                after_prod_cycle,
                prepare_shadow_cycle,
                resolve_next_trigger,
            )
            from runtime_store.loxone_push_inbox import log_link_transition

            log_link_transition()

            prep = prepare_shadow_cycle(
                next_trigger, optimize_trigger=TRIGGER_REQUEST_OPTIMIZE
            )
            next_trigger = prep.trigger
            if prep.skipped:
                logger.warning(
                    "shadow: cycle skipped (%s) — warte %ss",
                    prep.reason,
                    _SETUP_WAIT_SEC,
                )
                time.sleep(_SETUP_WAIT_SEC)
                continue

            cycle_woke_at, woke_at = woke_at, None
            cycle_cold_start, cold_start = cold_start, False
            cycle_tick, pending_tick = pending_tick, None
            if next_trigger != TRIGGER_QUARTER_HOUR or (
                # Stale after a skipped/failed iteration: plan for the current slot.
                cycle_tick is not None
                and datetime.now() >= cycle_tick
                + timedelta(minutes=optimization_schedule.QUARTER_HOUR_MINUTES)
            ):
                cycle_tick = None
            completed = main(
                run_trigger=next_trigger,
                woke_at=cycle_woke_at,
                cold_start=cycle_cold_start,
                tick=cycle_tick,
                lead_sec=pending_lead_sec,
            )
            if not completed:
                next_trigger = _wait_after_aborted_cycle()
                woke_at = datetime.now()
                continue
            clear_loxone_auth_error()
            next_trigger = TRIGGER_QUARTER_HOUR
            after_prod_cycle()
            from runtime_store.usage_ping import spawn_maybe_send_ping

            spawn_maybe_send_ping()

            decision = decide_lead(
                cycle_duration_stats.load_records(),
                platform=cycle_duration_stats.platform_info()["id"],
                enabled=early_start_on,
            )
            if decision.capped and not lead_was_capped:
                logger.warning(
                    "Vorlauf-Schätzung %.0f s > %.0f s (Median der letzten %d Läufe) — "
                    "Start wird nicht weiter vorverlegt; Sollwerte können zu spät kommen.",
                    decision.estimate_sec,
                    LEAD_MAX_SEC,
                    decision.samples,
                )
            lead_was_capped = decision.capped
            now = datetime.now()
            next_tick, start_at = next_regular_start(now, decision.lead_sec)
            _prefetch_for_next_cycle(next_tick, start_at)
            now = datetime.now()
            wait_sec = max(0.0, (start_at - now).total_seconds())
            if early_start_on:
                pending_tick, pending_lead_sec = next_tick, decision.lead_sec
                logger.info(
                    "✅ Durchlauf erfolgreich beendet. Nächster regulärer Lauf um %s "
                    "für den Takt %s (Vorlauf %.0f s, %s; in %.0f s).",
                    start_at.strftime("%H:%M:%S"),
                    next_tick.strftime("%H:%M"),
                    decision.lead_sec,
                    decision.reason,
                    wait_sec,
                )
            else:
                logger.info(
                    "✅ Durchlauf erfolgreich beendet. Nächster regulärer Lauf um %s (in %.0f s).",
                    start_at.strftime("%H:%M:%S"),
                    wait_sec,
                )
            early = wait_until_next_run(
                total_wait_sec=wait_sec,
                on_poll=_daemon_wait_poll,
            )
            woke_at = datetime.now()
            next_trigger = resolve_next_trigger(
                early,
                next_trigger,
                optimize_trigger=TRIGGER_REQUEST_OPTIMIZE,
            )

        except LoxoneAuthError as exc:
            logger.error(
                "Loxone-Zugang verweigert (HTTP %s). Optimierung pausiert — "
                "erneuter Versuch in %s Sekunden.",
                exc.http_status,
                _SETUP_WAIT_SEC,
            )
            time.sleep(_SETUP_WAIT_SEC)
            load_app_dotenv(override=True)
            config.reinit_config()
        except Exception as e:
            logger.exception(
                "🚨 Unerwarteter Fehler während des Durchlaufs: %s", e
            )
            print(
                "🔄 Skript läuft weiter. Schneller Wiederholungsversuch in 60 Sekunden...",
                flush=True,
            )
            time.sleep(60)

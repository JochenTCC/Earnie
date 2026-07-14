# optimizer.py – Facade: Verbraucher-State und Re-Exports für Abwärtskompatibilität
"""
Öffentliche Einstiegsschnittstelle für main.py, app.py und Tests.

Implementierung liegt in optimizer.battery, optimizer.milp, optimizer.simulation,
optimizer.targets und optimizer.charging_context. Neue Aufrufer sollen diese Facade nutzen,
nicht die Submodule direkt.
"""
from datetime import datetime
import json
import os

import config
from . import schedule
from .charge_immediate import (
    apply_immediate_charge_to_matrix,
    apply_immediate_charge_chart_display,
    prepare_optimization_matrix,
)
from .charging_context import (
    apply_horizon_charging_limits as _apply_horizon_charging_limits,
    resolve_charging_contexts,
    serialize_charging_contexts,
)
from .charging_session import (
    add_session_delivery,
    is_charging_session_context,
    normalize_consumer_state,
    session_delivered_kwh,
)
from .delivery_tracking import (
    assess_session_delivery,
    booking_power_kw,
    build_delivery_compliance_row,
)
from .filter_context import (
    adjust_targets_for_native_filter,
    resolve_filter_contexts,
    serialize_filter_contexts,
)
from .battery import (
    MODE_AUTOMATIK,
    MODE_ENTLADESPERRE,
    MODE_ZWANGS_ENTLADEN,
    MODE_ZWANGS_LADEN,
    apply_soc_change as _apply_soc_change,
    automatik_discharge_kw as _automatik_discharge_kw,
    battery_plan_kw_from_control,
    charge_kw_for_hourly_soc as _charge_kw_for_hourly_soc,
    clamp_power as _clamp_power,
    discharge_kw_for_hourly_soc as _discharge_kw_for_hourly_soc,
    power_threshold_kw as _power_threshold_kw,
    steuerbefehl_for_mode,
)
from .milp import milp_optimizer
from .simulation import (
    calculate_optimization_savings,
    build_savings_snapshot,
    calculate_step_cost_euro_from_row as _calculate_step_cost_euro_from_row,
    delivered_flex_kwh_from_rows as _delivered_flex_kwh_from_rows,
    flexible_consumer_power_kw as _flexible_consumer_power_kw,
    simulate_24h_horizon,
    simulate_baseline_horizon,
    simulate_matched_baseline_horizon,
    simulate_horizon,
    horizon_end_soc_from_chart_rows,
    horizon_end_soc_percent,
    sync_chart_row_netzbezug,
    total_consumption_kwh_from_rows as _total_consumption_kwh_from_rows,
)
from .targets import (
    build_applied_targets_detail,
    build_baseline_targets_detail,
    build_energy_comparison_detail,
    consumer_column_name as _consumer_column_name,
    consumer_pv_follow_column_name as _consumer_pv_follow_column_name,
    consumer_immediate_charge_column_name as _consumer_immediate_charge_column_name,
    resolve_applied_daily_targets,
    resolve_baseload_kwh,
    resolve_horizon_consumer_targets_kwh,
)
from runtime_store.file_metadata import (
    CONSUMER_STATE_SCHEMA,
    read_schema_version,
    stamp_payload,
    strip_metadata,
)

from runtime_store.persist_paths import consumer_state_file

CONSUMER_STATE_FILE = consumer_state_file()

__all__ = [
    "CONSUMER_STATE_FILE",
    "MODE_AUTOMATIK",
    "MODE_ENTLADESPERRE",
    "MODE_ZWANGS_ENTLADEN",
    "MODE_ZWANGS_LADEN",
    "battery_plan_kw_from_control",
    "build_applied_targets_detail",
    "build_baseline_targets_detail",
    "build_energy_comparison_detail",
    "build_savings_snapshot",
    "calculate_optimization_savings",
    "get_consumer_remaining_kwh",
    "get_spa_remaining_kwh",
    "milp_optimizer",
    "overlay_main_run_on_rows",
    "register_consumer_delivery",
    "register_consumer_hours",
    "register_spa_hour",
    "resolve_applied_daily_targets",
    "resolve_baseload_kwh",
    "apply_immediate_charge_to_matrix",
    "prepare_optimization_matrix",
    "resolve_charging_contexts",
    "resolve_filter_contexts",
    "serialize_charging_contexts",
    "serialize_filter_contexts",
    "resolve_horizon_consumer_targets_kwh",
    "simulate_24h_horizon",
    "simulate_baseline_horizon",
    "simulate_matched_baseline_horizon",
    "simulate_horizon",
    "horizon_end_soc_from_chart_rows",
    "horizon_end_soc_percent",
    "steuerbefehl_for_mode",
    # Von optimization_consistency / simulation_engine genutzt:
    "_apply_soc_change",
    "_calculate_step_cost_euro_from_row",
    "_delivered_flex_kwh_from_rows",
    "_flexible_consumer_power_kw",
    "_total_consumption_kwh_from_rows",
]


def overlay_main_run_on_rows(rows: list[dict], main_state: dict | None) -> list[dict]:
    """Ersetzt Stunde 0 durch den Produktiv-Durchlauf von main.py."""
    if not rows or not main_state or not main_state.get("success"):
        return rows
    updated = [dict(row) for row in rows]
    row = updated[0]
    mode = int(main_state.get("mode", MODE_AUTOMATIK))
    target_power = float(main_state.get("target_power_kw", 0.0) or 0.0)
    row["Steuerbefehl"] = steuerbefehl_for_mode(mode, target_power)
    if "battery_plan_kw" in main_state:
        row["Geplante Batterie-Aktion (kW)"] = float(main_state["battery_plan_kw"])
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        col = _consumer_column_name(consumer)
        if col in row:
            cid = consumer["id"]
            row[col] = float((main_state.get("consumer_powers_kw") or {}).get(cid, 0.0) or 0.0)
        pv_col = _consumer_pv_follow_column_name(consumer)
        if pv_col in row:
            cid = consumer["id"]
            row[pv_col] = int((main_state.get("consumer_pv_follow") or {}).get(cid, 0) or 0)
        imm_col = _consumer_immediate_charge_column_name(consumer)
        if imm_col in row:
            row[imm_col] = 0
    contexts = main_state.get("charging_contexts") or {}
    flex_live = main_state.get("flex_live_kw")
    apply_immediate_charge_chart_display(
        row, 0, contexts, flex_live_kw=flex_live
    )
    sync_chart_row_netzbezug(row)
    updated[0] = row
    return updated


def _active_consumers(consumers: list | None = None) -> list:
    return consumers if consumers is not None else config.get_flexible_consumers(optimizer_only=True)


def _consumers_by_id(consumers: list | None = None) -> dict[str, dict]:
    return {consumer["id"]: consumer for consumer in _active_consumers(consumers)}


def _load_consumer_state(
    charging_contexts: dict[str, dict] | None = None,
    consumers: list | None = None,
) -> dict:
    today = datetime.now().date().isoformat()
    consumers_by_id = _consumers_by_id(consumers)
    if not os.path.exists(CONSUMER_STATE_FILE):
        return normalize_consumer_state(
            {"date": today, "delivered": {}, "charging_sessions": {}, "generic_flex_run": {}},
            today,
            charging_contexts,
            consumers_by_id,
        )
    try:
        with open(CONSUMER_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        schema_version = read_schema_version(state, default=1)
        if schema_version > CONSUMER_STATE_SCHEMA:
            import logging
            logging.getLogger(__name__).warning(
                "flexible_consumers_state: neuere Schema-Version %s (aktuell %s) – lese best effort",
                schema_version,
                CONSUMER_STATE_SCHEMA,
            )
        state = strip_metadata(state)
        return normalize_consumer_state(state, today, charging_contexts, consumers_by_id)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return normalize_consumer_state(
            {"date": today, "delivered": {}, "charging_sessions": {}, "generic_flex_run": {}},
            today,
            charging_contexts,
            consumers_by_id,
        )


def _save_consumer_state(state: dict) -> None:
    payload = stamp_payload(strip_metadata(state), schema_version=CONSUMER_STATE_SCHEMA)
    with open(CONSUMER_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def get_consumer_remaining_kwh(
    consumers: list | None = None,
    optimization_matrix: list | None = None,
    consumer_daily_targets_kwh: dict | None = None,
    charging_contexts: dict[str, dict] | None = None,
    filter_contexts: dict[str, dict] | None = None,
    *,
    live_flex_kw: dict[str, float] | None = None,
    trigger_snapshot: dict | None = None,
    delivery_plausibility: dict[str, dict] | None = None,
) -> dict[str, float]:
    """Verbleibende Zielenergie aller optimierbaren Verbraucher (inkl. Loxone E-Auto)."""
    from data import consumer_targets
    from data.consumer_targets import uses_loxone_debt_counter
    active = _active_consumers(consumers)
    contexts = charging_contexts
    if contexts is None and optimization_matrix is not None:
        contexts = resolve_charging_contexts(
            optimization_matrix, consumer_daily_targets_kwh
        )
    state = _load_consumer_state(contexts, active)
    delivered = state.get("delivered", {})
    sessions = state.get("charging_sessions", {})
    consumers_by_id = _consumers_by_id(active)
    if optimization_matrix is not None:
        daily_targets = resolve_horizon_consumer_targets_kwh(
            optimization_matrix, consumer_daily_targets_kwh
        )
        if contexts is not None:
            daily_targets = _apply_horizon_charging_limits(daily_targets, contexts)
    else:
        daily_targets = consumer_targets.resolve_consumer_daily_targets()
    remaining = {}
    plausibility = delivery_plausibility if delivery_plausibility is not None else {}
    plausibility.clear()
    for consumer in active:
        cid = consumer["id"]
        daily_target = float(daily_targets.get(cid, consumer["daily_target_kwh"]))
        ctx = (contexts or {}).get(cid)
        if uses_loxone_debt_counter(consumer):
            already = 0.0
        elif is_charging_session_context(consumer, ctx):
            booked = session_delivered_kwh(sessions, cid)
            live_kw = (live_flex_kw or {}).get(cid)
            session = sessions.get(cid)
            already, note = assess_session_delivery(
                consumer,
                ctx,
                booked,
                live_kw=live_kw,
                trigger_snapshot=trigger_snapshot,
                session=session,
            )
            if note is not None:
                plausibility[cid] = note
        else:
            already = float(delivered.get(cid, 0.0))
        remaining[cid] = max(0.0, daily_target - already)
    if optimization_matrix is not None:
        remaining = adjust_targets_for_native_filter(
            remaining, active, optimization_matrix, filter_contexts
        )
    return remaining


def get_generic_flex_continue_on(
    charging_contexts: dict[str, dict] | None = None,
    consumers: list | None = None,
) -> dict[str, bool]:
    """Offene generic-min_on-Blöcke für den nächsten MILP-Schritt (Live-Pfad)."""
    from .generic_flex_run import continue_on_from_state

    active = _active_consumers(consumers)
    state = _load_consumer_state(charging_contexts, active)
    return continue_on_from_state(state, active)


def _optimization_interval_hours() -> float:
    """Dauer eines Live-Optimierungszyklus in Stunden (Viertelstunde)."""
    return schedule.optimization_interval_hours()


def register_consumer_delivery(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumers: list | None = None,
    *,
    live_flex_kw: dict[str, float] | None = None,
    sent_flex_kw: dict[str, float] | None = None,
    book_planned: bool = True,
) -> dict[str, dict]:
    """Bucht gelieferte Energie und liefert Soll-Ist-Kennzahlen je Verbraucher."""
    from .generic_flex_run import update_generic_flex_run_state

    interval_h = _optimization_interval_hours()
    active = _active_consumers(consumers)
    consumers_by_id = _consumers_by_id(active)
    state = _load_consumer_state(charging_contexts, active)
    delivered = dict(state.get("delivered", {}))
    sessions = dict(state.get("charging_sessions", {}))
    generic_flex_run = dict(state.get("generic_flex_run") or {})
    compliance: dict[str, dict] = {}

    for consumer in active:
        cid = consumer["id"]
        planned_kw = float(consumer_powers.get(cid, 0.0) or 0.0)
        live_kw = (live_flex_kw or {}).get(cid)
        sent_kw = (sent_flex_kw or {}).get(cid)
        ctx = (charging_contexts or {}).get(cid)
        power_kw = booking_power_kw(
            consumer,
            ctx,
            planned_kw=planned_kw,
            live_kw=live_kw,
            book_planned=book_planned,
        )
        compliance[cid] = build_delivery_compliance_row(
            consumer,
            ctx,
            planned_kw=planned_kw,
            live_kw=live_kw,
            sent_kw=sent_kw,
            booked_kw=power_kw,
        )
        if power_kw <= 0:
            update_generic_flex_run_state(generic_flex_run, consumer, 0.0)
            continue
        delta_kwh = power_kw * interval_h
        if is_charging_session_context(consumer, ctx):
            add_session_delivery(sessions, cid, delta_kwh)
        else:
            delivered[cid] = round(float(delivered.get(cid, 0.0)) + delta_kwh, 3)
        update_generic_flex_run_state(generic_flex_run, consumer, power_kw)

    state["delivered"] = delivered
    state["charging_sessions"] = sessions
    state["generic_flex_run"] = generic_flex_run
    _save_consumer_state(state)
    return compliance


def register_consumer_hours(
    consumer_powers: dict[str, float],
    charging_contexts: dict[str, dict] | None = None,
    consumers: list | None = None,
    *,
    live_flex_kw: dict[str, float] | None = None,
    sent_flex_kw: dict[str, float] | None = None,
    book_planned: bool = True,
) -> dict[str, dict]:
    """Legacy-Alias für register_consumer_delivery."""
    return register_consumer_delivery(
        consumer_powers,
        charging_contexts=charging_contexts,
        consumers=consumers,
        live_flex_kw=live_flex_kw,
        sent_flex_kw=sent_flex_kw,
        book_planned=book_planned,
    )


def get_spa_remaining_kwh() -> float:
    """Legacy: verbleibendes SwimSpa-Tagesziel."""
    return get_consumer_remaining_kwh().get("swimspa", 0.0)


def register_spa_hour(spa_power_kw: float) -> None:
    """Legacy: SwimSpa-Stunde buchen."""
    if spa_power_kw > 0:
        register_consumer_hours({"swimspa": spa_power_kw})

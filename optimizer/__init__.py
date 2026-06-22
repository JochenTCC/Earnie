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
from .charging_context import (
    apply_horizon_charging_limits as _apply_horizon_charging_limits,
    resolve_charging_contexts,
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
    calculate_step_cost_euro_from_row as _calculate_step_cost_euro_from_row,
    delivered_flex_kwh_from_rows as _delivered_flex_kwh_from_rows,
    flexible_consumer_power_kw as _flexible_consumer_power_kw,
    simulate_24h_horizon,
    simulate_baseline_horizon,
    simulate_horizon,
    total_consumption_kwh_from_rows as _total_consumption_kwh_from_rows,
)
from .targets import (
    build_applied_targets_detail,
    build_baseline_targets_detail,
    build_energy_comparison_detail,
    consumer_column_name as _consumer_column_name,
    resolve_applied_daily_targets,
    resolve_baseload_kwh,
    resolve_horizon_consumer_targets_kwh,
)
from file_metadata import (
    CONSUMER_STATE_SCHEMA,
    read_schema_version,
    stamp_payload,
    strip_metadata,
)

CONSUMER_STATE_FILE = "flexible_consumers_state.json"

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
    "calculate_optimization_savings",
    "get_consumer_remaining_kwh",
    "get_spa_remaining_kwh",
    "milp_optimizer",
    "overlay_main_run_on_rows",
    "register_consumer_hours",
    "register_spa_hour",
    "resolve_applied_daily_targets",
    "resolve_baseload_kwh",
    "resolve_charging_contexts",
    "resolve_horizon_consumer_targets_kwh",
    "simulate_24h_horizon",
    "simulate_baseline_horizon",
    "simulate_horizon",
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
    row["Netzbezug (kW)"] = round(
        float(row["Verbrauch-Prognose (kW)"])
        + _flexible_consumer_power_kw(row)
        - float(row["PV-Prognose (kW)"])
        + float(row["Geplante Batterie-Aktion (kW)"]),
        2,
    )
    updated[0] = row
    return updated


def _active_consumers(consumers: list | None = None) -> list:
    return consumers if consumers is not None else config.get_flexible_consumers(optimizer_only=True)


def _load_consumer_state() -> dict:
    today = datetime.now().date().isoformat()
    if not os.path.exists(CONSUMER_STATE_FILE):
        return {"date": today, "delivered": {}}
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
        if state.get("date") != today:
            return {"date": today, "delivered": {}}
        delivered = state.get("delivered", {})
        if not isinstance(delivered, dict):
            return {"date": today, "delivered": {}}
        return {"date": today, "delivered": delivered}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {"date": today, "delivered": {}}


def _save_consumer_state(state: dict) -> None:
    payload = stamp_payload(strip_metadata(state), schema_version=CONSUMER_STATE_SCHEMA)
    with open(CONSUMER_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def get_consumer_remaining_kwh(
    consumers: list | None = None,
    optimization_matrix: list | None = None,
    consumer_daily_targets_kwh: dict | None = None,
) -> dict[str, float]:
    """Verbleibende Zielenergie aller optimierbaren Verbraucher (inkl. Loxone E-Auto)."""
    import consumer_targets
    active = _active_consumers(consumers)
    state = _load_consumer_state()
    delivered = state.get("delivered", {})
    if optimization_matrix is not None:
        daily_targets = resolve_horizon_consumer_targets_kwh(
            optimization_matrix, consumer_daily_targets_kwh
        )
        charging_contexts = resolve_charging_contexts(
            optimization_matrix, consumer_daily_targets_kwh
        )
        daily_targets = _apply_horizon_charging_limits(daily_targets, charging_contexts)
    else:
        daily_targets = consumer_targets.resolve_consumer_daily_targets()
    remaining = {}
    for consumer in active:
        cid = consumer["id"]
        daily_target = float(daily_targets.get(cid, consumer["daily_target_kwh"]))
        already = float(delivered.get(cid, 0.0))
        remaining[cid] = max(0.0, daily_target - already)
    return remaining


def _optimization_interval_hours() -> float:
    """Dauer eines Live-Optimierungszyklus in Stunden (Viertelstunde)."""
    return schedule.optimization_interval_hours()


def register_consumer_hours(consumer_powers: dict[str, float]) -> None:
    """Bucht die gelieferte Energie aller Verbraucher im aktuellen Optimierungsintervall."""
    if not consumer_powers:
        return
    interval_h = _optimization_interval_hours()
    state = _load_consumer_state()
    delivered = dict(state.get("delivered", {}))
    for cid, power_kw in consumer_powers.items():
        if power_kw > 0:
            delivered[cid] = round(float(delivered.get(cid, 0.0)) + power_kw * interval_h, 3)
    state["delivered"] = delivered
    _save_consumer_state(state)


def get_spa_remaining_kwh() -> float:
    """Legacy: verbleibendes SwimSpa-Tagesziel."""
    return get_consumer_remaining_kwh().get("swimspa", 0.0)


def register_spa_hour(spa_power_kw: float) -> None:
    """Legacy: SwimSpa-Stunde buchen."""
    if spa_power_kw > 0:
        register_consumer_hours({"swimspa": spa_power_kw})

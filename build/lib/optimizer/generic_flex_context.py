"""MILP-Zeitfenster für Planungs-generic-Verbraucher (Start ± Verschiebung)."""
from __future__ import annotations

from house_config.generic_schedule import generic_allowed_slot_hours
from optimizer.charging_context import matrix_slot_datetime


def generic_flex_window(consumer: dict) -> dict | None:
    window = consumer.get("generic_flex_window")
    return window if isinstance(window, dict) else None


def consumer_generic_eligible_indices(
    matrix: list,
    consumer: dict,
    schedule_indices: list[int],
) -> list[int]:
    """Erlaubte MILP-Slots: Stunde im Tages-Fenster für Lauf-Dauer."""
    window = generic_flex_window(consumer)
    if not window:
        return list(schedule_indices)
    allowed_hours = generic_allowed_slot_hours(
        int(window["start_hour"]) % 24,
        float(window.get("start_shift_h", 0.0) or 0.0),
        float(window.get("duration_h", 0.0) or 0.0),
    )
    eligible: list[int] = []
    for index in schedule_indices:
        if index < 0 or index >= len(matrix):
            continue
        slot_dt = matrix_slot_datetime(matrix, index)
        if slot_dt.hour in allowed_hours:
            eligible.append(index)
    return eligible


def apply_generic_flex_constraints(
    prob,
    consumer_on: dict[str, list],
    matrix: list,
    consumer: dict,
    schedule_indices: list[int],
    consumer_power_vars: dict[str, list] | None = None,
    consumer_pv_follow_vars: dict[str, list] | None = None,
) -> list[int]:
    """Sperrt Slots außerhalb des generic-Startfensters."""
    cid = consumer["id"]
    eligible = consumer_generic_eligible_indices(matrix, consumer, schedule_indices)
    blocked = set(schedule_indices) - set(eligible)
    for index in blocked:
        prob += consumer_on[cid][index] == 0
        if consumer_power_vars and cid in consumer_power_vars:
            prob += consumer_power_vars[cid][index] == 0
        if consumer_pv_follow_vars and cid in consumer_pv_follow_vars:
            prob += consumer_pv_follow_vars[cid][index] == 0
    return eligible

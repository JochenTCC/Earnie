"""E-Auto-MILP-Moduswahl: Modus A (power_setpoint) vs. Modus B (binär, Backtesting)."""
from __future__ import annotations

from typing import Any

from optimizer.charging_context import (
    consumer_charging_eligible_indices,
    schedule_indices_for_consumer,
)
from optimizer.consumer_power import power_limits_kw, uses_power_setpoint


def is_logged_day_matrix(matrix: list | None) -> bool:
    if not matrix:
        return False
    return matrix[0].get("consumption_mode") == "logged_day"


def milp_uses_power_setpoint(consumer: dict, matrix: list | None) -> bool:
    """True, wenn der MILP kontinuierliche kW-Variablen (power_setpoint) nutzt."""
    if not uses_power_setpoint(consumer):
        return False
    if is_logged_day_matrix(matrix):
        return False
    return True


def milp_binary_charge_kw(consumer: dict, matrix: list | None) -> float:
    """
    Feste kW pro Einschalt-Stunde im binären MILP-Modus.

    E-Auto Modus B (Backtesting): P_nom (max_kw).
    Übrige binäre Verbraucher: nominal_power_kw.
    """
    if consumer.get("id") == "eauto" and is_logged_day_matrix(matrix):
        _, max_kw = power_limits_kw(consumer)
        return max_kw
    return float(consumer["nominal_power_kw"])


def eauto_backtesting_uses_milp(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
) -> bool:
    """True, wenn E-Auto im Backtesting über MILP (remaining > P_nom) geplant wird."""
    if consumer.get("id") != "eauto" or not is_logged_day_matrix(matrix):
        return True
    if remaining_kwh <= 1e-9:
        return False
    _, max_kw = power_limits_kw(consumer)
    return remaining_kwh > max_kw + 1e-9


def eauto_preset_charge_kw(consumer: dict, remaining_kwh: float) -> float:
    """kW für eine Preset-Stunde: clamp(remaining, P_min, P_nom)."""
    min_kw, max_kw = power_limits_kw(consumer)
    return max(min_kw, min(remaining_kwh, max_kw))


def _eauto_cheapest_eligible_index(
    matrix: list[dict[str, Any]],
    consumer: dict,
    schedule_indices: list[int],
    charging_context: dict | None,
) -> int | None:
    horizon = len(matrix)
    consumer_indices = schedule_indices_for_consumer(
        matrix, horizon, schedule_indices, consumer, charging_context
    )
    eligible = consumer_charging_eligible_indices(
        matrix, consumer, consumer_indices, charging_context
    )
    if not eligible:
        return None
    return min(eligible, key=lambda t: float(matrix[t]["k_act"]))


def eauto_preset_power_now(
    matrix: list[dict[str, Any]],
    consumer: dict,
    remaining_kwh: float,
    schedule_indices: list[int],
    charging_context: dict | None,
) -> float | None:
    """
    Preset-Leistung in der aktuellen Stunde (t=0).

    None: E-Auto bleibt im MILP (Live oder remaining > P_nom).
    0.0: Preset-Modus, aber noch nicht die günstigste Stunde.
    >0: Preset-Laden jetzt mit clamp(remaining, P_min, P_nom).
    """
    if consumer.get("id") != "eauto" or not is_logged_day_matrix(matrix):
        return None
    if remaining_kwh <= 1e-9:
        return 0.0
    if eauto_backtesting_uses_milp(consumer, matrix, remaining_kwh):
        return None
    slot = _eauto_cheapest_eligible_index(
        matrix, consumer, schedule_indices, charging_context
    )
    if slot is None or slot != 0:
        return 0.0
    return eauto_preset_charge_kw(consumer, remaining_kwh)


def split_backtesting_eauto_preset(
    planned_consumers: list,
    matrix: list[dict[str, Any]],
    remaining: dict[str, float],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
) -> tuple[dict[str, float], list]:
    """Trennt Preset-E-Auto (außerhalb MILP) von MILP-Verbrauchern."""
    preset_now: dict[str, float] = {}
    milp_consumers: list = []
    for consumer in planned_consumers:
        cid = consumer["id"]
        preset = eauto_preset_power_now(
            matrix,
            consumer,
            remaining.get(cid, 0.0),
            schedule_indices,
            charging_contexts.get(cid),
        )
        if preset is None:
            milp_consumers.append(consumer)
            continue
        if preset > 1e-9:
            preset_now[cid] = preset
    return preset_now, milp_consumers

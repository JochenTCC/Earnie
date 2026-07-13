"""E-Auto-MILP-Moduswahl: Modus A (power_setpoint) vs. Modus B (binär/Preset)."""
from __future__ import annotations

from typing import Any

from optimizer.charging_context import (
    consumer_charging_eligible_indices,
    schedule_indices_for_consumer,
)
from optimizer.consumer_power import power_limits_kw, uses_power_setpoint

EAUTO_MILP_PARAM_KEYS = (
    "live_modus_a_min_remaining_kwh",
    "tie_break_on_epsilon",
    "tie_break_time_epsilon",
)


def is_logged_day_matrix(matrix: list | None) -> bool:
    if not matrix:
        return False
    mode = matrix[0].get("consumption_mode")
    return mode in ("logged_day", "profile_spec")


def validate_eauto_milp_params(raw: dict) -> dict[str, float]:
    """Validiert eauto_milp aus config.json; wirft bei fehlenden/ungültigen Werten."""
    if not isinstance(raw, dict):
        raise ValueError(
            "Kritischer Konfigurationsfehler: Block 'eauto_milp' fehlt oder ist ungültig."
        )
    missing = [key for key in EAUTO_MILP_PARAM_KEYS if key not in raw]
    if missing:
        raise ValueError(
            "Kritischer Konfigurationsfehler: eauto_milp."
            + ", eauto_milp.".join(missing)
            + " fehlt in config.json."
        )
    min_remaining = float(raw["live_modus_a_min_remaining_kwh"])
    eps_on = float(raw["tie_break_on_epsilon"])
    eps_time = float(raw["tie_break_time_epsilon"])
    if min_remaining <= 0.0:
        raise ValueError(
            "Kritischer Konfigurationsfehler: eauto_milp.live_modus_a_min_remaining_kwh "
            "muss > 0 sein."
        )
    if eps_on < 0.0 or eps_time < 0.0:
        raise ValueError(
            "Kritischer Konfigurationsfehler: eauto_milp.tie_break_*_epsilon "
            "dürfen nicht negativ sein."
        )
    return {
        "live_modus_a_min_remaining_kwh": min_remaining,
        "tie_break_on_epsilon": eps_on,
        "tie_break_time_epsilon": eps_time,
    }


def eauto_modus_a_active(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float],
) -> bool:
    """Live Modus A: kontinuierlicher power_setpoint wenn remaining über Schwelle."""
    if consumer.get("id") != "eauto" or is_logged_day_matrix(matrix):
        return False
    return remaining_kwh > params["live_modus_a_min_remaining_kwh"] + 1e-9


def eauto_in_modus_b(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float] | None,
) -> bool:
    """Backtesting immer Modus B; Live wenn remaining ≤ Schwelle."""
    if consumer.get("id") != "eauto":
        return False
    if is_logged_day_matrix(matrix):
        return True
    if params is None:
        raise ValueError(
            "eauto_milp-Konfiguration fehlt für Live E-Auto-Optimierung "
            "(live_modus_a_min_remaining_kwh, tie_break_*_epsilon)."
        )
    if remaining_kwh <= 1e-9:
        return False
    return not eauto_modus_a_active(consumer, matrix, remaining_kwh, params)


def milp_uses_power_setpoint(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float] | None,
) -> bool:
    """True, wenn der MILP kontinuierliche kW-Variablen (power_setpoint) nutzt."""
    if not uses_power_setpoint(consumer):
        return False
    if consumer.get("id") != "eauto":
        return True
    if is_logged_day_matrix(matrix):
        return False
    if params is None:
        raise ValueError(
            "eauto_milp-Konfiguration fehlt für Live E-Auto-Optimierung."
        )
    return eauto_modus_a_active(consumer, matrix, remaining_kwh, params)


def milp_binary_charge_kw(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float] | None,
) -> float:
    """Feste kW pro Einschalt-Stunde im binären MILP-Modus."""
    if consumer.get("id") == "eauto" and not milp_uses_power_setpoint(
        consumer, matrix, remaining_kwh, params
    ):
        _, max_kw = power_limits_kw(consumer)
        return max_kw
    return float(consumer["nominal_power_kw"])


def eauto_modus_b_uses_milp(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float] | None,
) -> bool:
    """True, wenn E-Auto in Modus B über MILP (remaining > P_nom) geplant wird."""
    if not eauto_in_modus_b(consumer, matrix, remaining_kwh, params):
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
    params: dict[str, float] | None,
) -> float | None:
    """
    Preset-Leistung in der aktuellen Stunde (t=0).

    None: E-Auto bleibt im MILP (Modus A oder Modus B mit remaining > P_nom).
    0.0: Preset-Modus, aber noch nicht die günstigste Stunde.
    >0: Preset-Laden jetzt mit clamp(remaining, P_min, P_nom).
    """
    if not eauto_in_modus_b(consumer, matrix, remaining_kwh, params):
        return None
    if eauto_modus_b_uses_milp(consumer, matrix, remaining_kwh, params):
        return None
    slot = _eauto_cheapest_eligible_index(
        matrix, consumer, schedule_indices, charging_context
    )
    if slot is None or slot != 0:
        return 0.0
    return eauto_preset_charge_kw(consumer, remaining_kwh)


def split_eauto_preset(
    planned_consumers: list,
    matrix: list[dict[str, Any]],
    remaining: dict[str, float],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
    params: dict[str, float] | None,
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
            params,
        )
        if preset is None:
            milp_consumers.append(consumer)
            continue
        if preset > 1e-9:
            preset_now[cid] = preset
    return preset_now, milp_consumers

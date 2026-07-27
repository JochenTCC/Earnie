"""E-Auto-MILP-Moduswahl: Modus A (power_setpoint) vs. Modus B (binär/Preset)."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from optimizer.charging_context import (
    consumer_charging_eligible_indices,
    hours_needed_to_deliver,
    latest_start_datetime,
    matrix_slot_datetime,
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
    """Validiert MILP-Parameter (root eauto_milp oder charging_schedule.milp)."""
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


def is_ev_milp_consumer(consumer: dict) -> bool:
    """EV mit power_setpoint und aktivem charging_schedule."""
    if not uses_power_setpoint(consumer):
        return False
    sched = consumer.get("charging_schedule")
    return bool(sched and sched.get("enabled"))


def milp_params_from_consumer(consumer: dict) -> dict[str, float] | None:
    """MILP-Parameter aus charging_schedule.milp (Pflicht für EV power_setpoint)."""
    if not is_ev_milp_consumer(consumer):
        return None
    sched = consumer.get("charging_schedule") or {}
    milp_raw = sched.get("milp")
    if isinstance(milp_raw, dict) and milp_raw:
        return validate_eauto_milp_params(milp_raw)
    return None


def build_ev_milp_params_by_id(consumers: list) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for consumer in consumers:
        params = milp_params_from_consumer(consumer)
        if params is not None:
            result[str(consumer["id"])] = params
    return result


def ev_modus_a_active(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float],
) -> bool:
    """Live Modus A: kontinuierlicher power_setpoint wenn remaining über Schwelle."""
    if not is_ev_milp_consumer(consumer) or is_logged_day_matrix(matrix):
        return False
    return remaining_kwh > params["live_modus_a_min_remaining_kwh"] + 1e-9


def ev_in_modus_b(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float] | None,
) -> bool:
    """Backtesting immer Modus B; Live wenn remaining ≤ Schwelle."""
    if not is_ev_milp_consumer(consumer):
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
    return not ev_modus_a_active(consumer, matrix, remaining_kwh, params)


# Backward-compatible aliases
eauto_modus_a_active = ev_modus_a_active
eauto_in_modus_b = ev_in_modus_b


def milp_uses_power_setpoint(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float] | None,
) -> bool:
    """True, wenn der MILP kontinuierliche kW-Variablen (power_setpoint) nutzt."""
    if not uses_power_setpoint(consumer):
        return False
    if not is_ev_milp_consumer(consumer):
        return True
    if is_logged_day_matrix(matrix):
        return False
    if params is None:
        raise ValueError(
            "eauto_milp-Konfiguration fehlt für Live E-Auto-Optimierung."
        )
    return ev_modus_a_active(consumer, matrix, remaining_kwh, params)


def milp_binary_charge_kw(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float] | None,
) -> float:
    """Feste kW pro Einschalt-Stunde im binären MILP-Modus."""
    if is_ev_milp_consumer(consumer) and not milp_uses_power_setpoint(
        consumer, matrix, remaining_kwh, params
    ):
        _, max_kw = power_limits_kw(consumer)
        return max_kw
    return float(consumer["nominal_power_kw"])


def ev_modus_b_uses_milp(
    consumer: dict,
    matrix: list | None,
    remaining_kwh: float,
    params: dict[str, float] | None,
) -> bool:
    """True, wenn EV in Modus B über MILP (remaining > P_nom) geplant wird."""
    if not ev_in_modus_b(consumer, matrix, remaining_kwh, params):
        return False
    _, max_kw = power_limits_kw(consumer)
    return remaining_kwh > max_kw + 1e-9


eauto_modus_b_uses_milp = ev_modus_b_uses_milp


def ev_preset_charge_kw(consumer: dict, remaining_kwh: float) -> float:
    """kW für eine Preset-Stunde: clamp(remaining, P_min, P_nom)."""
    min_kw, max_kw = power_limits_kw(consumer)
    return max(min_kw, min(remaining_kwh, max_kw))


eauto_preset_charge_kw = ev_preset_charge_kw


def _ev_cheapest_eligible_index(
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


def _parse_charging_deadline(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def _preset_must_charge_now(
    matrix: list[dict[str, Any]],
    consumer: dict,
    remaining_kwh: float,
    schedule_indices: list[int],
    charging_context: dict | None,
) -> bool:
    """Preset-Fallback: Deadline-Druck statt nur günstigste Stunde (t=0)."""
    if remaining_kwh <= 1e-9:
        return False
    ctx = charging_context or {}
    deadline = _parse_charging_deadline(ctx.get("deadline"))
    if deadline is None:
        return False
    _, max_kw = power_limits_kw(consumer)
    if max_kw <= 1e-9:
        return False
    now = matrix_slot_datetime(matrix, 0)
    must_start = latest_start_datetime(deadline, remaining_kwh, max_kw)
    if now >= must_start:
        return True
    horizon = len(matrix)
    consumer_indices = schedule_indices_for_consumer(
        matrix, horizon, schedule_indices, consumer, ctx
    )
    eligible = consumer_charging_eligible_indices(
        matrix, consumer, consumer_indices, ctx
    )
    future = [t for t in eligible if t >= 0]
    if not future:
        return False
    slots_needed = math.ceil(hours_needed_to_deliver(remaining_kwh, max_kw))
    return len(future) <= slots_needed


def ev_preset_power_now(
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
    if not ev_in_modus_b(consumer, matrix, remaining_kwh, params):
        return None
    if ev_modus_b_uses_milp(consumer, matrix, remaining_kwh, params):
        return None
    slot = _ev_cheapest_eligible_index(
        matrix, consumer, schedule_indices, charging_context
    )
    if slot == 0:
        return ev_preset_charge_kw(consumer, remaining_kwh)
    if _preset_must_charge_now(
        matrix, consumer, remaining_kwh, schedule_indices, charging_context
    ):
        return ev_preset_charge_kw(consumer, remaining_kwh)
    return 0.0


eauto_preset_power_now = ev_preset_power_now


def ev_preset_horizon_placement(
    matrix: list[dict[str, Any]],
    consumer: dict,
    remaining_kwh: float,
    schedule_indices: list[int],
    charging_context: dict | None,
    params: dict[str, float] | None,
) -> tuple[int, float] | None:
    """
    Open-loop SE/logged_day: place Modus-B preset at cheapest eligible hour.

    None → keep consumer in MILP. (slot, kw) → fixed flex outside MILP at slot.
    Unlike Live ``ev_preset_power_now``, never returns a wait-at-t0 (0.0) drop.
    """
    if not ev_in_modus_b(consumer, matrix, remaining_kwh, params):
        return None
    if ev_modus_b_uses_milp(consumer, matrix, remaining_kwh, params):
        return None
    slot = _ev_cheapest_eligible_index(
        matrix, consumer, schedule_indices, charging_context
    )
    if slot is None:
        return None
    power = ev_preset_charge_kw(consumer, remaining_kwh)
    if power <= 1e-9:
        return None
    return slot, power


eauto_preset_horizon_placement = ev_preset_horizon_placement


def _record_preset_slot(
    preset_by_slot: dict[int, dict[str, float]],
    slot: int,
    consumer_id: str,
    power: float,
) -> None:
    bucket = preset_by_slot.setdefault(slot, {})
    bucket[consumer_id] = float(power)


def split_eauto_preset(
    planned_consumers: list,
    matrix: list[dict[str, Any]],
    remaining: dict[str, float],
    schedule_indices: list[int],
    charging_contexts: dict[str, dict],
) -> tuple[dict[int, dict[str, float]], list]:
    """
    Trenne Preset-EV (außerhalb MILP) von MILP-Verbrauchern.

    Returns
    -------
    preset_by_slot:
        hour-index → {consumer_id: kW}. Live/rolling only fills slot 0 when
        charging now; logged_day/profile_spec open-loop places at the cheapest
        eligible hour so SE sunrise commit_hours=H still delivers small EV targets.
    milp_consumers:
        consumers that stay inside the MILP.
    """
    preset_by_slot: dict[int, dict[str, float]] = {}
    milp_consumers: list = []
    logged = is_logged_day_matrix(matrix)
    for consumer in planned_consumers:
        cid = consumer["id"]
        params = milp_params_from_consumer(consumer)
        rem = remaining.get(cid, 0.0)
        ctx = charging_contexts.get(cid)
        if logged and is_ev_milp_consumer(consumer):
            placement = ev_preset_horizon_placement(
                matrix, consumer, rem, schedule_indices, ctx, params
            )
            if placement is None:
                if ev_in_modus_b(consumer, matrix, rem, params) and not ev_modus_b_uses_milp(
                    consumer, matrix, rem, params
                ):
                    continue
                milp_consumers.append(consumer)
                continue
            slot, power = placement
            _record_preset_slot(preset_by_slot, slot, cid, power)
            continue
        preset = ev_preset_power_now(
            matrix,
            consumer,
            rem,
            schedule_indices,
            ctx,
            params,
        )
        if preset is None:
            milp_consumers.append(consumer)
            continue
        if preset > 1e-9:
            _record_preset_slot(preset_by_slot, 0, cid, preset)
    return preset_by_slot, milp_consumers

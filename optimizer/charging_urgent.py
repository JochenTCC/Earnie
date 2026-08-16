"""Urgent-/ASAP-Ladehilfen für MILP und Ladekontext."""
from __future__ import annotations

from datetime import datetime, timedelta

from optimizer.charging_schedule import matrix_slot_datetime
from settings.flexible_consumers import target_kwh_from_rest_soc

URGENT_PLAN_KWH_EPSILON = 0.05

def hours_needed_to_deliver(remaining_kwh: float, max_kw: float) -> float:
    """Benötigte Volllast-Stunden für verbleibende Energie (5 % Puffer)."""
    if max_kw <= 1e-9 or remaining_kwh <= 1e-9:
        return 0.0
    return (remaining_kwh / max_kw) * 1.05


def urgent_min_kwh_from_soc(
    consumer: dict,
    *,
    actual_soc: float | None,
    soc_min_immediate: float | None,
    capacity_kwh: float | None,
) -> float:
    """Grid kWh needed ASAP to reach SOC-Min-Immediate; 0 if inactive or already above."""
    if soc_min_immediate is None or actual_soc is None or capacity_kwh is None:
        return 0.0
    if float(actual_soc) >= float(soc_min_immediate) - 1e-9:
        return 0.0
    energy = target_kwh_from_rest_soc(
        consumer,
        float(actual_soc),
        capacity_kwh=float(capacity_kwh),
        limit_soc_percent=float(soc_min_immediate),
    )
    return max(0.0, float(energy or 0.0))


def asap_indices_for_urgent_min(
    matrix: list,
    *,
    horizon: int,
    urgent_min_kwh: float,
    max_kw: float,
    deadline: datetime | None = None,
) -> list[int]:
    """
    Horizon slots from now until energy can be delivered at max_kw (ASAP window).

    Ignores weekday charging windows; still skips slots at/after FertigUm deadline.
    """
    if urgent_min_kwh <= 1e-9 or max_kw <= 1e-9 or horizon <= 0 or not matrix:
        return []
    now = matrix_slot_datetime(matrix, 0)
    asap_end = now + timedelta(hours=hours_needed_to_deliver(urgent_min_kwh, max_kw))
    indices: list[int] = []
    for t in range(min(int(horizon), len(matrix))):
        slot_dt = matrix_slot_datetime(matrix, t)
        if deadline is not None and slot_dt >= deadline:
            continue
        if slot_dt < asap_end:
            indices.append(t)
    if indices:
        return indices
    slot0 = matrix_slot_datetime(matrix, 0)
    if deadline is None or slot0 < deadline:
        return [0]
    return []


def latest_start_datetime(
    deadline: datetime,
    remaining_kwh: float,
    max_kw: float,
) -> datetime:
    """Spätester Beginn, damit remaining_kwh vor deadline bei max_kw geliefert werden kann."""
    hours = hours_needed_to_deliver(remaining_kwh, max_kw)
    if hours <= 0:
        return deadline
    return deadline - timedelta(hours=hours)


def split_eligible_by_urgent_deadline(
    matrix: list,
    eligible_indices: list[int],
    deadline: datetime,
    remaining_kwh: float,
    max_kw: float,
) -> tuple[list[int], list[int]]:
    """
    Teilt zulässige Slots in optional (vor spätestem Ladebeginn) und urgent (bis Deadline).

    Optional: Laden erlaubt, aber nicht erzwungen (z. B. günstige Preise).
    Urgent: Muss die noch offene Restenergie liefern, falls vorher nicht genug geladen wurde.

    Fallback: Liegt kein Slot im urgent-Bereich, gelten alle eligible als urgent.
    """
    if not eligible_indices or remaining_kwh <= 1e-9:
        return [], []
    must_start = latest_start_datetime(deadline, remaining_kwh, max_kw)
    pre_urgent: list[int] = []
    urgent: list[int] = []
    for t in eligible_indices:
        slot_dt = matrix_slot_datetime(matrix, t)
        if slot_dt >= deadline:
            continue
        if slot_dt < must_start:
            pre_urgent.append(t)
        else:
            urgent.append(t)
    if not urgent:
        return [], list(eligible_indices)
    return pre_urgent, urgent


def urgent_charging_indices(
    matrix: list,
    eligible_indices: list[int],
    deadline: datetime,
    remaining_kwh: float,
    max_kw: float,
) -> list[int]:
    """Horizont-Slots ab spätestem Ladebeginn bis Deadline (Nachhol-Fenster)."""
    _, urgent = split_eligible_by_urgent_deadline(
        matrix, eligible_indices, deadline, remaining_kwh, max_kw
    )
    return urgent


def summarize_urgent_rule_usage(
    *,
    pre_urgent_indices: list[int],
    urgent_indices: list[int],
    effective_target_kwh: float,
    planned_pre_urgent_kwh: float,
    planned_urgent_kwh: float,
    deadline: datetime | None,
    must_start: datetime | None,
) -> dict:
    """
    Klassifiziert die Wirkung der urgent-Nebenbedingung im MILP-Plan.

    role:
      - nicht_aktiv: keine Deadline / kein Ladeziel / keine urgent-Slots
      - nur_urgent_fenster: kein optionaler Vorlauf (Horizont beginnt im urgent-Fenster)
      - nachholen: Energie wird im urgent-Fenster nachgeholt
      - redundant: Ziel wird ohne urgent-Fenster erreicht (Nebenbedingung wirkungslos)
    """
    if effective_target_kwh <= URGENT_PLAN_KWH_EPSILON or not urgent_indices:
        return {"role": "nicht_aktiv"}

    summary: dict = {
        "role": "redundant",
        "target_kwh": round(float(effective_target_kwh), 3),
        "planned_pre_urgent_kwh": round(float(planned_pre_urgent_kwh), 3),
        "planned_urgent_kwh": round(float(planned_urgent_kwh), 3),
    }
    if deadline is not None:
        summary["deadline"] = deadline.isoformat(timespec="seconds")
    if must_start is not None:
        summary["must_start"] = must_start.isoformat(timespec="seconds")

    if not pre_urgent_indices:
        summary["role"] = "nur_urgent_fenster"
    elif planned_urgent_kwh > URGENT_PLAN_KWH_EPSILON:
        summary["role"] = "nachholen"
    else:
        summary["role"] = "redundant"
    return summary

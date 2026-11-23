"""Live store plan → MILP store level and slot mapping (split from thermal_live_store)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from optimizer.thermal_live_cop import segment_cops, segment_edges_c
from optimizer.thermal_store_model import StoreLevelModel, StoreSegment

if TYPE_CHECKING:
    from optimizer.thermal_live_store import LiveStorePlan

TERMINAL_WINDOW_H = 24.0
"""The terminal level is the mean level of normal operation over the last day of the book, so it
does not depend on where in a charge cycle the simulation happens to end (design § 8.6 D2)."""

COLLECTOR_LOOKAHEAD_H = 24.0
"""The generator leaves the room above the setpoint free for the collector surplus forecast for
this time ahead (design § 4: no boost ahead of forecast collector heat)."""


def hourly_electric_to_slot_energy_kwh(
    matrix: list, electric_by_hour: list[float]
) -> list[float]:
    """WP electric kWh per matrix slot from hourly electric (wall-clock hour from horizon start)."""
    from optimizer.charging_context import matrix_slot_datetime
    from optimizer.slot_duration import energy_kwh_from_kw

    if not matrix:
        return []
    start = matrix_slot_datetime(matrix, 0)
    energies: list[float] = []
    for index in range(len(matrix)):
        hour_offset = int((matrix_slot_datetime(matrix, index) - start).total_seconds() // 3600)
        if 0 <= hour_offset < len(electric_by_hour):
            # electric_by_hour is kWh per hour == mean kW over that hour.
            energies.append(float(energy_kwh_from_kw([electric_by_hour[hour_offset]])))
        else:
            energies.append(0.0)
    return energies


def _slot_hours(matrix: list, n_hours: int) -> list[int]:
    """Wall-clock hour of the plan for every matrix slot (offset from the start's full hour).

    Plan hour 0 is the full hour of the first slot, as for the baseload and gains
    (``matrix_hourly_kw``). The plan has ``floor(slots × Δt)`` hours
    (``thermal_horizon_hours_from_slots``), and the recorded forecasts of the regression cases have
    exactly as many. A matrix that starts inside an hour (Live at :15/:30/:45) and ends with a
    partial hour spans up to two wall-clock hours more; those slots use the last hour of the
    plan. This is the only hold, a slot further out fails loud.
    """
    from optimizer.charging_context import matrix_slot_datetime

    if n_hours < 1:
        raise ValueError("Speicherplan ohne Stunden.")
    start = matrix_slot_datetime(matrix, 0)
    hours: list[int] = []
    for index in range(len(matrix)):
        hour = int((matrix_slot_datetime(matrix, index) - start).total_seconds() // 3600)
        if n_hours <= hour <= n_hours + 1:
            hour = n_hours - 1  # partial first and last hour of the matrix
        if not 0 <= hour < n_hours:
            raise ValueError(
                f"Speicherplan reicht nur {n_hours} h, Matrix-Slot {index} liegt in Stunde {hour}."
            )
        hours.append(hour)
    return hours


def live_store_level_model(matrix: list, plan: LiveStorePlan, dt_h: float) -> StoreLevelModel:
    """Store level of the Live MILP (HeatControl P4): kWh above the band minimum.

    Capacity up to ``charge_max_c``; start from the measured ``T_eq``; drain = net draw plus the
    loss at the band minimum; collector surplus may be spilled; leak ``Δt · H / C``.
    """
    if plan.capacity_kwh_per_k <= 0 or plan.jaz <= 0:
        raise ValueError("Speicherplan ohne Kapazität oder Wirkungsgrad: kein Speicherstand möglich.")
    if dt_h <= 0:
        raise ValueError("dt_h must be > 0")
    c = float(plan.capacity_kwh_per_k)
    t_min = float(plan.band.min_c)
    draw = plan.hourly_draw_at_min_kw()
    hours = _slot_hours(matrix, len(draw))
    capacity = c * (plan.charge_max_c - t_min)
    drain = [draw[hour] * dt_h for hour in hours]
    return StoreLevelModel(
        capacity_kwh=capacity,
        start_kwh=c * (float(plan.start_temp_c) - t_min),
        efficiency=float(plan.jaz),
        drain_kwh=drain,
        leak_per_slot=dt_h * float(plan.heat_loss_kw_per_k) / c,
        leak_ref_kwh=0.0,
        spill_max_kwh=[max(0.0, -float(plan.draw_kw_by_hour[hour])) * dt_h for hour in hours],
        segments=_live_store_segments(plan, hours, capacity),
        charge_limit_kwh=_collector_charge_limits(plan, drain, dt_h, capacity),
    )


def _live_store_segments(
    plan: LiveStorePlan, hours: list[int], capacity_kwh: float
) -> tuple[StoreSegment, ...]:
    """Sink segments of the band with their COP per slot (HeatControl P5); none with the JAZ."""
    if not plan.efficiency.by_temperature or capacity_kwh <= 0:
        return ()
    c = float(plan.capacity_kwh_per_k)
    edges = segment_edges_c(float(plan.band.min_c), float(plan.band.setpoint_c), plan.charge_max_c)
    held = plan.efficiency.source_temp_c
    source = [float(plan.ambient_c[hour]) if held is None else float(held) for hour in hours]
    cops = segment_cops(plan.efficiency, edges, source)
    return tuple(
        StoreSegment(capacity_kwh=c * (edges[index + 1] - edges[index]), cop=cops[index])
        for index in range(len(edges) - 1)
    )


def _collector_charge_limits(
    plan: LiveStorePlan, drain_kwh: list[float], dt_h: float, capacity_kwh: float
) -> list[float]:
    """Level per slot up to which the generator may charge: the capacity minus the room the
    collector surplus of the following ``COLLECTOR_LOOKAHEAD_H`` needs, never below the setpoint.

    The surplus is the collector heat the draw does not use up. From a slot on, the net heat
    into the store (``−drain``) adds up slot by slot; the largest sum is the room that must be
    free at the end of the slot so that the store takes it all. Collector heat that the house
    draws before or while it arrives needs no room: a charge that is used up before the
    collector heat comes stays allowed.

    Empty without a band above the setpoint, without forecast collector heat, or when no slot
    gets a limit below the capacity.
    """
    normal = float(plan.capacity_kwh_per_k) * (float(plan.band.setpoint_c) - float(plan.band.min_c))
    collector = plan.collector_kw_by_hour
    if capacity_kwh <= normal + 1e-9 or not any(kw > 1e-9 for kw in collector):
        return []
    if len(collector) < len(plan.draw_kw_by_hour):
        raise ValueError("Speicherplan: Kollektorprognose kürzer als die Wärmeentnahme.")
    window = int(round(COLLECTOR_LOOKAHEAD_H / dt_h))
    limits: list[float] = []
    for slot in range(len(drain_kwh)):
        surplus = room = 0.0
        for drain in drain_kwh[slot + 1 : slot + 1 + window]:
            surplus -= drain
            room = max(room, surplus)
        limits.append(max(normal, capacity_kwh - room))
    if not any(limit < capacity_kwh - 1e-9 for limit in limits):
        return []
    return limits


def live_store_terminal_kwh(matrix: list, plan: LiveStorePlan, last_slot: int, dt_h: float) -> float:
    """Mean level of normal operation over the last ``TERMINAL_WINDOW_H`` up to ``last_slot``."""
    if not plan.store_temp_c:
        raise ValueError("Speicherplan ohne Temperaturverlauf: kein Endstand möglich.")
    c = float(plan.capacity_kwh_per_k)
    t_min = float(plan.band.min_c)
    cap = c * (plan.charge_max_c - t_min)
    hours = _slot_hours(matrix, len(plan.store_temp_c))
    first = max(0, last_slot + 1 - int(round(TERMINAL_WINDOW_H / dt_h)))
    levels = [
        min(cap, max(0.0, c * (float(plan.store_temp_c[hours[slot]]) - t_min)))
        for slot in range(first, last_slot + 1)
    ]
    return sum(levels) / len(levels)


def map_forced_hours_to_slot_indices(
    matrix: list,
    forced_hour_flags: list[bool],
    *,
    eligible_indices: list[int] | None = None,
) -> list[int]:
    """Map hour flags onto matrix QH indices (wall-clock hour match from horizon start)."""
    from optimizer.charging_context import matrix_slot_datetime

    if not matrix or not forced_hour_flags:
        return []
    eligible = set(eligible_indices) if eligible_indices is not None else None
    start = matrix_slot_datetime(matrix, 0)
    forced_slots: list[int] = []
    for index, _row in enumerate(matrix):
        if eligible is not None and index not in eligible:
            continue
        slot_dt = matrix_slot_datetime(matrix, index)
        hour_offset = int((slot_dt - start).total_seconds() // 3600)
        if hour_offset < 0 or hour_offset >= len(forced_hour_flags):
            continue
        if forced_hour_flags[hour_offset]:
            forced_slots.append(index)
    return forced_slots

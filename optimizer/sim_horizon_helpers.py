"""Slot-Mathematik und Flex-/SoC-Nachbearbeitung für die Horizont-Simulation."""
from __future__ import annotations

from optimizer import battery as bat
from optimizer.sim_chart_rows import sync_chart_row_netzbezug
from optimizer.slot_duration import DEFAULT_DT_H, slots_for_wall_hours, validate_dt_h
from optimizer.targets import consumer_column_name


def _relative_sunrise_index(
    sunrise_soc_min_index: int | None,
    slice_start: int,
    slice_len: int,
) -> int | None:
    if sunrise_soc_min_index is None:
        return None
    if sunrise_soc_min_index < slice_start:
        return None
    rel = sunrise_soc_min_index - slice_start
    if rel < 0 or rel >= slice_len:
        return None
    return rel


def _commit_slots_for_buffer(
    commit_hours: int,
    *,
    matrix_len: int,
    remaining_len: int,
) -> int:
    """Wall-clock commit_hours → QH slot count; open-loop when >= matrix_len."""
    if commit_hours >= matrix_len:
        return remaining_len
    return min(
        remaining_len,
        max(1, slots_for_wall_hours(float(commit_hours), DEFAULT_DT_H)),
    )


def _terminal_soc_for_commit(
    commit_hours: int,
    remaining_slice_len: int,
    horizon_terminal_soc: float | None,
) -> float | None:
    """K=1: Terminal nur in der letzten Slot-Solve; K>1: Terminal solange Fensterende enthalten."""
    if horizon_terminal_soc is None:
        return None
    if commit_hours <= 1:
        return horizon_terminal_soc if remaining_slice_len == 1 else None
    return horizon_terminal_soc


def _flex_indices_for_book_hours(
    remaining_len: int,
    hour_index: int,
    flex_book_hours: int | None,
    flex_book_start: int = 0,
) -> list[int]:
    """
    Flex-eligible indices relative to remaining_slice.

    flex_book_hours=None: all remaining hours (Live / truncated SE).
    Otherwise only absolute hours [flex_book_start, flex_book_start + flex_book_hours).
    """
    if flex_book_hours is None:
        return list(range(remaining_len))
    if flex_book_hours < 1:
        raise ValueError(
            f"flex_book_hours must be >= 1 when set (got {flex_book_hours})."
        )
    if flex_book_start < 0:
        raise ValueError(
            f"flex_book_start must be >= 0 (got {flex_book_start})."
        )
    book_end = flex_book_start + flex_book_hours
    return [
        index
        for index in range(remaining_len)
        if flex_book_start <= hour_index + index < book_end
    ]


def _cap_flex_delivery(
    chart_row: dict,
    consumers_cfg: list,
    horizon_limits: dict[str, float],
    delivered_horizon: dict[str, float],
    *,
    dt_h: float = DEFAULT_DT_H,
) -> bool:
    """Begrenzt Flex-Leistung auf verbleibendes Horizontziel; True wenn gekappt."""
    dt_h = validate_dt_h(dt_h)
    flex_capped = False
    for consumer in consumers_cfg:
        col = consumer_column_name(consumer)
        cid = consumer["id"]
        power = float(chart_row.get(col, 0.0) or 0.0)
        if power <= 0:
            continue
        max_kwh = horizon_limits.get(cid, 0.0)
        already = delivered_horizon.get(cid, 0.0)
        room = max(0.0, max_kwh - already)
        energy = power * dt_h
        if energy > room + 1e-6:
            power = room / dt_h
            chart_row[col] = round(power, 2)
            flex_capped = True
            energy = power * dt_h
        if energy > 0:
            delivered_horizon[cid] = already + energy
    return flex_capped


def _apply_forced_grid_recharge_at_horizon_end(
    chart_rows: list[dict],
    end_soc: float,
    *,
    battery_params: dict,
    horizon_anchor_soc: float,
) -> float:
    """
    Netz-Zwangsladen am Horizontende, wenn SoC auf SOC_min liegt und der
    Terminal-Anker (Simulations-initial_soc) darüber liegt.
    """
    if not chart_rows or battery_params.get("battery_capacity_kwh", 0.0) <= 0.0:
        return end_soc
    min_soc = float(battery_params["min_soc"])
    max_soc = float(battery_params["max_soc"])
    if end_soc > min_soc + bat.SOC_DELTA_THRESHOLD:
        return end_soc
    target = min(max_soc, float(horizon_anchor_soc))
    if target <= min_soc + bat.SOC_DELTA_THRESHOLD:
        return end_soc
    charge_kw = bat.charge_kw_for_hourly_soc(
        end_soc,
        target,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        battery_params["max_power_kw"],
        min_soc,
        max_soc,
        dt_h=DEFAULT_DT_H,
    )
    if charge_kw <= 0.0:
        return end_soc

    last = chart_rows[-1]
    start_last = float(last["Simulierter SoC (%)"])
    batt_old = float(last.get("Geplante Batterie-Aktion (kW)", 0.0) or 0.0)
    new_end_soc, batt_new = bat.apply_soc_change(
        start_last,
        batt_old + charge_kw,
        battery_params["battery_capacity_kwh"],
        battery_params["efficiency"],
        min_soc,
        max_soc,
        dt_h=DEFAULT_DT_H,
    )
    last["Geplante Batterie-Aktion (kW)"] = round(batt_new, 2)
    # Steuerbefehl must match the applied charge power (after SoC clip / prior action).
    last["Steuerbefehl"] = bat.steuerbefehl_for_mode(
        bat.MODE_ZWANGS_LADEN, max(0.0, float(batt_new))
    )
    sync_chart_row_netzbezug(last)
    return round(new_end_soc, 1)

"""SOC reading plausibility vs battery power integration."""
from __future__ import annotations

import config
from optimizer import battery as bat
from optimizer.slot_duration import DEFAULT_DT_H

_SOC_INTEGRATION_TOLERANCE = 1.5  # percent above physics envelope


def max_soc_delta_per_slot(
    battery_params: dict | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> float:
    """Maximum plausible SoC swing in one slot at full battery power."""
    params = battery_params or config.get_battery_params()
    capacity = float(params.get("battery_capacity_kwh", 0.0))
    max_power = float(params.get("max_power_kw", 0.0))
    if capacity <= 0.0 or max_power <= 0.0:
        return 100.0
    mid = 50.0
    up, _ = bat.apply_soc_change(
        mid,
        max_power,
        capacity,
        float(params["efficiency"]),
        float(params["min_soc"]),
        float(params["max_soc"]),
        dt_h=dt_h,
    )
    down, _ = bat.apply_soc_change(
        mid,
        -max_power,
        capacity,
        float(params["efficiency"]),
        float(params["min_soc"]),
        float(params["max_soc"]),
        dt_h=dt_h,
    )
    return max(up - mid, mid - down) + _SOC_INTEGRATION_TOLERANCE


def integrate_soc_step(
    prev_soc: float,
    battery_kw: float,
    battery_params: dict | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> float:
    params = battery_params or config.get_battery_params()
    capacity = float(params.get("battery_capacity_kwh", 0.0))
    if capacity <= 0.0:
        return round(prev_soc, 1)
    new_soc, _ = bat.apply_soc_change(
        prev_soc,
        battery_kw,
        capacity,
        float(params["efficiency"]),
        float(params["min_soc"]),
        float(params["max_soc"]),
        dt_h=dt_h,
    )
    return round(new_soc, 1)


def sanitize_soc_reading(
    prev_soc: float | None,
    reported_soc: float,
    battery_kw: float,
    battery_params: dict | None = None,
    *,
    dt_h: float = DEFAULT_DT_H,
) -> tuple[float, bool]:
    """
    Return (soc, corrected?) — replace implausible jumps with battery integration.

    Uses Ist/plan battery power between slots; full-power envelope as backstop.
    """
    if prev_soc is None:
        return round(float(reported_soc), 1), False
    prev = float(prev_soc)
    reported = round(float(reported_soc), 1)
    expected = integrate_soc_step(prev, battery_kw, battery_params, dt_h=dt_h)
    max_delta = max_soc_delta_per_slot(battery_params, dt_h=dt_h)
    if abs(reported - prev) <= max_delta:
        return reported, False
    if abs(reported - expected) <= _SOC_INTEGRATION_TOLERANCE:
        return reported, False
    return expected, True

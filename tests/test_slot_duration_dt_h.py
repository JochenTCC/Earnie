"""2.5.d/e: explicit dt_h scales SoC, objective energy, and delivery kWh."""
from __future__ import annotations

from optimizer.battery import apply_soc_change, charge_kw_for_hourly_soc
from optimizer.milp_consumers import _max_deliverable_kwh
from optimizer.slot_duration import (
    DEFAULT_DT_H,
    SLOTS_PER_HOUR,
    slots_for_wall_hours,
    validate_dt_h,
    wall_hours_from_slots,
)


def test_default_dt_h_is_quarter_hour():
    assert DEFAULT_DT_H == 0.25
    assert SLOTS_PER_HOUR == 4


def test_validate_dt_h_rejects_non_positive():
    try:
        validate_dt_h(0.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_apply_soc_change_scales_with_dt_h():
    kwargs = dict(
        old_soc=50.0,
        batt_action=4.0,
        battery_capacity_kwh=10.0,
        efficiency=1.0,
        min_soc_limit=10.0,
        max_soc_limit=90.0,
    )
    soc_1h, _ = apply_soc_change(**kwargs, dt_h=1.0)
    soc_qh, _ = apply_soc_change(**kwargs, dt_h=0.25)
    assert soc_1h == 90.0  # +40% capped at 90
    assert soc_qh == 60.0


def test_charge_kw_for_slot_scales_with_dt_h():
    kw = charge_kw_for_hourly_soc(
        50.0,
        60.0,
        10.0,
        1.0,
        10.0,
        10.0,
        90.0,
        dt_h=0.25,
    )
    assert kw == 4.0


def test_max_deliverable_scales_with_dt_h():
    consumer = {"id": "x", "nominal_power_kw": 2.0, "min_power_kw": 0.0}
    assert _max_deliverable_kwh(consumer, [0, 1, 2, 3], dt_h=1.0) == 8.0
    assert _max_deliverable_kwh(consumer, [0, 1, 2, 3], dt_h=0.25) == 2.0


def test_slots_for_wall_hours():
    assert slots_for_wall_hours(1.0, 0.25) == 4
    assert slots_for_wall_hours(1.05, 0.25) == 5
    assert slots_for_wall_hours(24.0) == 96


def test_wall_hours_from_slots():
    assert wall_hours_from_slots(4) == 1
    assert wall_hours_from_slots(96) == 24
    assert wall_hours_from_slots(35040) == 8760
    assert wall_hours_from_slots(35041) == 8760

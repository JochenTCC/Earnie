"""Ledger P3: shadow plant slot engine (spec docs/dev/savings-ledger.md § 3)."""

from __future__ import annotations

import pytest

from runtime_store.savings_ledger import (
    SKIP_DEAD_TELEMETRY,
    SKIP_FEW_SAMPLES,
    SKIP_MISSING,
    SKIP_NO_POWER,
    SKIP_NOT_MEAN,
    advance_slot,
    shadow_battery_params,
    slot_skip_reason,
)

BATTERY = {
    "battery_capacity_kwh": 10.0,
    "efficiency": 0.9,
    "min_soc": 10.0,
    "max_soc": 90.0,
    "max_power_kw": 2.0,
    "standby_power_kw": 0.0,
}
BUY = 30.0
SELL = 8.0


def _closed(pv: float, house: float, grid: float, battery: float = 0.0, **extra) -> dict:
    closed = {
        "interval_start": "2026-11-01T12:00:00",
        "sample_count": 30,
        "pv_kw": pv,
        "grid_kw": grid,
        "battery_kw": battery,
        "house_kw": house,
        "ist_power_source": {"pv": "mean", "grid": "mean", "battery": "mean", "house": "mean"},
    }
    closed.update(extra)
    return closed


def _step(closed, soc, battery=BATTERY, **kw):
    return advance_slot(closed, soc, battery, k_act_cent=BUY, k_push_cent=SELL, **kw)


def test_pv_surplus_charges_the_shadow_battery():
    # Earnie held the battery and exported the surplus; vendor mode charges it.
    slot = _step(_closed(pv=3.0, house=1.0, grid=-2.0), 50.0)

    assert slot.counted
    assert slot.shadow_battery_kw == pytest.approx(2.0)
    assert slot.shadow_soc_next == pytest.approx(50.0 + 2.0 * 0.9 * 0.25 / 10.0 * 100)
    assert slot.cost_without_eur == pytest.approx(0.0)
    assert slot.cost_with_eur == pytest.approx(-2.0 * 0.25 * SELL / 100)
    assert slot.export_kwh_with == pytest.approx(0.5)
    assert slot.export_kwh_without == pytest.approx(0.0)
    assert slot.saving_eur == pytest.approx(0.04)


def test_deficit_discharges_the_shadow_battery():
    # Earnie blocked discharge and imported; vendor mode covers the load.
    slot = _step(_closed(pv=0.0, house=1.0, grid=1.0), 50.0)

    assert slot.shadow_battery_kw == pytest.approx(-1.0)
    assert slot.shadow_soc_next == pytest.approx(50.0 - 1.0 / 0.9 * 0.25 / 10.0 * 100)
    assert slot.cost_without_eur == pytest.approx(0.0)
    assert slot.cost_with_eur == pytest.approx(0.25 * BUY / 100)
    assert slot.import_kwh_with == pytest.approx(0.25)
    assert slot.saving_eur == pytest.approx(-0.075)


def test_min_soc_limits_the_discharge():
    slot = _step(_closed(pv=0.0, house=2.0, grid=2.0), 10.5)

    # 0.5 % of 10 kWh = 0.05 kWh stored, 0.045 kWh delivered → 0.18 kW over 0.25 h
    assert slot.shadow_soc_next == pytest.approx(10.0)
    assert slot.shadow_battery_kw == pytest.approx(-0.18)
    assert slot.import_kwh_without == pytest.approx((2.0 - 0.18) * 0.25)


def test_max_soc_limits_the_charge_and_exports_the_rest():
    slot = _step(_closed(pv=3.0, house=1.0, grid=-2.0), 89.5)

    assert slot.shadow_soc_next == pytest.approx(90.0)
    charge_kw = 0.05 / (0.9 * 0.25)
    assert slot.shadow_battery_kw == pytest.approx(charge_kw)
    assert slot.export_kwh_without == pytest.approx((2.0 - charge_kw) * 0.25)
    assert slot.cost_without_eur == pytest.approx(-(2.0 - charge_kw) * 0.25 * SELL / 100)


def test_max_power_limits_the_charge():
    slot = _step(_closed(pv=6.0, house=1.0, grid=-5.0), 50.0)

    assert slot.shadow_battery_kw == pytest.approx(2.0)
    assert slot.export_kwh_without == pytest.approx(3.0 * 0.25)


def test_standby_loss_drains_the_shadow_battery_and_is_imported_at_min_soc():
    battery = {**BATTERY, "standby_power_kw": 0.04}

    # PV covers the house exactly; only the standby is left
    draining = _step(_closed(pv=0.5, house=0.5, grid=0.0), 50.0, battery=battery)
    assert draining.shadow_battery_kw == pytest.approx(-0.04)
    assert draining.shadow_soc_next < 50.0
    assert draining.cost_without_eur == pytest.approx(0.0)

    empty = _step(_closed(pv=0.5, house=0.5, grid=0.0), 10.0, battery=battery)
    assert empty.shadow_soc_next == pytest.approx(10.0)
    assert empty.import_kwh_without == pytest.approx(0.04 * 0.25)
    assert empty.cost_without_eur == pytest.approx(0.01 * BUY / 100)


def test_import_and_export_use_their_own_prices():
    slot = advance_slot(
        _closed(pv=0.0, house=1.0, grid=-1.0, battery=2.0),
        10.0,
        BATTERY,
        k_act_cent=40.0,
        k_push_cent=5.0,
    )

    # with: Earnie discharged 2 kW into the grid at the sell price
    assert slot.cost_with_eur == pytest.approx(-0.25 * 5.0 / 100)
    # without: battery at min_soc, the load is imported at the buy price
    assert slot.cost_without_eur == pytest.approx(0.25 * 40.0 / 100)


def test_slot_length_scales_the_soc_step():
    quarter = _step(_closed(pv=3.0, house=1.0, grid=-2.0), 50.0)
    half = _step(_closed(pv=3.0, house=1.0, grid=-2.0), 50.0, dt_h=0.5)

    assert half.shadow_soc_next - 50.0 == pytest.approx(2 * (quarter.shadow_soc_next - 50.0))
    assert half.cost_with_eur == pytest.approx(2 * quarter.cost_with_eur)


@pytest.mark.parametrize(
    ("closed", "reason"),
    [
        (None, SKIP_MISSING),
        ({}, SKIP_MISSING),
        (_closed(1.0, 1.0, 0.0, sample_count=2), SKIP_FEW_SAMPLES),
        (
            _closed(
                1.0,
                1.0,
                0.0,
                ist_power_source={"pv": "counter", "grid": "mean", "battery": "mean", "house": "mean"},
            ),
            SKIP_NOT_MEAN,
        ),
        (_closed(1.0, 1.0, 0.0, ist_power_source=None), SKIP_NOT_MEAN),
        (_closed(1.0, None, 0.0), SKIP_NO_POWER),
        (_closed(0.0, 0.0, 0.0), SKIP_DEAD_TELEMETRY),
    ],
)
def test_invalid_slot_is_skipped_on_both_sides(closed, reason):
    assert slot_skip_reason(closed) == reason

    slot = _step(closed, 42.0)

    assert not slot.counted
    assert slot.skip_reason == reason
    assert slot.cost_with_eur == 0.0
    assert slot.cost_without_eur == 0.0
    assert slot.shadow_soc_next == 42.0


def test_valid_slot_has_no_skip_reason():
    assert slot_skip_reason(_closed(1.0, 1.0, 0.0)) is None


def test_multi_ess_is_aggregated_like_the_baseline():
    second = {**BATTERY, "standby_power_kw": 0.02, "max_power_kw": 3.0}
    agg = shadow_battery_params([{**BATTERY, "standby_power_kw": 0.01}, second])

    assert agg["standby_power_kw"] == pytest.approx(0.03)
    assert agg["max_power_kw"] == pytest.approx(5.0)
    assert shadow_battery_params(BATTERY) == BATTERY


def test_missing_battery_params_fail_loud():
    with pytest.raises(ValueError, match="no house battery"):
        shadow_battery_params(None)
    with pytest.raises(ValueError, match="no house battery"):
        shadow_battery_params([])

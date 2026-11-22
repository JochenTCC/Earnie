"""Reserve P3: tolerance at the virtual reserve floor (reading steps, refill band).

Spec: ``docs/dev/virtual-reserve-price-aware.md`` § Design 3. Live pattern 2026-11-21
(maintainer's plant): 15 kWh, min_soc 5 %, 1.1 kWh virtual reserve (floor 12.33 %), SoC read in
whole percent, idle drain about 1 %/h. A reading of 13 % released 0.34 kW of Automatik discharge
for one slot, a reading of 11 % forced a 0.9 kW grid charge for one slot: 22 forced charge slots
that day.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from optimizer.milp import milp_horizon_schedule, milp_optimizer
from optimizer.powerstation_reserve import (
    prepare_battery_params_for_reserves,
    reserve_floor_discharge_cap_kw,
)
from optimizer.reserve_price_floor import (
    BAND_HOLD_SLOTS,
    BAND_MIN_READING_STEPS,
    SOC_READING_RESOLUTION_PCT,
    banded_floor_kwh,
    reserve_floor_band_soc_pct,
    reserve_price_floor,
)

_CAP_KWH = 15.0
_ETA = 0.94
_RESERVE_KWH = 1.1
_BASE_SOC = 5.0
_FLOOR_SOC = _BASE_SOC + _RESERVE_KWH / _CAP_KWH * 100.0  # 12.333 %
_FLOOR_KWH = _FLOOR_SOC / 100.0 * _CAP_KWH
_DRAIN_KW = 0.15  # 1 %/h of 15 kWh
_DT_H = 0.25
_START = datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)
_KW_TOL = 1e-6
_HIGH = 45.0  # ct: the reserve pays in every slot of the horizon


def _battery(**overrides) -> dict:
    out = {
        "id": "house",
        "battery_capacity_kwh": _CAP_KWH,
        "min_soc": _BASE_SOC,
        "max_soc": 100.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "max_power_kw": 5.0,
        "efficiency": _ETA,
        "control": "full",
    }
    out.update(overrides)
    return out


def _held(*, basis_at: datetime = _START, **bat) -> dict:
    """Reserve stored at 25 ct at ``basis_at``.

    It pays above 25 / 0.94² ≈ 28.3 ct plus the hold cost: with the drain of 1 %/h about
    3.6 ct per hour held (``reserve_price_floor``), so 45 ct pays over a 16-slot horizon.
    """
    reserve = {
        "powerstation_id": "vps",
        "backing": "virtual",
        "state": "standby",
        "target_kwh": _RESERVE_KWH,
        "stored_kwh": _RESERVE_KWH,
        "protected_kwh": _RESERVE_KWH,
        "asap_charge_kwh": 0.0,
        "fill_basis_price": 25.0,
        "fill_basis_at": basis_at.isoformat(),
    }
    return prepare_battery_params_for_reserves(_battery(**bat), [reserve])


def _matrix(prices: list[float], *, start: datetime = _START, load_kw: float = 0.4) -> list[dict]:
    rows = []
    for t, price in enumerate(prices):
        dt = start + timedelta(minutes=15 * t)
        rows.append(
            {
                "hour": dt.hour,
                "date": dt.date(),
                "slot_datetime": dt,
                "expected_p_pv": 0.0,
                "expected_p_act": load_kw,
                "k_act": price,
                "k_push_act": 5.0,
                "expected_flex_kw": {},
            }
        )
    return rows


def _charge_kw(battery: dict, soc: float, prices: list[float]) -> list[float]:
    matrix = _matrix(prices)
    schedule = milp_horizon_schedule(
        matrix, soc, battery_params=battery, k_push=5.0, verbose=False, consumers=[]
    )
    assert len(schedule) == len(matrix), "plan fell back (no optimal solve)"
    return [float(slot["milp_plan"]["p_charge"]) for slot in schedule]


# --- band size -----------------------------------------------------------------------------------


def test_band_without_drain_is_two_reading_steps() -> None:
    assert reserve_floor_band_soc_pct(_battery(), dt_h=_DT_H) == pytest.approx(
        BAND_MIN_READING_STEPS * SOC_READING_RESOLUTION_PCT
    )
    assert BAND_MIN_READING_STEPS >= 2


def test_band_follows_the_drain_over_the_hold_slots() -> None:
    # 1 %/h over 8 quarter hours = 2 %: the minimum still rules
    assert reserve_floor_band_soc_pct(_battery(idle_drain_kw=_DRAIN_KW), dt_h=_DT_H) == pytest.approx(2.0)
    # 4 %/h: the drain of BAND_HOLD_SLOTS slots
    strong = _battery(idle_drain_kw=0.6)
    expected = 0.6 * BAND_HOLD_SLOTS * _DT_H / _CAP_KWH * 100.0
    assert reserve_floor_band_soc_pct(strong, dt_h=_DT_H) == pytest.approx(expected)
    assert expected > 2.0


def test_band_fails_loud_without_slot_length() -> None:
    with pytest.raises(ValueError, match="dt_h"):
        reserve_floor_band_soc_pct(_battery(), dt_h=0.0)


# --- floor per slot ------------------------------------------------------------------------------


def _floors(battery: dict, soc: float, prices: list[float]) -> list[float]:
    plan = reserve_price_floor(battery, _matrix(prices), horizon=len(prices), dt_h=_DT_H)
    assert plan is not None
    return banded_floor_kwh(plan, battery, e_init=soc / 100.0 * _CAP_KWH, dt_h=_DT_H)


def test_inside_the_band_the_bound_follows_the_drain() -> None:
    battery = _held(idle_drain_kw=_DRAIN_KW)
    floors = _floors(battery, 12.0, [_HIGH] * 16)
    drain = _DRAIN_KW * _DT_H
    start = 12.0 / 100.0 * _CAP_KWH
    assert floors == pytest.approx([start - drain * (k + 1) for k in range(16)])
    # not held at the band bottom: the next cycles refill once the reading leaves the band
    bottom = (_FLOOR_SOC - 2.0) / 100.0 * _CAP_KWH
    assert floors[-1] < bottom


def test_one_step_above_the_floor_is_held_where_it_is() -> None:
    floors = _floors(_held(), 13.0, [_HIGH] * 16)
    assert floors == pytest.approx([13.0 / 100.0 * _CAP_KWH] * 16)
    # two steps above: the energy above the floor is free, the floor stays
    assert _floors(_held(), 14.0, [_HIGH] * 16) == pytest.approx([_FLOOR_KWH] * 16)


def test_beyond_the_band_the_floor_is_due_in_slot_0_then_follows_the_drain() -> None:
    battery = _held(idle_drain_kw=_DRAIN_KW)
    floors = _floors(battery, 10.0, [_HIGH] * 16)
    drain = _DRAIN_KW * _DT_H
    assert floors == pytest.approx([_FLOOR_KWH - drain * k for k in range(16)])


def test_band_changes_only_the_paying_run_from_slot_0() -> None:
    battery = _held()
    prices = [_HIGH] * 4 + [20.0] * 4 + [_HIGH] * 8
    floors = _floors(battery, 11.0, prices)
    base = _BASE_SOC / 100.0 * _CAP_KWH
    assert floors[:4] == pytest.approx([11.0 / 100.0 * _CAP_KWH] * 4)
    assert floors[4:7] == pytest.approx([base] * 3)
    # the next paying run keeps the full floor: the gap is due there (built in the cheap slots)
    assert floors[7:] == pytest.approx([_FLOOR_KWH] * 9)


def test_band_bottom_is_never_below_the_configured_min_soc() -> None:
    small = {
        "powerstation_id": "vps",
        "backing": "virtual",
        "protected_kwh": 0.03,  # +0.2 %
        "asap_charge_kwh": 0.0,
        "fill_basis_price": 25.0,
        "fill_basis_at": _START.isoformat(),
    }
    battery = prepare_battery_params_for_reserves(_battery(idle_drain_kw=_DRAIN_KW), [small])
    floors = _floors(battery, 5.1, [_HIGH] * 16)
    assert min(floors) == pytest.approx(_BASE_SOC / 100.0 * _CAP_KWH)


# --- readings one step around the floor ----------------------------------------------------------


@pytest.mark.parametrize("soc", [12.0, 13.0])
def test_reading_one_step_around_the_floor_releases_no_discharge(soc: float) -> None:
    battery = _held(idle_drain_kw=_DRAIN_KW)
    cap = reserve_floor_discharge_cap_kw(battery, soc, dt_h=_DT_H, matrix=_matrix([_HIGH] * 16))
    assert cap == pytest.approx(0.0)


@pytest.mark.parametrize("soc", [11.0, 12.0, 13.0])
def test_reading_around_the_floor_forces_no_charge(soc: float) -> None:
    battery = _held(idle_drain_kw=_DRAIN_KW)
    charge = _charge_kw(battery, soc, [_HIGH] * 16)
    assert charge[0] <= _KW_TOL


def test_reading_one_step_above_the_floor_plans_no_discharge() -> None:
    battery = _held(idle_drain_kw=_DRAIN_KW)
    matrix = _matrix([_HIGH] * 16)
    schedule = milp_horizon_schedule(
        matrix, 13.0, battery_params=battery, k_push=5.0, verbose=False, consumers=[]
    )
    assert float(schedule[0]["milp_plan"]["p_discharge"]) <= _KW_TOL


def test_gap_beyond_the_band_is_refilled_in_one_block_up_to_the_floor() -> None:
    battery = _held(idle_drain_kw=_DRAIN_KW)
    charge = _charge_kw(battery, 10.0, [_HIGH] * 16)
    assert charge[0] > 0.0
    assert all(c <= _KW_TOL for c in charge[1:]), "refill spread over several slots"
    gap = _FLOOR_KWH - 10.0 / 100.0 * _CAP_KWH + _DRAIN_KW * _DT_H
    assert charge[0] * _DT_H * _ETA == pytest.approx(gap, abs=1e-3)


# --- replay of the live day 2026-11-21 -----------------------------------------------------------


def _day_prices() -> list[float]:
    """Hourly prices between 43 and 50 ct: the reserve pays all day, as the single floor did."""
    hourly = [46.5 + 3.5 * math.sin(2.0 * math.pi * (h - 6) / 24.0) for h in range(24)]
    return [p for p in hourly for _ in range(4)]


def _replay_day(reading) -> tuple[int, int]:
    """Live loop over 96 slots: plan from the whole-percent reading, run slot 0, drain.

    Returns (forced charge slots, slots with Automatik discharge release).
    """
    prices = _day_prices() + _day_prices()[:16]
    true_soc = 12.6
    charge_slots = 0
    release_slots = 0
    for t in range(96):
        start = _START + timedelta(minutes=15 * t)
        matrix = _matrix(prices[t : t + 16], start=start)
        # live keeps the fill basis while the floor is held; a fresh one keeps it held all day
        battery = _held(basis_at=start, idle_drain_kw=_DRAIN_KW)
        soc = float(reading(true_soc))
        mode, target_kw, *_rest = milp_optimizer(
            matrix,
            current_hour=start.hour,
            current_soc=soc,
            battery_params=battery,
            consumers=[],
        )
        mode = int(mode)
        if mode == 1:
            charge_slots += 1
            true_soc += float(target_kw) * _DT_H * _ETA / _CAP_KWH * 100.0
        elif mode == 0:
            cap = reserve_floor_discharge_cap_kw(battery, soc, dt_h=_DT_H, matrix=matrix)
            used_kw = min(0.4, cap if cap is not None else 5.0)
            if used_kw > _KW_TOL:
                release_slots += 1
            true_soc -= used_kw * _DT_H / _ETA / _CAP_KWH * 100.0
        elif mode == 3:
            true_soc -= float(target_kw) * _DT_H / _ETA / _CAP_KWH * 100.0
        true_soc -= _DRAIN_KW * _DT_H / _CAP_KWH * 100.0
        assert true_soc >= _FLOOR_SOC - 3.5, f"reserve lost at slot {t}: {true_soc:.2f} %"
    return charge_slots, release_slots


@pytest.mark.parametrize(
    "reading",
    [math.floor, lambda soc: math.floor(soc + 0.5)],
    ids=["truncated", "rounded"],
)
def test_live_day_replay_needs_far_fewer_forced_charge_slots(reading) -> None:
    charge_slots, release_slots = _replay_day(reading)
    assert release_slots == 0
    # 22 forced charge slots on 2026-11-21; this replay: 9 (one block about every 2.5 h),
    # 42 with the one-step relaxation of P2 and the drain in the model
    assert charge_slots <= 11, charge_slots

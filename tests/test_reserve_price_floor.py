"""Reserve P2: the virtual reserve is held per slot only where it pays (price-aware floor).

Spec: ``docs/dev/virtual-reserve-price-aware.md`` § Design 2. The reserve pays in slot ``t`` when
``price[t] > fill_price / efficiency**2 + hold cost``; the fill price is the cheapest slot
before ``t`` or the persisted fill basis of energy already stored.

Live pattern 2026-11-21 (maintainer's plant): 15 kWh, min_soc 5 %, 1.1 kWh virtual reserve
(floor 12.33 %), reading 11 % at cheap prices forced a grid charge every few slots.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from optimizer.milp import milp_horizon_schedule
from optimizer.powerstation_reserve import (
    prepare_battery_params_for_reserves,
    reserve_floor_discharge_cap_kw,
)
from optimizer.reserve_price_floor import (
    BASIS_PRICE_KEY,
    FLOOR_SOC_KEY,
    RESERVE_KWH_KEY,
    reserve_price_floor,
)

_CAP_KWH = 15.0
_ETA = 0.94
_RESERVE_KWH = 1.1
_BASE_SOC = 5.0
_FLOOR_SOC = _BASE_SOC + _RESERVE_KWH / _CAP_KWH * 100.0  # 12.333 %
_FLOOR_KWH = _FLOOR_SOC / 100.0 * _CAP_KWH
_DT_H = 0.25
_START = datetime(2026, 11, 21, 6, 0, tzinfo=timezone.utc)
_SOC_TOL = 0.11  # planned SoC is rounded to 0.1 %
_KW_TOL = 1e-6


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


def _reserve(*, state: str = "standby", basis: tuple[float, datetime] | None = None) -> dict:
    standby = state == "standby"
    return {
        "powerstation_id": "vps",
        "backing": "virtual",
        "state": state,
        "target_kwh": _RESERVE_KWH,
        "stored_kwh": _RESERVE_KWH if standby else 0.0,
        "protected_kwh": _RESERVE_KWH if standby else 0.0,
        "asap_charge_kwh": 0.0 if standby else _RESERVE_KWH,
        "fill_basis_price": basis[0] if basis else None,
        "fill_basis_at": basis[1].isoformat() if basis else None,
    }


def _prepared(reserve: dict | None = None, **bat) -> dict:
    return prepare_battery_params_for_reserves(_battery(**bat), [reserve or _reserve()])


def _matrix(prices: list[float], *, load_kw: float = 0.4) -> list[dict]:
    rows = []
    for t, price in enumerate(prices):
        dt = _START + timedelta(minutes=15 * t)
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


def _schedule(matrix: list[dict], soc: float, battery: dict) -> list[dict]:
    schedule = milp_horizon_schedule(
        matrix, soc, battery_params=battery, k_push=5.0, verbose=False, consumers=[]
    )
    assert len(schedule) == len(matrix), "plan fell back (no optimal solve)"
    return schedule


def _charge_kw(schedule: list[dict]) -> list[float]:
    return [float(slot["milp_plan"]["p_charge"]) for slot in schedule]


def _soc(schedule: list[dict]) -> list[float]:
    return [float(slot["planned_soc_percent"]) for slot in schedule]


# --- floor per slot ------------------------------------------------------------------------


def test_params_keep_min_soc_and_carry_the_reserve() -> None:
    battery = _prepared(_reserve(state="empty"))
    assert battery["min_soc"] == pytest.approx(_BASE_SOC)
    assert battery[FLOOR_SOC_KEY] == pytest.approx(_FLOOR_SOC)
    # empty reserve: the whole target is due where it pays
    assert battery[RESERVE_KWH_KEY] == pytest.approx(_RESERVE_KWH)
    assert BASIS_PRICE_KEY not in battery


def test_flat_prices_give_no_floor() -> None:
    plan = reserve_price_floor(_prepared(), _matrix([30.0] * 16), horizon=16, dt_h=_DT_H)
    assert plan is not None
    assert not any(plan.pays)
    assert plan.floor_kwh == pytest.approx([_BASE_SOC / 100.0 * _CAP_KWH] * 16)
    assert not plan.held_now


def test_price_step_floors_the_expensive_slots_from_the_slot_before() -> None:
    plan = reserve_price_floor(
        _prepared(), _matrix([20.0] * 8 + [35.0] * 8), horizon=16, dt_h=_DT_H
    )
    assert plan.pays == [False] * 8 + [True] * 8
    # energy at the end of slot 7 = start of the first expensive slot carries the reserve
    assert plan.floor_kwh[6] == pytest.approx(_BASE_SOC / 100.0 * _CAP_KWH)
    assert plan.floor_kwh[7:] == pytest.approx([_FLOOR_KWH] * 9)
    assert plan.fill_price[8] == pytest.approx(20.0)


def test_round_trip_is_efficiency_squared() -> None:
    # 22 ct < 20 / 0.94² = 22.6 ct: not worth it; with a lossless battery it is
    matrix = _matrix([20.0, 22.0])
    assert reserve_price_floor(_prepared(), matrix, horizon=2, dt_h=_DT_H).pays == [False, False]
    lossless = _prepared(efficiency=1.0)
    assert reserve_price_floor(lossless, matrix, horizon=2, dt_h=_DT_H).pays == [False, True]


def test_idle_drain_hold_cost_drops_a_reserve_that_barely_pays() -> None:
    # 20 / 0.94² = 22.6 ct; 8 h hold at 0.125 kW = 1 kWh of drain on a 1.1 kWh reserve
    prices = [20.0] + [21.0] * 31 + [24.0]
    without = reserve_price_floor(_prepared(), _matrix(prices), horizon=33, dt_h=_DT_H)
    assert without.pays[-1]
    draining = _prepared(idle_drain_kw=0.125)
    with_drain = reserve_price_floor(draining, _matrix(prices), horizon=33, dt_h=_DT_H)
    assert not with_drain.pays[-1]


def test_fill_basis_keeps_the_floor_inside_an_expensive_phase() -> None:
    basis = (25.0, _START - timedelta(hours=1))
    battery = _prepared(_reserve(basis=basis))
    assert battery[BASIS_PRICE_KEY] == pytest.approx(25.0)
    plan = reserve_price_floor(battery, _matrix([35.0] * 16), horizon=16, dt_h=_DT_H)
    assert all(plan.pays)
    assert plan.held_now
    assert plan.fill_price[0] == pytest.approx(25.0)
    assert plan.fill_at[0] == basis[1]
    # without the basis the same re-plan sees only expensive slots: no floor
    plain = reserve_price_floor(_prepared(), _matrix([35.0] * 16), horizon=16, dt_h=_DT_H)
    assert not any(plain.pays)


def test_fill_slot_needs_a_timed_matrix() -> None:
    # The basis counts the hold from slot 0 (review fix 2026-11-22) and needs no slot time;
    # a horizon slot that becomes the fill source does (it may become the persisted basis).
    battery = _prepared(_reserve(basis=(25.0, _START)))
    untimed = _matrix([35.0] * 4)
    del untimed[0]["slot_datetime"]
    assert all(reserve_price_floor(battery, untimed, horizon=4, dt_h=_DT_H).pays)
    matrix = _matrix([20.0] + [35.0] * 3)
    del matrix[0]["slot_datetime"]
    with pytest.raises(ValueError, match="slot_datetime"):
        reserve_price_floor(_prepared(), matrix, horizon=4, dt_h=_DT_H)


def test_released_reserve_has_no_floor() -> None:
    released = {**_reserve(), "state": "discharging", "protected_kwh": 0.0, "asap_charge_kwh": 0.0}
    battery = _prepared(released)
    assert FLOOR_SOC_KEY not in battery
    assert reserve_price_floor(battery, _matrix([20.0, 40.0]), horizon=2, dt_h=_DT_H) is None


# --- MILP --------------------------------------------------------------------------------------


def test_milp_flat_prices_empty_reserve_charges_nothing() -> None:
    schedule = _schedule(_matrix([30.0] * 16), _BASE_SOC, _prepared(_reserve(state="empty")))
    assert max(_charge_kw(schedule)) <= _KW_TOL


def test_milp_price_step_builds_the_reserve_in_the_cheapest_slots_before() -> None:
    prices = [24.0] * 4 + [18.0] * 2 + [24.0] * 2 + [35.0] * 8
    schedule = _schedule(_matrix(prices), _BASE_SOC, _prepared(_reserve(state="empty")))
    charge = _charge_kw(schedule)
    soc = _soc(schedule)
    assert soc[7] >= _FLOOR_SOC - _SOC_TOL, "reserve not full at the first expensive slot"
    assert all(s >= _FLOOR_SOC - _SOC_TOL for s in soc[7:])
    assert sum(charge[4:6]) > 0.0
    assert all(charge[t] <= _KW_TOL for t in range(16) if t not in (4, 5))


def test_milp_full_reserve_at_a_cheap_phase_is_not_forced_out() -> None:
    schedule = _schedule(_matrix([20.0] * 16), _FLOOR_SOC, _prepared())
    for slot in schedule:
        plan = slot["milp_plan"]
        assert float(plan["p_grid_sell"]) <= _KW_TOL, "reserve exported"
        assert float(plan["p_charge"]) <= _KW_TOL
    # the plan may use the energy for the house load, it is not held
    assert min(_soc(schedule)) < _FLOOR_SOC - _SOC_TOL


def test_milp_live_pattern_no_floor_in_slot_0_forces_no_charge() -> None:
    """Reading 11 % under a 12.33 % floor at cheap prices (2026-11-21): no slot-0 charge."""
    battery = _prepared()
    flat = _schedule(_matrix([25.4] * 16), 11.0, battery)
    assert max(_charge_kw(flat)) <= _KW_TOL
    # an expensive phase later: the reserve is built in the cheapest slots before it, not now
    prices = [30.0] * 4 + [25.4] * 4 + [30.0] * 4 + [37.0] * 4
    later = _schedule(_matrix(prices), 11.0, battery)
    charge = _charge_kw(later)
    assert charge[0] <= _KW_TOL
    assert sum(charge[4:8]) > 0.0
    assert _soc(later)[11] >= _FLOOR_SOC - _SOC_TOL


def test_milp_fill_basis_holds_the_reserve_through_the_expensive_phase() -> None:
    battery = _prepared(_reserve(basis=(25.0, _START - timedelta(hours=1))))
    schedule = _schedule(_matrix([35.0] * 16), 20.0, battery)
    assert min(_soc(schedule)) >= _FLOOR_SOC - _SOC_TOL
    plain = _schedule(_matrix([35.0] * 16), 20.0, _prepared())
    assert min(_soc(plain)) < _FLOOR_SOC - _SOC_TOL


def test_milp_unreachable_floor_is_lowered_with_a_warning(caplog) -> None:
    battery = _prepared(_reserve(state="empty"), max_charge_power_kw=0.5, max_power_kw=5.0)
    with caplog.at_level(logging.WARNING):
        schedule = _schedule(_matrix([20.0] + [40.0] * 15), _BASE_SOC, battery)
    assert "nicht erreichbar" in caplog.text
    charge = _charge_kw(schedule)
    assert charge[0] == pytest.approx(0.5, abs=1e-3)
    assert _soc(schedule)[-1] >= _FLOOR_SOC - _SOC_TOL


# --- Automatik discharge cap -------------------------------------------------------------------


def test_discharge_cap_only_where_the_reserve_is_held_now() -> None:
    battery = _prepared()
    assert reserve_floor_discharge_cap_kw(
        battery, 13.0, dt_h=_DT_H, matrix=_matrix([30.0] * 8)
    ) is None
    # 14 % is more than one reading step above the floor (Reserve P3: 13 % releases nothing)
    cap = reserve_floor_discharge_cap_kw(
        battery, 14.0, dt_h=_DT_H, matrix=_matrix([20.0] + [35.0] * 7)
    )
    assert cap == pytest.approx((14.0 - _FLOOR_SOC) / 100.0 * _CAP_KWH * _ETA / _DT_H)


# --- fill basis persistence --------------------------------------------------------------------


@pytest.fixture
def store(tmp_path, monkeypatch):
    from runtime_store import powerstation_reserves as store

    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "reserves.json"))
    states = store.load_reserve_states()
    entry = store.get_or_init_state(states, "vps", target_kwh=_RESERVE_KWH)
    entry["state"] = store.STATE_STANDBY
    entry["stored_kwh"] = _RESERVE_KWH
    store.save_reserve_states(states)
    return store


def test_live_cycle_persists_and_clears_the_fill_basis(store) -> None:
    from optimizer.powerstation_live import update_reserve_fill_basis

    reserves = [_reserve()]
    # cheap slot 0, expensive from slot 1: held now, basis = slot-0 price
    update_reserve_fill_basis(
        _prepared(), _matrix([20.0] + [35.0] * 7), reserves, dt_h=_DT_H
    )
    entry = store.load_reserve_states()["vps"]
    assert entry["fill_basis_price"] == pytest.approx(20.0)
    assert datetime.fromisoformat(entry["fill_basis_at"]) == _START

    # next re-plan inside the expensive phase reads the basis and keeps it
    basis = (entry["fill_basis_price"], datetime.fromisoformat(entry["fill_basis_at"]))
    held = _prepared(_reserve(basis=basis))
    update_reserve_fill_basis(held, _matrix([35.0] * 8), [_reserve(basis=basis)], dt_h=_DT_H)
    assert store.load_reserve_states()["vps"]["fill_basis_price"] == pytest.approx(20.0)

    # cheap phase: the floor drops, the basis is cleared
    update_reserve_fill_basis(held, _matrix([15.0] * 8), [_reserve(basis=basis)], dt_h=_DT_H)
    assert store.load_reserve_states()["vps"]["fill_basis_price"] is None


def test_trigger_and_empty_reserve_clear_the_fill_basis(store) -> None:
    from optimizer.powerstation_reserve import advance_reserve_after_slot

    states = store.load_reserve_states()
    store.set_fill_basis(states["vps"], price=20.0, at=_START)
    store.save_reserve_states(states)
    store.set_trigger("vps", active=True)
    assert store.load_reserve_states()["vps"]["fill_basis_price"] is None

    states = store.load_reserve_states()
    store.set_fill_basis(states["vps"], price=20.0, at=_START)
    store.save_reserve_states(states)
    advance_reserve_after_slot(powerstation_id="vps", discharged_kwh=_RESERVE_KWH)
    entry = store.load_reserve_states()["vps"]
    assert entry["state"] == store.STATE_EMPTY
    assert entry["fill_basis_price"] is None

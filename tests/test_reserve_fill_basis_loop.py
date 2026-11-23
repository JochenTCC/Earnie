"""Reserve P2: the fill basis in a live loop (prices that rise gradually).

Slot 0 pays only through the persisted basis. ``update_reserve_fill_basis`` used to persist it
only while the floor was held at the end of slot 0, which needs slot 1 to pay from slot 0. With a
gradual rise (0.5 ct per quarter hour) slot 1 never exceeds the round-trip threshold of slot 0, so
the basis was never set and the floor of a full reserve was not held inside the expensive phase.
Now it is kept while any slot of the horizon pays from the basis or slot 0. Synthetic prices.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from optimizer.powerstation_live import update_reserve_fill_basis
from optimizer.reserve_price_floor import reserve_price_floor
from tests.test_reserve_price_floor import (
    _DT_H,
    _ETA,
    _START,
    _matrix,
    _prepared,
    _reserve,
    store,  # noqa: F401  (fixture)
)

_CHEAP_CT = 29.5
_EXPENSIVE_CT = 41.0
_HORIZON = 96


def _live_loop(store, curve: list[float], cycles: int) -> list[tuple[float, bool]]:
    """Plan from the persisted basis, then ``update_reserve_fill_basis`` as main.py does.

    Returns (slot 0 price, floor held at the end of slot 0) per cycle; the reserve stays full.
    """
    out: list[tuple[float, bool]] = []
    for c in range(cycles):
        prices = [curve[(c + i) % len(curve)] for i in range(_HORIZON)]
        matrix = _matrix(prices)
        for i, row in enumerate(matrix):
            row["slot_datetime"] = _START + timedelta(minutes=15 * (c + i))
        entry = store.load_reserve_states()["vps"]
        basis = None
        if entry.get("fill_basis_price") is not None:
            basis = (entry["fill_basis_price"], datetime.fromisoformat(entry["fill_basis_at"]))
        reserve = _reserve(basis=basis)
        battery = _prepared(reserve)
        plan = reserve_price_floor(battery, matrix, horizon=len(matrix), dt_h=_DT_H)
        assert plan is not None
        update_reserve_fill_basis(battery, matrix, [reserve], dt_h=_DT_H)
        out.append((prices[0], plan.held_now))
    return out


def _expensive_cycles(curve: list[float], rows: list[tuple[float, bool]]) -> list[tuple[float, bool]]:
    """Cycles whose slot 0 price is above the cheapest price of the day over the round trip."""
    limit = min(curve) / (_ETA * _ETA)
    return [r for r in rows if r[0] > limit + 1e-9]


def _step_day() -> list[float]:
    return [_CHEAP_CT] * 48 + [_EXPENSIVE_CT] * 48


def _ramp_day() -> list[float]:
    n = 24
    ramp = [_CHEAP_CT + 0.5 * i for i in range(n)]
    fall = [_EXPENSIVE_CT - 0.5 * i for i in range(n)]
    return [_CHEAP_CT] * n + ramp + [_EXPENSIVE_CT] * n + fall


def test_price_step_sets_the_basis_and_holds_through_the_expensive_phase(store) -> None:
    curve = _step_day()
    expensive = _expensive_cycles(curve, _live_loop(store, curve, 96))
    assert expensive
    assert all(held for _price, held in expensive)


def test_gradual_price_rise_holds_the_floor_through_the_expensive_phase(store) -> None:
    curve = _ramp_day()
    expensive = _expensive_cycles(curve, _live_loop(store, curve, 96))
    held = [r for r in expensive if r[1]]
    assert len(held) == len(expensive), f"held in {len(held)} of {len(expensive)} expensive cycles"

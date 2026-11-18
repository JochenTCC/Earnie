"""Virtual-reserve refill: a too-short deadline window must not lower the requirement silently.

The window charges what it can; the rest is required in the slots right after it (as soon as
possible), with a warning. Only an amount beyond the horizon end stays unplanned (warning).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pulp
import pytest

from optimizer.milp import _add_virtual_reserve_refill
from optimizer.milp_horizon_extras import _add_virtual_reserve_deadline_charge

_START = datetime(2026, 11, 18, 0, tzinfo=timezone.utc)
_DT_H = 0.25
_MAX_KW = 2.0
_WINDOW = "virtual_reserve_deadline_charge"
_AFTER = "virtual_reserve_after_deadline_charge"


def _model(horizon: int):
    prob = pulp.LpProblem("reserve_cap", pulp.LpMinimize)
    p_charge = [pulp.LpVariable(f"c{t}", lowBound=0, upBound=_MAX_KW) for t in range(horizon)]
    model = SimpleNamespace(prob=prob, horizon=horizon, p_charge=p_charge, dt_h=_DT_H)
    matrix = [
        {"slot_datetime": _START + timedelta(minutes=15 * t)} for t in range(horizon)
    ]
    return model, matrix


def _deadline_after(slots: int) -> datetime:
    return _START + timedelta(minutes=15 * slots)


def _add(model, matrix, deadline, refill_kwh=3.0):
    _add_virtual_reserve_deadline_charge(
        model,
        matrix=matrix,
        refill_kwh=refill_kwh,
        max_charge_kw=_MAX_KW,
        efficiency=1.0,
        deadline=deadline,
    )


def _slots(model, name: str) -> list[int]:
    return sorted(int(var.name[1:]) for var in model.prob.constraints[name].keys())


def _required_kwh(model, name: str) -> float:
    return -model.prob.constraints[name].constant


def test_window_that_fits_requires_the_full_refill_without_warning(caplog):
    model, matrix = _model(12)
    with caplog.at_level(logging.WARNING):
        _add(model, matrix, _deadline_after(8))
    assert _slots(model, _WINDOW) == list(range(8))
    assert _required_kwh(model, _WINDOW) == pytest.approx(3.0)
    assert _AFTER not in model.prob.constraints
    assert "Nachlade-Fenster" not in caplog.text


def test_short_window_requires_the_rest_right_after_the_deadline(caplog):
    # 3 kWh at 2 kW in four 15-min slots: the window reaches 2 kWh, 1 kWh is left.
    model, matrix = _model(12)
    with caplog.at_level(logging.WARNING):
        _add(model, matrix, _deadline_after(4))
    assert _slots(model, _WINDOW) == [0, 1, 2, 3]
    assert _required_kwh(model, _WINDOW) == pytest.approx(2.0)
    # 1 kWh at 0.5 kWh per slot → the two slots right after the deadline.
    assert _slots(model, _AFTER) == [0, 1, 2, 3, 4, 5]
    assert _required_kwh(model, _AFTER) == pytest.approx(3.0)
    assert "Nachlade-Fenster" in caplog.text


def test_short_window_plan_charges_the_full_refill():
    model, matrix = _model(12)
    _add(model, matrix, _deadline_after(4))
    # Prefer late charging: without the after-deadline constraint the plan would drop 1 kWh.
    model.prob += pulp.lpSum((model.horizon - t) * model.p_charge[t] for t in range(model.horizon))
    model.prob.solve(pulp.HiGHS(msg=False))
    assert pulp.LpStatus[model.prob.status] == "Optimal"
    charged = [model.p_charge[t].value() * _DT_H for t in range(model.horizon)]
    assert sum(charged) == pytest.approx(3.0)
    assert sum(charged[:4]) == pytest.approx(2.0)
    assert sum(charged[6:]) == pytest.approx(0.0)


def test_rest_beyond_the_horizon_end_is_warned_not_hidden(caplog):
    # Window of 4 slots (2 kWh) plus one slot left in the horizon (0.5 kWh): 0.5 kWh beyond.
    model, matrix = _model(5)
    with caplog.at_level(logging.WARNING):
        _add(model, matrix, _deadline_after(4))
    assert _slots(model, _AFTER) == [0, 1, 2, 3, 4]
    assert _required_kwh(model, _AFTER) == pytest.approx(2.5)
    assert "0.500 kWh jenseits des Planungshorizonts" in caplog.text


def test_overdue_refill_longer_than_the_horizon_is_warned(caplog):
    # Deadline overdue → as soon as possible; the four slots of the horizon reach 2 of 3 kWh.
    model, matrix = _model(4)
    with caplog.at_level(logging.WARNING):
        _add(model, matrix, _START - timedelta(hours=1))
    assert _slots(model, _WINDOW) == [0, 1, 2, 3]
    assert _required_kwh(model, _WINDOW) == pytest.approx(2.0)
    assert _AFTER not in model.prob.constraints
    assert "1.000 kWh jenseits des Planungshorizonts" in caplog.text


def test_refill_entry_point_keeps_the_rest_after_the_deadline():
    model, matrix = _model(12)
    primary = {
        "_virtual_reserve_refill_kwh": 3.0,
        "_virtual_reserve_refill_deadline_utc": _deadline_after(4).isoformat(),
        "max_charge_power_kw": _MAX_KW,
        "efficiency": 1.0,
    }
    _add_virtual_reserve_refill(model, matrix, primary)
    assert _required_kwh(model, _WINDOW) == pytest.approx(2.0)
    assert _required_kwh(model, _AFTER) == pytest.approx(3.0)

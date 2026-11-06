"""The plan may export a PV surplus only when the battery could not take it anyway."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from optimizer.battery import power_threshold_kw
from optimizer.milp import _solve_milp_to_model
from optimizer.milp_vendor_mode import (
    FORCED_DISCHARGE_MARGIN,
    VENDOR_MODE_ENV,
    add_vendor_mode_export_constraints,
)
from optimizer.slot_duration import DEFAULT_DT_H

SURPLUS_KW = 2.5


def _battery(*, control: str = "full", max_power_kw: float = 5.0) -> dict:
    return {
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": max_power_kw,
        "efficiency": 0.95,
        "control": control,
    }


def _matrix(hours: int) -> list[dict]:
    return [
        {
            "hour": h,
            "expected_p_pv": 0.5 + SURPLUS_KW,
            "expected_p_act": 0.5,
            "k_act": 20.0,
            "k_push_act": 6.5,
            "expected_flex_kw": {},
        }
        for h in range(hours)
    ]


def _solve(hours: int, soc: float, battery: dict, *, hold_index: int | None = None, hold: float | None = None):
    solved = _solve_milp_to_model(
        _matrix(hours), soc, battery, 6.5, False, [], {}, None, None, None, None, None, None, None, None,
        soc_hold_index=hold_index, soc_hold_percent=hold, inverter_params=[], pv_systems=[],
    )
    assert solved is not None
    return solved[0]


def _value(variable) -> float:
    return float(variable.varValue or 0.0)


def test_without_the_switch_the_plan_exports_past_the_empty_battery(monkeypatch) -> None:
    monkeypatch.delenv(VENDOR_MODE_ENV, raising=False)
    model = _solve(2, 10.0, _battery())
    assert _value(model.p_grid_sell[0]) == pytest.approx(SURPLUS_KW, abs=1e-6)
    assert _value(model.p_charge[0]) == pytest.approx(0.0, abs=1e-6)


def test_an_empty_battery_takes_the_surplus_first(monkeypatch) -> None:
    monkeypatch.setenv(VENDOR_MODE_ENV, "1")
    model = _solve(2, 10.0, _battery())
    assert _value(model.p_charge[0]) == pytest.approx(SURPLUS_KW, abs=1e-6)
    assert _value(model.p_grid_sell[0]) == pytest.approx(0.0, abs=1e-6)


def test_export_starts_when_the_battery_is_full(monkeypatch) -> None:
    monkeypatch.setenv(VENDOR_MODE_ENV, "1")
    model = _solve(2, 98.0, _battery(control="limits_only"))
    charge_kw = 0.2 / (0.95 * DEFAULT_DT_H)
    assert _value(model.p_charge[0]) == pytest.approx(charge_kw, abs=1e-6)
    assert _value(model.p_grid_sell[0]) == pytest.approx(SURPLUS_KW - charge_kw, abs=1e-6)
    assert _value(model.p_grid_sell[1]) == pytest.approx(SURPLUS_KW, abs=1e-6)


def test_surplus_above_the_charge_limit_may_be_exported(monkeypatch) -> None:
    monkeypatch.setenv(VENDOR_MODE_ENV, "1")
    model = _solve(1, 10.0, _battery(control="limits_only", max_power_kw=1.0))
    assert _value(model.p_charge[0]) == pytest.approx(1.0, abs=1e-6)
    assert _value(model.p_grid_sell[0]) == pytest.approx(SURPLUS_KW - 1.0, abs=1e-6)


def test_every_export_has_a_reason_the_book_can_follow(monkeypatch) -> None:
    monkeypatch.setenv(VENDOR_MODE_ENV, "1")
    battery = _battery()
    model = _solve(6, 50.0, battery)
    forced_min = FORCED_DISCHARGE_MARGIN * power_threshold_kw(battery["max_power_kw"])
    for t in range(6):
        if _value(model.p_grid_sell[t]) <= 1e-6:
            continue
        full = _value(model.e_batt[t]) >= 10.0 - 1e-6
        forced = _value(model.p_discharge[t]) >= forced_min - 1e-6
        assert full or forced, f"Slot {t} exportiert ohne Grund"


def test_slots_before_the_book_stay_free(monkeypatch) -> None:
    """The hold at SA₁ would be infeasible if the slot leading to it had to charge."""
    monkeypatch.setenv(VENDOR_MODE_ENV, "1")
    model = _solve(3, 10.0, _battery(), hold_index=0, hold=10.0)
    assert _value(model.p_grid_sell[0]) == pytest.approx(SURPLUS_KW, abs=1e-6)
    assert _value(model.p_charge[1]) == pytest.approx(SURPLUS_KW, abs=1e-6)


def test_two_batteries_are_refused() -> None:
    with pytest.raises(ValueError, match="einen Speicher"):
        add_vendor_mode_export_constraints(SimpleNamespace(ess_ids=["a", "b"]), [], [], first_slot=0)

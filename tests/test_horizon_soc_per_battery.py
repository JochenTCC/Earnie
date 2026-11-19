"""Horizon simulation with several house batteries: one SoC per battery in both paths.

Two batteries of different capacity, limits, power and efficiency; the plant SoC column is the
energy-weighted SoC of both, and the MILP's plan SoC (``model.e_batt``) is the plant's.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from optimizer import battery as bat
from optimizer.milp import milp_horizon_schedule, milp_optimizer
from optimizer.milp_horizon import plant_soc_percent
from optimizer.sim_chart_rows import COL_BATTERIE_AKTION, COL_SOC, ess_soc_column_name
from optimizer.sim_house_batteries import HouseBatteryControl, step_house_batteries

_NO_WEAR = {"battery_wear": {"enabled": False}}
_SMALL = {
    "id": "a",
    "label": "A",
    "battery_capacity_kwh": 5.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "max_charge_power_kw": 2.5,
    "max_discharge_power_kw": 2.5,
    "max_power_kw": 2.5,
    "efficiency": 0.95,
    "standby_power_kw": 0.0,
    "control": "full",
    **_NO_WEAR,
}
_LARGE = {
    "id": "b",
    "label": "B",
    "battery_capacity_kwh": 10.0,
    "min_soc": 20.0,
    "max_soc": 90.0,
    "max_charge_power_kw": 5.0,
    "max_discharge_power_kw": 5.0,
    "max_power_kw": 5.0,
    "efficiency": 0.90,
    "standby_power_kw": 0.0,
    "control": "full",
    **_NO_WEAR,
}
_START = {"a": 40.0, "b": 60.0}
_COL_A = ess_soc_column_name("A")
_COL_B = ess_soc_column_name("B")


def _batteries() -> list[dict]:
    return [dict(_SMALL), dict(_LARGE)]


def _matrix(n: int) -> list[dict]:
    """Cheap night, PV surplus at noon, expensive evening: charge, surplus and discharge slots."""
    start = datetime(2025, 6, 1, 10, 0)
    prices = [8.0, 8.0, 30.0, 30.0, 12.0, 12.0, 40.0, 40.0, 10.0, 10.0, 35.0, 35.0]
    pv = [0.0, 0.0, 6.0, 6.0, 4.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    rows = []
    for index in range(n):
        slot = start + timedelta(minutes=15 * index)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "expected_p_pv": pv[index % len(pv)],
                "expected_p_act": 1.5,
                "k_act": prices[index % len(prices)],
                "price_buy": prices[index % len(prices)],
                "k_push_act": 5.0,
            }
        )
    return rows


@pytest.fixture(autouse=True)
def _offline_climate(monkeypatch):
    from tests.fixtures.open_meteo_mock import install_open_meteo_climate_mock

    install_open_meteo_climate_mock(monkeypatch)


def _simulate(matrix: list[dict], commit_hours: int, **kwargs) -> list[dict]:
    from optimizer.simulation import simulate_horizon

    return simulate_horizon(
        matrix,
        _START["a"],
        battery_params=_batteries(),
        k_push=5.0,
        verbose=False,
        flexible_consumers=[],
        commit_hours=commit_hours,
        current_soc_by_id=dict(_START),
        **kwargs,
    )


def _assert_plant_column_is_weighted(rows: list[dict]) -> None:
    for row in rows:
        soc_a, soc_b = row[_COL_A], row[_COL_B]
        assert 10.0 - 0.05 <= soc_a <= 100.0 + 0.05
        assert 20.0 - 0.05 <= soc_b <= 90.0 + 0.05
        # Columns are rounded to 0.1 each, the plant column from the unrounded values.
        assert row[COL_SOC] == pytest.approx((5.0 * soc_a + 10.0 * soc_b) / 15.0, abs=0.1)


def test_open_loop_steps_each_battery_and_books_the_plant(monkeypatch):
    import optimizer.simulation as simulation

    schedules: list[list[dict]] = []
    real_schedule = simulation.milp_horizon_schedule

    def _capture(*args, **kwargs):
        schedule = real_schedule(*args, **kwargs)
        schedules.append(schedule)
        return schedule

    monkeypatch.setattr(simulation, "milp_horizon_schedule", _capture)
    matrix = _matrix(8)

    rows = _simulate(matrix, commit_hours=len(matrix))

    assert len(schedules) == 1
    assert rows[0][_COL_A] == pytest.approx(40.0)
    assert rows[0][_COL_B] == pytest.approx(60.0)
    assert rows[0][COL_SOC] == pytest.approx((5.0 * 40.0 + 10.0 * 60.0) / 15.0, abs=0.05)
    _assert_plant_column_is_weighted(rows)
    for slot in schedules[0]:
        planned_plant = plant_soc_percent(_batteries(), slot["planned_soc_by_ess"])
        assert slot["planned_soc_percent"] == pytest.approx(planned_plant, abs=0.1)
    # The first two slots discharge the small battery alone (load 1.5 kW, no PV): Automatik
    # gives the residual to it first, so each battery follows its own plan.
    for index in (0, 1):
        planned = schedules[0][index]["planned_soc_by_ess"]
        assert rows[index + 1][_COL_A] == pytest.approx(planned["a"], abs=0.1)
        assert rows[index + 1][_COL_B] == pytest.approx(planned["b"], abs=0.1)
        assert rows[index + 1][COL_SOC] == pytest.approx(
            schedules[0][index]["planned_soc_percent"], abs=0.1
        )
    # Both batteries move: the small one alone could not carry the plan.
    assert any(abs(r[_COL_A] - rows[0][_COL_A]) > 1.0 for r in rows)
    assert any(abs(r[_COL_B] - rows[0][_COL_B]) > 1.0 for r in rows)
    end = rows[-1]["_horizon_end_soc"]
    assert 15.0 <= end <= 93.4


def test_slot_resolve_carries_each_batterys_soc(monkeypatch):
    import optimizer.simulation as simulation

    calls: list[dict] = []
    real_optimizer = simulation.milp_optimizer

    def _capture(*args, **kwargs):
        calls.append(
            {"current_soc": args[2], "soc_by_id": dict(kwargs["current_soc_by_id"])}
        )
        assert isinstance(kwargs["battery_params"], list)
        return real_optimizer(*args, **kwargs)

    monkeypatch.setattr(simulation, "milp_optimizer", _capture)
    matrix = _matrix(6)

    rows = _simulate(matrix, commit_hours=1)

    assert len(calls) == len(matrix)
    _assert_plant_column_is_weighted(rows)
    for index, call in enumerate(calls):
        # Each solve starts at the simulated SoC of both batteries (columns rounded to 0.1).
        assert call["soc_by_id"]["a"] == pytest.approx(rows[index][_COL_A], abs=0.05)
        assert call["soc_by_id"]["b"] == pytest.approx(rows[index][_COL_B], abs=0.05)
        assert call["current_soc"] == pytest.approx(rows[index][COL_SOC], abs=0.05)
    assert calls[0]["soc_by_id"] == _START


def test_slot_resolve_first_slot_equals_open_loop():
    matrix = _matrix(6)

    # Without the terminal anchor (K=1 sets it only in the last solve) slot 0 solves the same MILP.
    open_loop = _simulate(matrix, commit_hours=len(matrix), disable_horizon_soc_anchor=True)
    resolve = _simulate(matrix, commit_hours=1, disable_horizon_soc_anchor=True)

    assert resolve[0][COL_BATTERIE_AKTION] == pytest.approx(open_loop[0][COL_BATTERIE_AKTION])
    assert resolve[1][_COL_A] == pytest.approx(open_loop[1][_COL_A])
    assert resolve[1][_COL_B] == pytest.approx(open_loop[1][_COL_B])


def test_open_loop_refill_gets_the_simulated_soc_map(monkeypatch):
    import optimizer.simulation as simulation

    maps: list[dict] = []
    real_schedule = simulation.milp_horizon_schedule

    def _capture(*args, **kwargs):
        maps.append({"current_soc": args[1], "soc_by_id": dict(kwargs["current_soc_by_id"])})
        return real_schedule(*args, **kwargs)

    monkeypatch.setattr(simulation, "milp_horizon_schedule", _capture)
    matrix = _matrix(12)

    # 2 h = 8 quarter-hour slots per solve: the second solve starts inside the matrix.
    rows = _simulate(matrix, commit_hours=2)

    assert len(maps) == 2
    assert maps[0]["soc_by_id"] == _START
    assert maps[1]["soc_by_id"]["a"] == pytest.approx(rows[8][_COL_A], abs=0.05)
    assert maps[1]["soc_by_id"]["b"] == pytest.approx(rows[8][_COL_B], abs=0.05)
    assert maps[1]["soc_by_id"] != _START
    assert maps[1]["current_soc"] == pytest.approx(rows[8][COL_SOC], abs=0.05)


def test_single_battery_refill_gets_the_simulated_soc(monkeypatch):
    import optimizer.simulation as simulation

    maps: list[dict | None] = []
    real_schedule = simulation.milp_horizon_schedule

    def _capture(*args, **kwargs):
        maps.append(kwargs["current_soc_by_id"])
        return real_schedule(*args, **kwargs)

    monkeypatch.setattr(simulation, "milp_horizon_schedule", _capture)
    from optimizer.simulation import simulate_horizon

    rows = simulate_horizon(
        _matrix(12),
        40.0,
        battery_params=[dict(_SMALL)],
        k_push=5.0,
        verbose=False,
        flexible_consumers=[],
        commit_hours=2,
        current_soc_by_id={"a": 40.0},
    )

    assert maps[0] == {"a": 40.0}
    # The MILP takes a single battery's start from the map: the refill must find the simulation.
    assert maps[1]["a"] == pytest.approx(rows[8][COL_SOC], abs=0.05)


def test_automatik_batteries_share_the_residual_in_order():
    controls = (
        HouseBatteryControl("a", bat.MODE_AUTOMATIK, 0.0),
        HouseBatteryControl("b", bat.MODE_AUTOMATIK, 0.0),
    )

    end, total = step_house_batteries(
        controls, _batteries(), dict(_START), pv=5.5, con=1.5, total_flex=0.0
    )

    # 4 kW surplus: the first battery takes its 2.5 kW, the second the rest.
    assert total == pytest.approx(4.0)
    assert end["a"] == pytest.approx(40.0 + 2.5 * 0.95 * 0.25 / 5.0 * 100.0)
    assert end["b"] == pytest.approx(60.0 + 1.5 * 0.90 * 0.25 / 10.0 * 100.0)


def test_forced_battery_runs_apart_from_the_residual():
    controls = (
        HouseBatteryControl("a", bat.MODE_ZWANGS_LADEN, 2.0),
        HouseBatteryControl("b", bat.MODE_AUTOMATIK, 0.0),
    )

    end, total = step_house_batteries(
        controls, _batteries(), dict(_START), pv=0.0, con=3.0, total_flex=0.0
    )

    # a charges 2 kW from the grid; b covers the house load of 3 kW.
    assert total == pytest.approx(2.0 - 3.0)
    assert end["a"] == pytest.approx(40.0 + 2.0 * 0.95 * 0.25 / 5.0 * 100.0)
    assert end["b"] == pytest.approx(60.0 - 3.0 / 0.90 * 0.25 / 10.0 * 100.0)


def test_soc_limits_pass_the_rest_to_the_next_battery():
    controls = (
        HouseBatteryControl("a", bat.MODE_AUTOMATIK, 0.0),
        HouseBatteryControl("b", bat.MODE_AUTOMATIK, 0.0),
    )

    end, total = step_house_batteries(
        controls, _batteries(), {"a": 100.0, "b": 60.0}, pv=4.5, con=1.5, total_flex=0.0
    )

    # a is full: the whole surplus of 3 kW goes to b.
    assert end["a"] == pytest.approx(100.0)
    assert total == pytest.approx(3.0)
    assert end["b"] == pytest.approx(60.0 + 3.0 * 0.90 * 0.25 / 10.0 * 100.0)


def test_hold_slot_sets_the_plant_soc_exactly():
    from optimizer.sim_horizon_types import _HorizonOptions
    from optimizer.simulation import _house_soc_after_hold_slot

    options = _HorizonOptions(
        k_push=5.0,
        verbose=False,
        commit_hours=8,
        flex_book_hours=None,
        flex_book_start=0,
        sunrise_soc_min_index=None,
        soc_hold_index=3,
        soc_hold_percent=55.0,
        import_caps=None,
    )
    socs = {"a": 41.0, "b": 61.0}

    assert _house_soc_after_hold_slot(options, 2, _batteries(), socs, None) is socs
    held = _house_soc_after_hold_slot(options, 3, _batteries(), socs, {"a": 30.0, "b": 70.0})

    assert plant_soc_percent(_batteries(), held) == pytest.approx(55.0)
    # The plan's split stays; both move by the same SoC difference.
    assert held["b"] - held["a"] == pytest.approx(40.0)


def test_milp_plan_soc_is_the_plant_soc():
    matrix = _matrix(6)

    schedule = milp_horizon_schedule(
        matrix,
        40.0,
        battery_params=_batteries(),
        k_push=5.0,
        consumers=[],
        current_soc_by_id=dict(_START),
    )

    for slot in schedule:
        assert set(slot["planned_soc_by_ess"]) == {"a", "b"}
        assert slot["planned_soc_percent"] == pytest.approx(
            plant_soc_percent(_batteries(), slot["planned_soc_by_ess"]), abs=0.1
        )


def test_milp_optimizer_controls_refer_to_the_plant():
    matrix = _matrix(6)

    def _solve(current_soc: float) -> tuple:
        return milp_optimizer(
            matrix,
            matrix[0]["hour"],
            current_soc,
            battery_params=_batteries(),
            k_push=5.0,
            verbose=False,
            consumers=[],
            current_soc_by_id=dict(_START),
        )

    first = _solve(40.0)
    other = _solve(75.0)

    plan = first[5]
    assert set(plan["planned_soc_by_ess"]) == {"a", "b"}
    # With several house batteries the plan's SoC comes from the map, not from current_soc.
    assert first[:3] == other[:3]
    # Slot 0 is cheap: the plant charges from the grid towards the plant's planned SoC.
    mode, target_power, target_soc = first[:3]
    planned_plant = plant_soc_percent(_batteries(), plan["planned_soc_by_ess"])
    if mode == bat.MODE_ZWANGS_LADEN:
        assert target_soc == pytest.approx(planned_plant, abs=0.15)
        assert target_power <= 7.5 + 1e-9


def test_history_soc_is_the_plant_soc():
    from runtime_store.history_chart_rows import history_soc_percent

    entry = {"soc_percent": 40.0, "soc_percent_by_ess": {"a": 40.0, "b": 70.0, "ps_virtual": 5.0}}

    assert history_soc_percent(entry, [dict(_SMALL)]) == 40.0
    assert history_soc_percent(entry, _batteries()) == pytest.approx(60.0)
    assert math.isnan(history_soc_percent({"soc_percent": 40.0}, _batteries()))
    assert math.isnan(
        history_soc_percent({"soc_percent": 40.0, "soc_percent_by_ess": {"a": 40.0}}, _batteries())
    )

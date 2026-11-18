"""MILP battery wear per house battery: each battery's own battery_wear on its own throughput."""
from __future__ import annotations

import pytest

from house_config.entity_resolution import battery_params_from_planning
from optimizer.milp import milp_horizon_schedule

COSTLY_WEAR = {
    "enabled": True,
    "replacement_cost_euro": 10000.0,
    "expected_cycles": 1000.0,
    "cycle_cost_fraction": 1.0,
}
NO_WEAR = {"enabled": False}


def _battery(ess_id: str, wear: dict | None) -> dict:
    bat = {
        "id": ess_id,
        "label": ess_id,
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_charge_power_kw": 2.5,
        "max_discharge_power_kw": 2.5,
        "max_power_kw": 2.5,
        "efficiency": 0.97,
        "standby_power_kw": 0.0,
        "control": "full",
    }
    if wear is not None:
        bat["battery_wear"] = dict(wear)
    return bat


def _cheap_then_expensive(slots: int = 24) -> list[dict]:
    """Cheap grid first, expensive later: worth cycling unless wear eats the spread."""
    return [
        {
            "hour": t // 4,
            "expected_p_pv": 0.0,
            "expected_p_act": 2.0,
            "k_act": 5.0 if t < slots // 2 else 40.0,
            "k_push_act": 0.0,
        }
        for t in range(slots)
    ]


def _schedule(batteries: list[dict]) -> list[dict]:
    return milp_horizon_schedule(
        _cheap_then_expensive(),
        current_soc=10.0,
        battery_params=batteries,
        k_push=0.0,
        verbose=False,
        consumers=[],
        current_soc_by_id={b["id"]: 10.0 for b in batteries},
    )


def _max_soc(schedule: list[dict], ess_id: str) -> float:
    return max(float(slot["planned_soc_by_ess"][ess_id]) for slot in schedule)


def test_each_battery_is_priced_with_its_own_wear():
    # The first battery's wear (200 ct/kWh) must not price the second, which has none.
    schedule = _schedule([_battery("a", COSTLY_WEAR), _battery("b", NO_WEAR)])
    assert _max_soc(schedule, "a") == pytest.approx(10.0, abs=1e-3)
    assert _max_soc(schedule, "b") > 50.0


def test_costly_wear_on_the_second_battery_keeps_it_idle():
    schedule = _schedule([_battery("a", NO_WEAR), _battery("b", COSTLY_WEAR)])
    assert _max_soc(schedule, "a") > 50.0
    assert _max_soc(schedule, "b") == pytest.approx(10.0, abs=1e-3)


def test_several_batteries_need_their_own_wear():
    with pytest.raises(ValueError, match="battery_wear fehlt"):
        _schedule([_battery("a", NO_WEAR), _battery("b", None)])


def test_planning_params_carry_the_battery_wear():
    entry = {
        "id": "a",
        "battery_capacity_kwh": 5.0,
        "battery_min_soc": 10.0,
        "battery_max_soc": 100.0,
        "battery_max_charge_power_kw": 2.5,
        "battery_max_discharge_power_kw": 2.5,
        "battery_max_power_kw": 2.5,
        "battery_efficiency": 0.97,
        "inverter_efficiency": 1.0,
        "battery_wear": dict(COSTLY_WEAR),
    }
    assert battery_params_from_planning(entry)["battery_wear"] == COSTLY_WEAR
    assert "battery_wear" not in battery_params_from_planning({**entry, "battery_wear": None})

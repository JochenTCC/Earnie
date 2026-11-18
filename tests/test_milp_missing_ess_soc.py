"""Several house batteries each need their own SoC: live filter and MILP start energy fail loud."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from integrations.ehal_live_soc import filter_planning_batteries_with_soc
from optimizer.milp import milp_horizon_schedule
from optimizer.milp_horizon import _initial_energy_by_ess

NO_WEAR = {"enabled": False}


def _battery(ess_id: str, capacity_kwh: float = 5.0) -> dict:
    return {
        "id": ess_id,
        "label": ess_id,
        "battery_capacity_kwh": capacity_kwh,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_charge_power_kw": 2.5,
        "max_discharge_power_kw": 2.5,
        "max_power_kw": 2.5,
        "efficiency": 0.97,
        "standby_power_kw": 0.0,
        "control": "full",
        "battery_wear": dict(NO_WEAR),
    }


def _matrix(slots: int = 8) -> list[dict]:
    return [
        {
            "hour": t // 4,
            "expected_p_pv": 0.0,
            "expected_p_act": 1.0,
            "k_act": 30.0,
            "k_push_act": 0.0,
        }
        for t in range(slots)
    ]


def _schedule(batteries: list[dict], soc_by_id: dict[str, float] | None) -> list[dict]:
    return milp_horizon_schedule(
        _matrix(),
        current_soc=60.0,
        battery_params=batteries,
        k_push=0.0,
        verbose=False,
        consumers=[],
        current_soc_by_id=soc_by_id,
    )


def _grid_vars(batteries: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        ess_ids=[b["id"] for b in batteries],
        battery_params_by_id={b["id"]: b for b in batteries},
    )


def test_second_battery_without_soc_raises_naming_it_and_present_ids():
    with pytest.raises(ValueError, match=r"MILP: Start-SoC fehlt") as exc:
        _schedule([_battery("a"), _battery("b")], {"a": 50.0})
    message = str(exc.value)
    assert "['b']" in message
    assert "vorhanden: ['a']" in message


def test_several_batteries_without_any_soc_map_raise_for_all():
    # current_soc (the primary's) must not stand in for the batteries' own SoC.
    with pytest.raises(ValueError, match=r"MILP: Start-SoC fehlt") as exc:
        _schedule([_battery("a"), _battery("b")], None)
    assert "['a', 'b']" in str(exc.value)
    assert "vorhanden: []" in str(exc.value)


def test_several_batteries_with_own_soc_plan():
    schedule = _schedule([_battery("a"), _battery("b")], {"a": 50.0, "b": 80.0})
    assert len(schedule) == len(_matrix())


def test_single_battery_without_soc_map_uses_current_soc():
    energy = _initial_energy_by_ess(_grid_vars([_battery("a", 10.0)]), 60.0, None)
    assert energy == {"a": pytest.approx(6.0)}


def test_single_battery_prefers_its_own_soc():
    energy = _initial_energy_by_ess(_grid_vars([_battery("a", 10.0)]), 60.0, {"a": 30.0})
    assert energy == {"a": pytest.approx(3.0)}


def test_several_batteries_start_with_their_own_energy():
    batteries = [_battery("a", 10.0), _battery("b", 4.0)]
    energy = _initial_energy_by_ess(_grid_vars(batteries), 60.0, {"a": 50.0, "b": 25.0})
    assert energy == {"a": pytest.approx(5.0), "b": pytest.approx(1.0)}


def test_battery_without_capacity_needs_no_soc():
    # It stores nothing, so its SoC does not change the plan (as in plant_soc_percent).
    batteries = [_battery("a", 10.0), _battery("empty", 0.0)]
    energy = _initial_energy_by_ess(_grid_vars(batteries), 60.0, {"a": 50.0})
    assert energy == {"a": pytest.approx(5.0), "empty": 0.0}


def test_filter_keeps_a_single_battery_without_own_soc():
    # One battery plans with the primary SoC (read_ess_soc), as before.
    batteries = [_battery("a")]
    assert filter_planning_batteries_with_soc(batteries, {"other": 40.0}) is batteries


def test_filter_drops_only_the_battery_without_own_soc():
    kept = filter_planning_batteries_with_soc([_battery("a"), _battery("b")], {"b": 40.0})
    assert [b["id"] for b in kept] == ["b"]


def test_filter_raises_when_no_battery_has_own_soc():
    with pytest.raises(ValueError, match=r"keine hat einen eigenen SoC") as exc:
        filter_planning_batteries_with_soc([_battery("a"), _battery("b")], {"x": 40.0})
    assert "['a', 'b']" in str(exc.value)
    assert "['x']" in str(exc.value)


def test_filter_raises_for_several_batteries_without_soc_map():
    with pytest.raises(ValueError, match=r"keine hat einen eigenen SoC"):
        filter_planning_batteries_with_soc([_battery("a"), _battery("b")], None)


def test_filter_raises_for_a_battery_without_id_among_several():
    batteries = [_battery("a"), {**_battery("x"), "id": ""}]
    with pytest.raises(ValueError, match=r"eine Batterie hat keine id"):
        filter_planning_batteries_with_soc(batteries, {"a": 50.0, "x": 40.0})


def test_battery_without_id_never_matches_a_soc_key():
    # The model names a battery without id ``ess_<index>``; a SoC under another key is no match.
    batteries = [_battery("a"), {**_battery("x"), "id": ""}]
    with pytest.raises(ValueError, match=r"\['ess_1'\]"):
        _schedule(batteries, {"a": 50.0, "x": 40.0})

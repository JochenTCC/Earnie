"""Inverter P3: MILP AC clipping, DC cap, island PV outside house balance."""
from __future__ import annotations

import pulp
import pytest

from optimizer.milp import _add_milp_objective, _build_milp_model, milp_optimizer
from optimizer.milp_inverter import (
    apply_dc_pv_cap,
    house_balance_pv_kw,
    raw_pv_kw_by_inverter,
)


def _battery(*, bat_id: str = "bat", inv_id: str = "wr_main", max_kw: float = 5.0) -> dict:
    return {
        "id": bat_id,
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_charge_power_kw": max_kw,
        "max_discharge_power_kw": max_kw,
        "max_power_kw": max_kw,
        "efficiency": 0.95,
        "standby_power_kw": 0.0,
        "control": "full",
        "inverter_id": inv_id,
        "ac_connection": "grid_tied",
    }


def _hybrid_inv(*, inv_id: str = "wr_main", max_ac: float | None = None, **extra) -> dict:
    # efficiency=1.0 so clip/topology tests isolate AC caps from η_inv.
    inv = {
        "id": inv_id,
        "label": inv_id,
        "type": "hybrid",
        "ac_connection": "grid_tied",
        "control": "full",
        "efficiency": 1.0,
    }
    if max_ac is not None:
        inv["max_ac_power_kw"] = max_ac
    inv.update(extra)
    return inv


def _pv(*, pv_id: str = "roof", inv_id: str = "wr_main") -> dict:
    return {
        "id": pv_id,
        "label": pv_id,
        "pv_kwp": 10.0,
        "pv_tilt": 30.0,
        "pv_azimuth": 180.0,
        "inverter_id": inv_id,
    }


def _matrix(*, p_pv: float, p_act: float = 0.5, k_act: float = 40.0, hours: int = 1) -> list[dict]:
    return [
        {
            "hour": h,
            "expected_p_pv": p_pv,
            "expected_p_act": p_act,
            "k_act": k_act,
            "k_push_act": 5.0,
            "expected_p_pv_by_system": {"roof": p_pv},
        }
        for h in range(hours)
    ]


def _solve_discharge(
    *,
    max_ac: float | None,
    p_pv: float = 4.0,
    p_act: float = 8.0,
    soc: float = 90.0,
) -> float:
    """Deficit hour: PV + discharge covers load; clipping binds on shared AC."""
    inv = _hybrid_inv(max_ac=max_ac)
    matrix = _matrix(p_pv=p_pv, p_act=p_act)
    model = _build_milp_model(
        matrix,
        1,
        _battery(),
        soc,
        [],
        0.0,
        {},
        {},
        inverter_params=[inv],
        pv_systems=[_pv()],
    )
    _add_milp_objective(
        model, matrix, fallback_k_push=5.0, ev_milp_params_by_id={}, wear_cent_per_kwh=0.0
    )
    status = pulp.LpStatus[
        model.prob.solve(pulp.PULP_CBC_CMD(msg=False, gapRel=0.05))
    ]
    assert status == "Optimal"
    return float(model.p_discharge[0].varValue or 0.0)


def test_ac_clipping_binds_when_max_ac_power_kw_set():
    # PV 4 + discharge; max_ac 5 → discharge ≤ 1 (cannot cover full 4 kW deficit).
    discharge = _solve_discharge(max_ac=5.0)
    assert discharge <= 1.0 + 1e-5


def test_no_ac_clip_when_max_ac_power_kw_absent():
    # Same deficit; without cap discharge covers residual (~4 kW).
    discharge = _solve_discharge(max_ac=None)
    assert discharge >= 3.5


def test_dc_cap_limits_house_pv():
    inv = _hybrid_inv(max_pv_input_kw=2.0)
    row = {
        "expected_p_pv": 8.0,
        "expected_p_pv_by_system": {"roof": 8.0},
    }
    assert apply_dc_pv_cap(8.0, inv) == pytest.approx(2.0)
    assert house_balance_pv_kw(
        row, inverters=[inv], pv_systems=[_pv()]
    ) == pytest.approx(2.0)


def test_island_pv_excluded_from_house_balance():
    inverters = [
        _hybrid_inv(inv_id="wr_main"),
        {
            "id": "wr_island",
            "label": "Island",
            "type": "hybrid",
            "ac_connection": "island",
            "control": "full",
            "efficiency": 1.0,
        },
    ]
    pvs = [
        _pv(pv_id="roof", inv_id="wr_main"),
        _pv(pv_id="balkon", inv_id="wr_island"),
    ]
    row = {
        "expected_p_pv": 10.0,
        "expected_p_pv_by_system": {"roof": 3.0, "balkon": 7.0},
    }
    assert house_balance_pv_kw(
        row, inverters=inverters, pv_systems=pvs
    ) == pytest.approx(3.0)
    raw = raw_pv_kw_by_inverter(row, inverters=inverters, pv_systems=pvs)
    assert raw["wr_island"] == pytest.approx(7.0)


def test_island_battery_excluded_from_milp_ess():
    batteries = [
        _battery(bat_id="house", inv_id="wr_main"),
        {
            **_battery(bat_id="eco", inv_id="wr_island", max_kw=1.0),
            "ac_connection": "island",
        },
    ]
    inverters = [
        _hybrid_inv(inv_id="wr_main"),
        {
            "id": "wr_island",
            "label": "Island",
            "type": "hybrid",
            "ac_connection": "island",
            "control": "full",
            "efficiency": 1.0,
        },
    ]
    model = _build_milp_model(
        _matrix(p_pv=1.0),
        1,
        batteries,
        50.0,
        [],
        0.0,
        {},
        {},
        inverter_params=inverters,
        pv_systems=[_pv()],
    )
    assert model.ess_ids == ["house"]


def test_max_ac_charge_kw_caps_grid_charge():
    inv = _hybrid_inv(max_ac_charge_kw=0.5)
    # Night: no PV, high buy price later — force cheap slot charge.
    matrix = [
        {
            "hour": 0,
            "expected_p_pv": 0.0,
            "expected_p_act": 0.0,
            "k_act": 5.0,
            "k_push_act": 1.0,
            "expected_p_pv_by_system": {"roof": 0.0},
        },
        {
            "hour": 1,
            "expected_p_pv": 0.0,
            "expected_p_act": 4.0,
            "k_act": 50.0,
            "k_push_act": 1.0,
            "expected_p_pv_by_system": {"roof": 0.0},
        },
    ]
    _, _, _, _, _, plan, _ = milp_optimizer(
        matrix,
        current_hour=0,
        current_soc=20.0,
        battery_params=_battery(max_kw=5.0),
        k_push=1.0,
        verbose=False,
        consumers=[],
        inverter_params=[inv],
        pv_systems=[_pv()],
    )
    assert float(plan.get("p_charge") or 0.0) <= 0.5 + 1e-5


def test_absent_inverter_topology_unchanged_build():
    model = _build_milp_model(
        _matrix(p_pv=3.0),
        1,
        _battery(),
        50.0,
        [],
        0.0,
        {},
        {},
    )
    assert model.ess_ids == ["bat"]

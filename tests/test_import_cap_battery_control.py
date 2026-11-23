"""Import cap: the battery follows the plan's partial discharge and charge (Bugfix, 2.8).

Under an import limit the plan spreads the battery over the expensive slots. Executed as plain
Automatik the battery covered the whole deficit, was empty after a few slots, and the later slots
went over the limit without a cause. A forced charge chasing the plan's SoC went over it too.
"""
from __future__ import annotations

import pytest

from optimizer import battery as bat

_BATTERY = {
    "id": "akku",
    "min_soc": 10.0,
    "max_soc": 100.0,
    "max_power_kw": 2.5,
    "battery_capacity_kwh": 10.0,
    "efficiency": 0.95,
    "control": "full",
}


def _row(load_kw: float, pv_kw: float = 0.0) -> dict:
    return {"expected_p_pv": pv_kw, "expected_p_act": load_kw}


def _discharge_plan(**extra) -> dict:
    # 13.01. 08:00 of the winter smoke: 3.08 kW load, 2.2 kW from the grid, 0.88 kW battery.
    return {"p_charge": 0.0, "p_discharge": 0.88, "p_grid_buy": 2.2, "p_grid_sell": 0.0, **extra}


def test_partial_discharge_under_a_limit_caps_automatik_at_the_plan() -> None:
    plan = _discharge_plan(import_cap_limit_kw=2.2, import_cap_slack_kw=0.0)
    mode, _, _ = bat.derive_control_from_milp_plan(
        plan, _row(3.08), 0.0, 60.0, 57.8, _BATTERY, dt_h=0.25
    )
    assert mode == bat.MODE_AUTOMATIK
    cap = bat.import_cap_discharge_cap_kw(plan, _row(3.08), 0.0, _BATTERY)
    assert cap == pytest.approx(0.88)
    action = bat.battery_plan_kw_from_control(
        mode, 0.0, 0.0, 3.08, 0.0, 2.5, automatik_discharge_cap_kw=cap
    )
    assert action == pytest.approx(-0.88)


def test_load_above_forecast_still_keeps_the_planned_import() -> None:
    plan = _discharge_plan(import_cap_limit_kw=2.2, import_cap_slack_kw=0.0)
    assert bat.import_cap_discharge_cap_kw(plan, _row(3.5), 0.0, _BATTERY) == pytest.approx(1.3)


def test_planned_slack_is_import_the_plan_allows() -> None:
    plan = _discharge_plan(import_cap_limit_kw=2.0, import_cap_slack_kw=0.3)
    assert bat.import_cap_discharge_cap_kw(plan, _row(3.5), 0.0, _BATTERY) == pytest.approx(1.2)


def test_without_a_limit_there_is_no_cap() -> None:
    assert bat.import_cap_discharge_cap_kw(_discharge_plan(), _row(3.08), 0.0, _BATTERY) is None


def test_forced_charge_stays_within_the_limit() -> None:
    # 14.01. 05:45: the plan charges 2.119 kW with 2.2 kW import; the SoC chase asked for 2.4 kW.
    plan = {
        "p_charge": 2.119,
        "p_discharge": 0.0,
        "p_grid_buy": 2.2,
        "p_grid_sell": 0.0,
        "import_cap_limit_kw": 2.2,
        "import_cap_slack_kw": 0.0,
    }
    mode, power, _ = bat.derive_control_from_milp_plan(
        plan, _row(0.08), 0.0, 50.0, 55.7, _BATTERY, dt_h=0.25
    )
    assert mode == bat.MODE_ZWANGS_LADEN
    assert power == pytest.approx(2.12)


def test_forced_charge_never_drops_below_the_plan() -> None:
    plan = {
        "p_charge": 2.3,
        "p_discharge": 0.0,
        "p_grid_buy": 2.4,
        "p_grid_sell": 0.0,
        "import_cap_limit_kw": 2.2,
        "import_cap_slack_kw": 0.2,
    }
    _, power, _ = bat.derive_control_from_milp_plan(
        plan, _row(0.5), 0.0, 50.0, 55.7, _BATTERY, dt_h=0.25
    )
    assert power == pytest.approx(2.3)


def test_forced_charge_without_a_limit_is_unchanged() -> None:
    plan = {"p_charge": 2.119, "p_discharge": 0.0, "p_grid_buy": 2.2, "p_grid_sell": 0.0}
    _, power, _ = bat.derive_control_from_milp_plan(
        plan, _row(0.08), 0.0, 50.0, 55.7, _BATTERY, dt_h=0.25
    )
    assert power == pytest.approx(2.4)


def test_live_writes_the_plan_discharge_as_automatik_limit(monkeypatch) -> None:
    import main as main_module
    from optimizer.run_trigger import TRIGGER_QUARTER_HOUR
    from tests.main_run_harness import patch_main_run

    patch_main_run(monkeypatch, silent=False)
    plan = _discharge_plan(import_cap_limit_kw=2.2, import_cap_slack_kw=0.0)
    monkeypatch.setattr(
        main_module.optimizer,
        "milp_optimizer",
        lambda *a, **k: (bat.MODE_AUTOMATIK, 0.0, 99.0, {}, {}, plan, {}),
    )
    caps: list[float | None] = []
    monkeypatch.setattr(main_module.run_state, "save_run_state", lambda _payload: None)
    monkeypatch.setattr(
        main_module.ehal_live,
        "write_huawei_modbus_states",
        lambda *a, **k: caps.append(k.get("automatik_discharge_cap_kw")) or [],
    )
    monkeypatch.setattr(main_module.ehal_live, "write_flexible_consumer_states", lambda *a, **k: [])

    main_module.main(run_trigger=TRIGGER_QUARTER_HOUR)

    assert caps == [pytest.approx(0.88)]

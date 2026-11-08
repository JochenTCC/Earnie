"""Import cap in the MILP: limit per slot, slack, ratchet, month boundary, model unchanged without it."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from house_config.import_cap import ImportCap
from optimizer import cbc_solver
from optimizer.import_power_limit import ImportCaps, import_caps_for_slots
from optimizer.milp import _solve_milp_to_model, milp_horizon_schedule, milp_optimizer

START = datetime(2027, 1, 12, 16, 0)
TOLERANCE = 1e-5


def _battery(**overrides) -> dict:
    return {
        "battery_capacity_kwh": 10.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 5.0,
        "efficiency": 0.95,
        "control": "full",
        **overrides,
    }


def _ev() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 11.0,
        "min_power_kw": 4.2,
        "min_on_quarterhours": 1,
        "ehal_bindings": {"set_evcs_max_current": "x"},
    }


def _rows(loads: list[float], *, start: datetime = START, price: float = 20.0) -> list[dict]:
    rows = []
    for t, load in enumerate(loads):
        slot = start + timedelta(minutes=15 * t)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "expected_p_pv": 0.0,
                "expected_p_act": load,
                "k_act": price,
                "k_push_act": 5.0,
                "expected_flex_kw": {},
            }
        )
    return rows


def _caps(rows: list[dict], limit: float, month: str = "2027-01") -> ImportCaps:
    return ImportCaps(tuple(limit for _ in rows), tuple(month for _ in rows))


def _solve(rows, caps, *, battery=None, soc=50.0, consumers=None, remaining=None):
    solved = _solve_milp_to_model(
        rows, soc, battery or _battery(), 5.0, False, consumers or [], remaining or {},
        None, None, {}, None, None, None, None, None, import_caps=caps,
    )
    assert solved is not None
    return solved[0]


def _buy(model) -> list[float]:
    return [float(var.varValue or 0.0) for var in model.p_grid_buy]


def _slack(model) -> list[float]:
    return [float(var.varValue or 0.0) if var is not None else 0.0 for var in model.import_cap_slack]


# --- limits per slot ---------------------------------------------------------------------


def _slots(*moments: datetime) -> list[datetime]:
    return list(moments)


CAP = ImportCap(5.0, 0.5)
JAN = datetime(2027, 1, 31, 23, 45)
FEB = datetime(2027, 2, 1, 0, 0)


def test_limit_is_the_cap_less_the_margin():
    caps = import_caps_for_slots(_slots(JAN), CAP, lambda _month: True, {})
    assert caps == ImportCaps((4.5,), ("2027-01",))


def test_reached_peak_lifts_the_limit():
    caps = import_caps_for_slots(_slots(JAN), CAP, lambda _month: True, {"2027-01": 7.0})
    assert caps.limits_kw == (6.5,)


def test_peak_below_the_cap_changes_nothing():
    caps = import_caps_for_slots(_slots(JAN), CAP, lambda _month: True, {"2027-01": 3.0})
    assert caps.limits_kw == (4.5,)


def test_next_month_starts_without_the_peak():
    caps = import_caps_for_slots(_slots(JAN, FEB), CAP, lambda _month: True, {"2027-01": 7.0})
    assert caps == ImportCaps((6.5, 4.5), ("2027-01", "2027-02"))


def test_inactive_month_has_no_limit():
    caps = import_caps_for_slots(_slots(JAN, FEB), CAP, lambda month: month == date(2027, 2, 1), {})
    assert caps == ImportCaps((None, 4.5), (None, "2027-02"))


def test_no_active_month_gives_no_caps():
    assert import_caps_for_slots(_slots(JAN), CAP, lambda _month: False, {}) is None


# --- the model ---------------------------------------------------------------------------


def test_without_caps_the_model_has_nothing_new():
    rows = _rows([1.0] * 8)
    model = _solve(rows, None)
    assert model.import_cap_slack is None
    assert not [name for name in model.prob.variablesDict() if name.startswith("import_cap")]
    assert not [name for name in model.prob.constraints if name.startswith("import_cap")]


def test_battery_holds_the_cap_with_no_slack():
    rows = _rows([6.0] * 4 + [0.5] * 4)
    model = _solve(rows, _caps(rows, 3.0))
    assert max(_buy(model)) <= 3.0 + TOLERANCE
    assert max(_slack(model)) <= TOLERANCE


def test_without_cap_the_same_window_imports_more():
    """The battery starts at its minimum, so without a cap nothing makes the plan pre-charge it."""
    rows = _rows([6.0] * 4 + [0.5] * 4)
    assert max(_buy(_solve(rows, None, soc=10.0))) > 3.0


def test_ev_moves_away_from_the_load_peak():
    rows = _rows([3.0] * 4 + [0.5] * 12)
    model = _solve(
        rows,
        _caps(rows, 5.5),
        soc=10.0,
        consumers=[_ev()],
        remaining={"eauto": 5.0},
    )
    assert max(_buy(model)) <= 5.5 + TOLERANCE
    assert max(_slack(model)) <= TOLERANCE


def test_cap_that_cannot_hold_stays_solvable_and_names_the_slots():
    rows = _rows([0.5, 9.0, 0.5, 0.5])
    model = _solve(rows, _caps(rows, 2.0), battery=_battery(max_power_kw=1.0), soc=100.0)
    slack = _slack(model)
    assert slack[1] == pytest.approx(9.0 - 1.0 - 2.0, abs=1e-3)  # 1 kW battery, 2 kW limit
    assert slack[0] <= TOLERANCE


def test_ev_deadline_beats_the_cap_and_the_slack_shows_it():
    rows = _rows([0.5] * 4)
    model = _solve(
        rows,
        _caps(rows, 2.0),
        battery=_battery(battery_capacity_kwh=0.0, max_power_kw=0.0),
        consumers=[_ev()],
        remaining={"eauto": 8.0},
    )
    assert sum(_buy(model)) * 0.25 == pytest.approx(0.5 * 4 * 0.25 + 8.0, abs=0.01)
    assert max(_slack(model)) > 0.0


def test_overshoot_goes_flat_because_the_bill_counts_the_height():
    """8 kWh in 2 h over a 2 kW limit: 4 kW EV plus 0.5 kW load in every slot, no higher slot."""
    rows = _rows([0.5] * 8)
    model = _solve(
        rows,
        _caps(rows, 2.0),
        battery=_battery(battery_capacity_kwh=0.0, max_power_kw=0.0),
        consumers=[{**_ev(), "min_power_kw": 1.4}],
        remaining={"eauto": 8.0},
    )
    assert max(_buy(model)) == pytest.approx(4.5, abs=0.05)
    assert max(_slack(model)) == pytest.approx(2.5, abs=0.05)


@pytest.mark.parametrize("control", ["limits_only", "read_only"])
def test_battery_without_full_control_stays_solvable(control):
    rows = _rows([6.0] * 4 + [0.5] * 4)
    model = _solve(rows, _caps(rows, 3.0), battery=_battery(control=control))
    assert model.import_cap_slack is not None


def test_two_batteries_share_the_cap():
    rows = _rows([8.0] * 2 + [0.5] * 4)
    batteries = [
        {**_battery(max_power_kw=3.0), "id": "a"},
        {**_battery(max_power_kw=3.0), "id": "b"},
    ]
    solved = _solve_milp_to_model(
        rows, 80.0, batteries, 5.0, False, [], {}, None, None, {}, None, None, None, None, None,
        current_soc_by_id={"a": 80.0, "b": 80.0},
        import_caps=_caps(rows, 3.0),
    )
    assert solved is not None
    assert max(_buy(solved[0])) <= 3.0 + TOLERANCE


def test_each_month_has_its_own_overshoot():
    rows = _rows([9.0, 0.5, 0.5, 9.0], start=datetime(2027, 1, 31, 23, 30))
    caps = ImportCaps((2.0, 2.0, 2.0, 2.0), ("2027-01", "2027-01", "2027-02", "2027-02"))
    model = _solve(rows, caps, battery=_battery(battery_capacity_kwh=0.0, max_power_kw=0.0))
    names = [name for name in model.prob.variablesDict() if name.startswith("import_cap_overshoot")]
    assert sorted(names) == ["import_cap_overshoot_2027_01", "import_cap_overshoot_2027_02"]


def test_slot_without_a_limit_is_free():
    rows = _rows([9.0, 9.0])
    caps = ImportCaps((None, 2.0), (None, "2027-02"))
    model = _solve(rows, caps, battery=_battery(battery_capacity_kwh=0.0, max_power_kw=0.0))
    assert model.import_cap_slack[0] is None
    assert model.import_cap_slack[1] is not None


def test_too_few_limits_fail_loud():
    rows = _rows([1.0] * 4)
    with pytest.raises(ValueError, match="Bezugsgrenze"):
        _solve(rows, ImportCaps((2.0,), ("2027-01",)))


# --- what the penalty has to beat ---------------------------------------------------------


@pytest.fixture(params=["highs", "cbc"])
def solver(request):
    token = cbc_solver.set_milp_solver_override(request.param)
    yield request.param
    cbc_solver.reset_milp_solver_override(token)


def test_a_price_spread_of_150_cent_does_not_buy_its_way_over_the_cap(solver):
    """Cheap now, very dear later: charging fast would exceed the limit, the plan stays within it."""
    rows = _rows([0.5] * 16)
    for t, row in enumerate(rows):
        row["k_act"] = 5.0 if t < 8 else 155.0
    model = _solve(rows, _caps(rows, 3.0), soc=10.0)
    assert max(_buy(model)) <= 3.0 + TOLERANCE


def test_both_solvers_report_the_same_overshoot(solver):
    rows = _rows([0.5, 9.0, 0.5, 0.5])
    model = _solve(rows, _caps(rows, 2.0), battery=_battery(max_power_kw=1.0), soc=100.0)
    assert _slack(model)[1] == pytest.approx(6.0, abs=1e-3)


# --- plan output ---------------------------------------------------------------------------


def test_plan_output_has_the_slack_only_with_a_cap():
    rows = _rows([0.5, 9.0, 0.5, 0.5])
    battery = _battery(max_power_kw=1.0)
    with_cap = milp_horizon_schedule(
        rows, 100.0, battery_params=battery, k_push=5.0, consumers=[], consumer_remaining_kwh={},
        import_caps=_caps(rows, 2.0),
    )
    assert with_cap[1]["milp_plan"]["import_cap_slack_kw"] == pytest.approx(6.0, abs=1e-3)
    without = milp_horizon_schedule(
        rows, 100.0, battery_params=battery, k_push=5.0, consumers=[], consumer_remaining_kwh={},
    )
    assert "import_cap_slack_kw" not in without[1]["milp_plan"]


def test_optimizer_returns_the_slack_of_the_first_slot():
    rows = _rows([9.0, 0.5, 0.5, 0.5])
    result = milp_optimizer(
        rows, rows[0]["hour"], 100.0, battery_params=_battery(max_power_kw=1.0), k_push=5.0,
        verbose=False, consumers=[], import_caps=_caps(rows, 2.0),
    )
    assert result[5]["import_cap_slack_kw"] == pytest.approx(6.0, abs=1e-3)

"""Import cap in the SE month report (max-power tariff P6c): plan causes per booked slot, days, table."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from optimizer import import_cap_report as icr
from optimizer import milp
from optimizer.import_power_limit import ImportCaps
from simulation import capacity_charge as cc
from simulation.capacity_charge import capacity_for_result
from tests.test_capacity_charge import _charge, _frame, _params
from tests.test_milp_import_cap import _battery, _caps, _rows, _solve
from tests.test_se_import_cap import (  # noqa: F401  (fixtures)
    BATTERY,
    CAP,
    FLEX,
    _matrix,
    _run,
    all_months_active,
    se_env,
)
from ui.backtesting_results_helpers import build_capacity_rows

LIMIT = icr.SLOT_LIMIT_KEY
CAUSE = icr.SLOT_CAUSE_KEY


# --- marks per plan slot ---------------------------------------------------------------------


def test_plan_slot_marks_name_the_cause_where_the_plan_goes_over():
    rows = _rows([0.5, 9.0, 0.5, 0.5])
    caps = ImportCaps((2.0, 2.0, 2.0, None), ("2027-01",) * 3 + (None,))
    model = _solve(rows, caps, battery=_battery(max_power_kw=1.0), soc=100.0)
    marks = icr.plan_slot_marks(model, rows, caps, {})
    assert marks[0] == {LIMIT: 2.0, CAUSE: None}
    assert marks[1] == {LIMIT: 2.0, CAUSE: icr.CAUSE_BASE_LOAD}
    assert marks[3] is None


def test_not_planned_marks_every_slot_with_a_limit():
    caps = ImportCaps((None, 2.0), (None, "2027-01"))
    assert icr.not_planned_slot_marks(caps, 2) == [None, {LIMIT: 2.0, CAUSE: icr.CAUSE_NOT_PLANNED}]


def _schedule(rows, caps):
    return milp.milp_horizon_schedule(
        rows, 100.0, battery_params=_battery(max_power_kw=1.0), k_push=5.0, consumers=[],
        import_caps=caps,
    )


def test_the_horizon_schedule_carries_the_marks():
    rows = _rows([0.5, 9.0, 0.5, 0.5])
    schedule = _schedule(rows, _caps(rows, 2.0))
    assert [slot[CAUSE] for slot in schedule] == [None, icr.CAUSE_BASE_LOAD, None, None]
    assert {slot[LIMIT] for slot in schedule} == {2.0}


def test_a_schedule_without_a_cap_has_no_marks():
    rows = _rows([0.5, 9.0])
    assert not [slot for slot in _schedule(rows, None) if LIMIT in slot]


def test_a_trivial_window_is_not_planned(monkeypatch):
    monkeypatch.setattr(milp, "_try_trivial_milp_skip", lambda *args, **kwargs: {})
    rows = _rows([9.0, 9.0])
    schedule = _schedule(rows, _caps(rows, 2.0))
    assert [slot[CAUSE] for slot in schedule] == [icr.CAUSE_NOT_PLANNED] * 2
    assert "import_cap_cause" not in milp._FALLBACK_SCHEDULE_SLOT


def test_a_failed_solve_is_not_planned(monkeypatch):
    monkeypatch.setattr(milp, "_solve_milp_to_model", lambda *args, **kwargs: None)
    rows = _rows([9.0, 9.0])
    [slot] = _schedule(rows, _caps(rows, 2.0))
    assert slot[CAUSE] == icr.CAUSE_NOT_PLANNED


def _optimizer_plan(loads, caps_limit=2.0):
    rows = _rows(loads)
    caps = _caps(rows, caps_limit)
    result = milp.milp_optimizer(
        rows, rows[0]["hour"], 100.0, battery_params=_battery(max_power_kw=1.0), k_push=5.0,
        verbose=False, consumers=[], import_caps=caps,
    )
    return result[5], caps


def test_first_slot_mark_takes_the_cause_of_slot_zero():
    plan, caps = _optimizer_plan([9.0, 0.5, 0.5, 0.5])
    assert icr.first_slot_mark(plan, caps) == {LIMIT: 2.0, CAUSE: icr.CAUSE_BASE_LOAD}


def test_first_slot_mark_ignores_a_later_slot_over_the_limit():
    plan, caps = _optimizer_plan([0.5, 9.0, 0.5, 0.5])
    assert plan["import_cap_report"]["slots"]
    assert icr.first_slot_mark(plan, caps) == {LIMIT: 2.0, CAUSE: None}


def test_first_slot_mark_of_a_plan_that_was_not_planned():
    rows = _rows([1.0])
    caps = _caps(rows, 2.0)
    plan = {"import_cap_report": icr.not_planned_report(caps, rows, icr.NOT_PLANNED_AUTOMATIK)}
    assert icr.first_slot_mark(plan, caps) == {LIMIT: 2.0, CAUSE: icr.CAUSE_NOT_PLANNED}


def test_first_slot_mark_needs_the_report():
    with pytest.raises(ValueError, match="fehlt im Plan"):
        icr.first_slot_mark({}, _caps(_rows([1.0]), 2.0))


def test_first_slot_mark_without_a_limit_at_slot_zero():
    assert icr.first_slot_mark({}, ImportCaps((None, 2.0), (None, "2027-01"))) is None


# --- chart rows of both SE paths ------------------------------------------------------------


@pytest.mark.parametrize("commit_hours", [1, 8])
def test_chart_rows_carry_limit_and_cause(se_env, commit_hours):
    from optimizer import simulation

    matrix = _matrix(8)
    for row in matrix[2:4]:
        row["expected_p_act"] = 9.0
    rows = simulation.simulate_horizon(
        matrix,
        100.0,
        battery_params={**BATTERY, "max_power_kw": 1.0},
        verbose=False,
        flexible_consumers=[FLEX],
        consumer_daily_targets_kwh={"eauto": 0.0},
        commit_hours=commit_hours,
        disable_horizon_soc_anchor=True,
        import_caps=ImportCaps(tuple(2.0 for _ in matrix), tuple("2027-01" for _ in matrix)),
    )
    assert [row[LIMIT] for row in rows] == [2.0] * 8
    assert [row[CAUSE] for row in rows[2:4]] == [icr.CAUSE_BASE_LOAD] * 2
    assert rows[0][CAUSE] is None


# --- booked slots over the cap --------------------------------------------------------------


def _capped(peaks_kw: dict[datetime, float], marks: dict[datetime, tuple[float, str | None]]) -> pd.DataFrame:
    """``_frame`` with the plan's limit 2.5 kW (cap 3, margin 0.5) and causes at given slots."""
    frame = _frame(peaks_kw)
    frame[LIMIT] = 2.5
    frame[CAUSE] = None
    for moment, (limit, cause) in marks.items():
        frame.loc[pd.Timestamp(moment), LIMIT] = limit
        frame.loc[pd.Timestamp(moment), CAUSE] = cause
    return frame


def _month(frame, tmp_path, cap_kw=3.0):
    params = {**_params(tmp_path, [_charge()]), **CAP}
    [month] = capacity_for_result(frame, params, planned_cap_kw=cap_kw).months
    return month


DAY1 = datetime(2027, 1, 12, 18, 0)
DAY2 = datetime(2027, 1, 13, 18, 0)


def test_days_and_causes_of_the_booked_slots_over_the_cap(tmp_path):
    peak1, peak2 = DAY1 + timedelta(minutes=15), DAY2 + timedelta(minutes=15)
    frame = _capped(
        {DAY1: 5.0, DAY2: 4.0},
        {peak1: (2.5, icr.CAUSE_BATTERY_ENERGY), peak2: (4.5, None)},
    )
    month = _month(frame, tmp_path)
    assert month.slots_over_cap == 2
    assert month.days_over_cap == 2
    assert month.causes_over_cap == {icr.CAUSE_BATTERY_ENERGY: 1, cc.CAUSE_MONTH_PEAK: 1}


def test_a_slot_over_the_plans_limit_without_plan_cause_was_booked_above_the_plan(tmp_path):
    month = _month(_capped({DAY1: 5.0}, {}), tmp_path)
    assert month.causes_over_cap == {cc.CAUSE_BOOKED_ABOVE_PLAN: 1}
    assert month.days_over_cap == 1


def test_slots_on_one_day_count_one_day(tmp_path):
    frame = _capped({DAY1: 5.0, DAY1 + timedelta(hours=2): 5.0}, {})
    month = _month(frame, tmp_path)
    assert (month.slots_over_cap, month.days_over_cap) == (2, 1)


def test_no_slot_over_the_cap_needs_no_marks(tmp_path):
    month = _month(_frame({DAY1: 2.0}), tmp_path)
    assert (month.slots_over_cap, month.days_over_cap, month.causes_over_cap) == (0, 0, {})


def test_a_capped_result_without_the_columns_fails(tmp_path):
    with pytest.raises(ValueError, match="ohne Spalte import_cap_limit"):
        _month(_frame({DAY1: 5.0}), tmp_path)


def test_a_slot_over_the_cap_without_a_plan_limit_fails(tmp_path):
    frame = _capped({DAY1: 5.0}, {DAY1 + timedelta(minutes=15): (float("nan"), None)})
    with pytest.raises(ValueError, match="ohne Plan-Grenze"):
        _month(frame, tmp_path)


def test_a_run_books_causes_for_every_slot_over_the_cap(se_env, all_months_active):
    """A cap of 0.1 kW cannot hold; every booked slot over it gets a cause."""
    frame, _, _ = _run(se_env, {**se_env["scenario"], "import_cap_kw": 0.1, "import_cap_margin_kw": 0.05})
    assert frame[LIMIT].notna().all()
    unique, _ = cc._unique_slots(frame)
    power = cc._booked_import_kw(unique)
    over = power[power > 0.1 + 1e-6]
    assert len(over)
    for month in sorted(set(over.index.strftime("%Y-%m"))):
        result = cc._over_cap(unique, power, month, 0.1)
        assert sum(result.causes.values()) == result.slots
    causes = cc._over_cap(unique, power, over.index[0].strftime("%Y-%m"), 0.1).causes
    assert set(causes) <= set(cc.SE_CAUSE_LABELS_DE)


def test_a_run_without_a_cap_has_no_cap_columns(se_env):
    frame, _, _ = _run(se_env, se_env["scenario"])
    assert LIMIT not in frame.columns
    assert CAUSE not in frame.columns


# --- the table ------------------------------------------------------------------------------


def _meta(months_by_result: dict[str, list[dict]]) -> dict:
    return {
        "capacity_by_scenario": {sid: {"months": months} for sid, months in months_by_result.items()},
        "summary": {"total_eur": {sid: 1.0 for sid in months_by_result}},
    }


MONTH = {"peak_kw": 5.0, "billed_kw": 5.0, "gross_eur": 9.0, "import_cap_kw": 3.0}


def test_table_shows_days_and_main_causes_over_all_months():
    meta = _meta({
        "capped": [
            {**MONTH, "month": "2027-01", "slots_over_cap": 3, "days_over_cap": 2,
             "causes_over_cap": {icr.CAUSE_BATTERY_ENERGY: 2, cc.CAUSE_MONTH_PEAK: 1}},
            {**MONTH, "month": "2027-02", "slots_over_cap": 2, "days_over_cap": 1,
             "causes_over_cap": {cc.CAUSE_MONTH_PEAK: 2}},
        ],
    })
    [row] = build_capacity_rows(meta)
    assert row["Viertelstunden über der Grenze"] == 5
    assert row["Tage über der Grenze"] == 3
    assert row["Hauptursachen"] == (
        "Monatsspitze schon höher, Grenze angehoben: 3; Batterie leer oder Reserve: 2"
    )


def test_table_without_slots_over_the_cap_shows_no_cause():
    meta = _meta({"capped": [{**MONTH, "month": "2027-01", "slots_over_cap": 0, "days_over_cap": 0,
                             "causes_over_cap": {}}]})
    [row] = build_capacity_rows(meta)
    assert (row["Tage über der Grenze"], row["Hauptursachen"]) == (0, "—")


def test_a_log_from_before_p6c_shows_a_dash_for_days_and_causes():
    meta = _meta({"old": [{**MONTH, "month": "2027-01", "slots_over_cap": 4}]})
    [row] = build_capacity_rows(meta)
    assert row["Viertelstunden über der Grenze"] == 4
    assert (row["Tage über der Grenze"], row["Hauptursachen"]) == ("—", "—")

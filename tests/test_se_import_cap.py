"""Import cap in the SE: only L3 plans with it, the month peak carries across windows, the report."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from house_config.import_cap import parse_import_cap
from optimizer.import_power_limit import ImportCaps, import_caps_for_slots
from simulation import anchor_step, engine
from simulation.anchor_step import _window_import_caps, import_peaks_after_window
from simulation.capacity_charge import capacity_by_result, capacity_for_result
from tests.fixtures.backtesting_fixtures import (
    HIGH_EAUTO_DAY,
    SOC_CHAIN_END_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    load_fixture_cache,
)
from tests.test_capacity_charge import _charge, _frame, _params
from ui.backtesting_results_helpers import build_capacity_rows

START = datetime(2027, 1, 12, 7, 0)
CAP = {"import_cap_kw": 3.0, "import_cap_margin_kw": 0.5}


# --- limits of a window ------------------------------------------------------------------


def test_from_slot_is_the_rest_of_the_plan():
    caps = ImportCaps((1.0, None, 3.0), ("2027-01", None, "2027-01"))
    assert caps.from_slot(1) == ImportCaps((None, 3.0), (None, "2027-01"))


def test_from_slot_without_a_limit_left_gives_none():
    assert ImportCaps((1.0, None), ("2027-01", None)).from_slot(1) is None


def test_only_at_frees_the_other_slots():
    caps = ImportCaps((1.0, 2.0, 3.0), ("2027-01", "2027-01", "2027-02"))
    assert caps.only_at({1}) == ImportCaps((None, 2.0, None), (None, "2027-01", None))


def _plan(slots: int, book_start: int = 0, book_slots: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        matrix=[{"slot_datetime": START + timedelta(minutes=15 * t)} for t in range(slots)],
        flex_book_start=book_start,
        flex_book_hours=book_slots,
    )


@pytest.fixture
def all_months_active(monkeypatch):
    """The scenarios here have no grid area: every month counts as one with a capacity charge."""

    def active(params, slots, peak_by_month):
        return import_caps_for_slots(slots, parse_import_cap(params), lambda _month: True, peak_by_month)

    monkeypatch.setattr(anchor_step, "import_caps_from_params", active)


def test_window_without_a_cap_has_no_limits():
    assert _window_import_caps(_plan(4), {}, {}) is None


def test_slots_before_and_after_the_book_are_free(all_months_active):
    caps = _window_import_caps(_plan(5, book_start=2, book_slots=2), CAP, {})
    assert caps.limits_kw == (None, None, 2.5, 2.5, None)


def test_fixed_window_limits_every_slot(all_months_active):
    assert _window_import_caps(_plan(3), CAP, {}).limits_kw == (2.5, 2.5, 2.5)


def test_reached_peak_lifts_the_window(all_months_active):
    assert _window_import_caps(_plan(2), CAP, {"2027-01": 4.0}).limits_kw == (3.5, 3.5)


def test_limits_come_from_the_grid_area(tmp_path):
    params = {**_params(tmp_path, [_charge(valid_from="2027-02-01")]), **CAP}
    plan = SimpleNamespace(
        matrix=[{"slot_datetime": datetime(2027, 1, 31, 23, 45)}, {"slot_datetime": datetime(2027, 2, 1)}],
        flex_book_start=0,
        flex_book_hours=None,
    )
    assert _window_import_caps(plan, params, {}).limits_kw == (None, 2.5)


# --- month peak --------------------------------------------------------------------------


def _row(slot: datetime, grid_kw: float) -> dict:
    return {"slot_datetime": slot, "Netzbezug (kW)": grid_kw}


def test_peak_rises_with_booked_import_and_stays():
    rows = [_row(START, 2.0), _row(START + timedelta(minutes=15), 5.0), _row(START + timedelta(minutes=30), 1.0)]
    assert import_peaks_after_window(rows, {"2027-01": 3.0}) == {"2027-01": 5.0}


def test_peak_below_the_earlier_one_changes_nothing():
    assert import_peaks_after_window([_row(START, 2.0)], {"2027-01": 3.0}) == {"2027-01": 3.0}


def test_export_is_no_peak():
    assert import_peaks_after_window([_row(START, -4.0)], {}) == {"2027-01": 0.0}


def test_each_month_keeps_its_own_peak():
    rows = [_row(datetime(2027, 1, 31, 23, 45), 6.0), _row(datetime(2027, 2, 1, 0, 0), 2.0)]
    assert import_peaks_after_window(rows, {}) == {"2027-01": 6.0, "2027-02": 2.0}


def test_handed_in_peaks_stay_untouched():
    peaks = {"2027-01": 1.0}
    import_peaks_after_window([_row(START, 2.0)], peaks)
    assert peaks == {"2027-01": 1.0}


# --- a run -------------------------------------------------------------------------------


@pytest.fixture
def se_env(monkeypatch):
    """Windows without PV: the fixture's offline PV covers all load, so nothing would be imported.

    Solves in the product's mode: importing ``scripts.run_regression`` sets ``EARNIE_CBC_STRICT``
    for the whole process, and a strict solve has no time limit (a 0.1 kW cap did not end).
    """
    monkeypatch.delenv("EARNIE_CBC_STRICT", raising=False)
    real_matrix = anchor_step.build_sunrise_window_matrix

    def matrix_without_pv(*args, **kwargs):
        book, meta, sa1_index, full = real_matrix(*args, **kwargs)
        for row in full:
            row["expected_p_pv"] = 0.0
        return book, meta, sa1_index, full

    monkeypatch.setattr(anchor_step, "build_sunrise_window_matrix", matrix_without_pv)
    with activate_backtesting_fixtures(monkeypatch):
        yield {
            "cache": load_fixture_cache(),
            "scenario": fixture_scenario_params(),
            "prices": build_synthetic_prices_df(pd.Timestamp("2024-07-01"), pd.Timestamp("2026-06-26")),
        }


@pytest.fixture
def horizon_calls(monkeypatch):
    """The real ``simulate_horizon``; keeps what each window was given."""
    calls: list[dict] = []
    real = engine.simulate_horizon

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "simulate_horizon", spy)
    return calls


def _run(env, scenario):
    return engine.run_simulation(
        pd.Timestamp(HIGH_EAUTO_DAY),
        pd.Timestamp(SOC_CHAIN_END_DAY),
        scenario,
        env["prices"],
        cache=env["cache"],
    )


def _peak_kw(frame: pd.DataFrame) -> float:
    return float(frame["import_kwh"].max()) / 0.25


def test_without_a_cap_no_window_gets_limits(se_env, horizon_calls):
    _run(se_env, se_env["scenario"])
    assert horizon_calls
    assert not [call for call in horizon_calls if "import_caps" in call]


def test_a_cap_lowers_the_booked_peak_and_keeps_the_energy(se_env, all_months_active):
    free, free_check, _ = _run(se_env, se_env["scenario"])
    limit = _peak_kw(free) * 0.6
    capped, capped_check, _ = _run(
        se_env, {**se_env["scenario"], "import_cap_kw": limit, "import_cap_margin_kw": 0.2}
    )
    assert _peak_kw(capped) < _peak_kw(free)
    assert capped_check.failed == free_check.failed == []
    assert capped["consumption_kw"].sum() == pytest.approx(free["consumption_kw"].sum(), rel=0.01)


def test_the_next_window_plans_with_the_peak_of_the_one_before(se_env, all_months_active, horizon_calls):
    """A cap of 0.1 kW cannot hold, so the first window sets a peak that lifts the second one."""
    frame, _, _ = _run(se_env, {**se_env["scenario"], "import_cap_kw": 0.1, "import_cap_margin_kw": 0.05})
    first, second, *_ = [call["import_caps"] for call in horizon_calls]
    assert {limit for limit in first.limits_kw if limit is not None} == {0.05}
    first_book = frame.iloc[: first.limits_kw.count(0.05)]
    lifted = {limit for limit in second.limits_kw if limit is not None}
    assert len(lifted) == 1
    assert lifted.pop() == pytest.approx(_peak_kw(first_book) - 0.05, abs=0.01)


def test_forecast_mode_plans_with_the_cap_and_books_on_the_window(all_months_active, monkeypatch):
    plan = SimpleNamespace(
        matrix=[{"slot_datetime": START}],
        meta={"sa1": START, "consumer_daily_targets_kwh": {}},
        sunrise_soc_min_index=None,
        commit_hours=1,
        disable_soc_anchor=True,
        flex_book_hours=None,
        flex_book_start=0,
        soc_hold_index=None,
        soc_hold_percent=None,
    )
    captured: dict = {}
    planned = [{"slot_datetime": START, "plan": True}]

    def fake_horizon(matrix, _soc, **kwargs):
        captured.update(kwargs, matrix=matrix)
        return []

    monkeypatch.setattr(anchor_step, "_simulate_horizon", fake_horizon)
    monkeypatch.setattr(anchor_step, "_flexible_consumers_from_scenario", lambda _params: [])
    anchor_step._simulate_plan_horizon(
        plan,
        50.0,
        battery_params={},
        hours_done=0,
        collect_cbc=False,
        scenario_params=CAP,
        forecast_planner=SimpleNamespace(plan_matrix=lambda _matrix, _sa1: planned),
        import_peak_by_month={"2027-01": 4.0},
    )
    assert captured["matrix"] is planned
    assert captured["booking_matrix"] is plan.matrix
    assert captured["import_caps"].limits_kw == (3.5,)

# --- the slots re-solved inside a window -------------------------------------------------


def _matrix(slots: int) -> list[dict]:
    rows = []
    for t in range(slots):
        slot = START + timedelta(minutes=15 * t)
        rows.append(
            {
                "hour": slot.hour,
                "date": slot.date(),
                "slot_datetime": slot,
                "expected_p_pv": 0.0,
                "expected_p_act": 1.0,
                "k_act": 20.0,
                "k_push_act": 5.0,
                "expected_flex_kw": {},
            }
        )
    return rows


BATTERY = {
    "battery_capacity_kwh": 10.0,
    "min_soc": 10.0,
    "max_soc": 100.0,
    "max_power_kw": 5.0,
    "efficiency": 0.95,
    "control": "full",
}
FLEX = {
    "id": "eauto",
    "name": "E-Auto",
    "nominal_power_kw": 11.0,
    "min_power_kw": 4.2,
    "min_on_quarterhours": 1,
    "ehal_bindings": {"set_evcs_max_current": "x"},
}


def _spy_on_limit_lengths(monkeypatch, target: str) -> list[int]:
    from optimizer import simulation

    seen: list[int] = []
    real = getattr(simulation, target)

    def spy(*args, **kwargs):
        seen.append(len(kwargs["import_caps"].limits_kw))
        return real(*args, **kwargs)

    monkeypatch.setattr(simulation, target, spy)
    return seen


def _simulate_with_limits(slots: int, commit_hours: int) -> None:
    from optimizer import simulation

    matrix = _matrix(slots)
    simulation.simulate_horizon(
        matrix,
        50.0,
        battery_params=BATTERY,
        verbose=False,
        flexible_consumers=[FLEX],
        consumer_daily_targets_kwh={"eauto": 0.0},
        commit_hours=commit_hours,
        disable_horizon_soc_anchor=True,
        import_caps=ImportCaps(tuple(3.0 for _ in matrix), tuple("2027-01" for _ in matrix)),
    )


def test_per_slot_solves_get_the_rest_of_the_limits(se_env, monkeypatch):
    seen = _spy_on_limit_lengths(monkeypatch, "milp_optimizer")
    _simulate_with_limits(4, commit_hours=1)
    assert seen == [4, 3, 2, 1]


def test_open_loop_refill_gets_the_rest_of_the_limits(se_env, monkeypatch):
    seen = _spy_on_limit_lengths(monkeypatch, "milp_horizon_schedule")
    _simulate_with_limits(12, commit_hours=2)
    assert seen == [12, 4]

# --- the references ----------------------------------------------------------------------


def test_the_cap_does_not_touch_l1_and_l2(se_env):
    from simulation.reference_ladder import compute_l1_reference_costs, compute_l2_reference_costs

    capped = {**se_env["scenario"], **CAP}
    for compute in (compute_l1_reference_costs, compute_l2_reference_costs):
        results = [
            compute(
                pd.Timestamp(HIGH_EAUTO_DAY),
                pd.Timestamp(SOC_CHAIN_END_DAY),
                scenario,
                se_env["prices"],
                se_env["cache"],
                initial_soc=50.0,
                horizon_mode="sunrise_window",
            )
            for scenario in (se_env["scenario"], capped)
        ]
        pd.testing.assert_frame_equal(results[0].frame, results[1].frame)


def test_scenarios_that_differ_in_the_cap_share_their_references(se_env):
    from simulation.reference_ladder import ladder_reference_fingerprint

    assert ladder_reference_fingerprint(se_env["scenario"]) == ladder_reference_fingerprint(
        {**se_env["scenario"], **CAP}
    )


# --- the report --------------------------------------------------------------------------


def _params_with_charge(tmp_path) -> dict:
    return {**_params(tmp_path, [_charge()]), **CAP}


def test_report_counts_the_booked_slots_over_the_cap_per_month(tmp_path):
    frame = _frame({datetime(2027, 1, 12, 18, 0): 5.0, datetime(2027, 2, 12, 18, 0): 2.0})
    months = capacity_for_result(frame, _params_with_charge(tmp_path), planned_cap_kw=3.0).months
    assert [(m.month, m.import_cap_kw, m.slots_over_cap) for m in months] == [
        ("2027-01", 3.0, 1),
        ("2027-02", 3.0, 0),
    ]


def test_a_slot_exactly_at_the_cap_is_not_over_it(tmp_path):
    frame = _frame({datetime(2027, 1, 12, 18, 0): 3.0})
    result = capacity_for_result(frame, _params_with_charge(tmp_path), planned_cap_kw=3.0)
    assert result.months[0].slots_over_cap == 0


def test_a_reference_with_the_same_params_reports_no_cap(tmp_path):
    frame = _frame({datetime(2027, 1, 12, 18, 0): 5.0})
    params = _params_with_charge(tmp_path)
    results = capacity_by_result(
        {"l3": frame, "ladder:l1": frame},
        {"l3": params, "ladder:l1": params},
        {"l3": 3.0},
    )
    assert results["l3"].months[0].slots_over_cap == 1
    assert results["ladder:l1"].months[0].import_cap_kw is None
    assert results["ladder:l1"].months[0].slots_over_cap == 0


def test_the_cap_does_not_change_the_amount(tmp_path):
    frame = _frame({datetime(2027, 1, 12, 18, 0): 5.0})
    params = _params_with_charge(tmp_path)
    assert (
        capacity_for_result(frame, params, planned_cap_kw=3.0).gross_eur
        == capacity_for_result(frame, params).gross_eur
    )


def test_table_shows_cap_and_slots_and_old_logs_still_read():
    month = {"month": "2027-01", "peak_kw": 5.0, "billed_kw": 5.0, "gross_eur": 9.0}
    meta = {
        "capacity_by_scenario": {
            "capped": {"months": [{**month, "import_cap_kw": 3.0, "slots_over_cap": 2}]},
            "old_log": {"months": [month]},
        },
        "summary": {"total_eur": {"capped": 1.0, "old_log": 2.0}},
    }
    rows = {row["Szenario"]: row for row in build_capacity_rows(meta)}
    assert rows["capped"]["Viertelstunden über der Grenze"] == 2
    assert rows["capped"]["Bezugsgrenze [kW]"] != "–"
    assert rows["old_log"]["Bezugsgrenze [kW]"] == "–"
    assert rows["old_log"]["Viertelstunden über der Grenze"] == 0

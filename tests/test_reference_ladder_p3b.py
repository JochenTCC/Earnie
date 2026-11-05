"""RuleRef P3b: end-SoC valuation and the SE window view on L2 (spec §§ 3.3, 5)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import pytest

from simulation.horizon_mode import SUNRISE_WINDOW
from simulation.reference_costs import RUN_END_SOC_ATTR
from simulation.reference_ladder import compute_ladder_reference, ladder_soc_correction
from tests.fixtures.backtesting_fixtures import (
    HIGH_EAUTO_DAY,
    activate_backtesting_fixtures,
    build_synthetic_prices_df,
    fixture_scenario_params,
    fixture_tariff_params,
    load_fixture_cache,
)
from ui.backtesting_results_helpers import build_annual_cost_rows
from ui.backtesting_standard_rules import (
    STANDARD_RULES_LABEL,
    StandardRulesSeries,
    apply_standard_rules,
    standard_rules_caption,
    standard_rules_series,
)
from ui.chart_baseline_label import (
    DEFAULT_BASELINE_LABEL,
    baseline_label,
    chart_baseline_label_context,
)

os.environ.setdefault("EARNIE_OFFLINE", "1")

_DAY = pd.Timestamp("2026-06-10")
_BATTERY = {"battery_capacity_kwh": 10.0, "efficiency": 0.9}


def _frame(soc: list[float], *, start=_DAY, import_kwh=1.0, k_act=30.0, end_soc=None) -> pd.DataFrame:
    index = pd.date_range(start, periods=len(soc), freq="15min", name="ts")
    frame = pd.DataFrame(
        {"sim_soc": soc, "import_kwh": import_kwh, "k_act": k_act}, index=index
    )
    if end_soc is not None:
        frame.attrs[RUN_END_SOC_ATTR] = end_soc
    return frame


@pytest.fixture
def one_battery(monkeypatch):
    monkeypatch.setattr(
        "simulation.engine_scenario._scenario_to_battery_params", lambda _params: dict(_BATTERY)
    )


def _correction(results: dict, *, end=_DAY) -> dict:
    return ladder_soc_correction(results, "live", {"l2": "l2:live"}, {}, end)


def test_fuller_l3_is_credited_with_the_ledger_formula(one_battery):
    block = _correction(
        {
            "live": _frame([50.0] * 96, end_soc=80.0),
            "l2:live": _frame([50.0] * 96, end_soc=30.0),
        }
    )
    # 50 % of 10 kWh × 0.9 × 30 ct.
    assert block["steps"]["l2"]["correction_eur"] == pytest.approx(1.35)
    assert block["p_ref_basis"] == "import_weighted"
    assert block["p_ref_cent"] == pytest.approx(30.0)


def test_fuller_l2_is_deducted(one_battery):
    block = _correction(
        {"live": _frame([50.0] * 96, end_soc=30.0), "l2:live": _frame([50.0] * 96, end_soc=80.0)}
    )
    assert block["steps"]["l2"]["correction_eur"] == pytest.approx(-1.35)


def test_equal_end_soc_has_no_term(one_battery):
    block = _correction(
        {"live": _frame([50.0] * 96, end_soc=42.0), "l2:live": _frame([50.0] * 96, end_soc=42.0)}
    )
    assert block["steps"]["l2"]["correction_eur"] == 0.0


def test_soc_is_read_where_the_period_ends_not_where_the_run_ends(one_battery):
    """Books spill over the period's end; those slots are not booked in the period."""
    soc = [50.0] * 96 + [70.0, 99.0]
    block = _correction(
        {"live": _frame(soc, end_soc=1.0), "l2:live": _frame([50.0] * 96 + [40.0, 2.0], end_soc=2.0)}
    )
    assert block["soc_end_percent"] == 70.0
    assert block["steps"]["l2"]["soc_end_percent"] == 40.0


def test_day_without_import_takes_the_time_mean_and_says_so(one_battery):
    l3 = _frame([50.0] * 96, import_kwh=0.0, end_soc=60.0)
    l3["k_act"] = [10.0] * 48 + [20.0] * 48
    block = _correction({"live": l3, "l2:live": _frame([50.0] * 96, end_soc=50.0)})
    assert block["p_ref_basis"] == "time_mean"
    assert block["p_ref_cent"] == pytest.approx(15.0)


def test_p_ref_only_reads_the_last_day(one_battery):
    l3 = _frame([50.0] * 192, end_soc=60.0, start=_DAY - pd.Timedelta(days=1))
    l3["k_act"] = [99.0] * 96 + [30.0] * 96
    block = _correction({"live": l3, "l2:live": _frame([50.0] * 96, end_soc=50.0)})
    assert block["p_ref_cent"] == pytest.approx(30.0)


def test_run_without_end_soc_fails_loud(one_battery):
    with pytest.raises(ValueError, match="End-SoC"):
        _correction({"live": _frame([50.0] * 96), "l2:live": _frame([50.0] * 96, end_soc=50.0)})


def _meta(correction: float | None) -> dict:
    meta = {
        "reference_id": "historical_reference",
        "live_scenario_id": "live",
        "scenario_ids": ["l2:live", "live"],
        "labels": {},
        "ladder_by_scenario": {"live": {"l2": "l2:live"}},
        "summary": {"total_eur": {"l2:live": 1000.0, "live": 900.0}},
    }
    if correction is not None:
        meta["ladder_soc_correction"] = {
            "live": {
                "soc_end_percent": 80.0,
                "steps": {"l2": {"soc_end_percent": 30.0, "correction_eur": correction}},
            }
        }
    return meta


def _live_row(meta: dict) -> dict:
    return next(row for row in build_annual_cost_rows(meta) if row["Szenario"] == "live")


def test_saving_column_includes_the_soc_term_and_names_it():
    row = _live_row(_meta(1.35))
    assert row["Ersparnis vs. Standard-Regeln [€]"] == "101,35 € gespart"
    assert "1,35 € gutgeschrieben (80 % gegen 30 %)" in row["Hinweis"]


def test_deducted_term_lowers_the_saving_in_words():
    row = _live_row(_meta(-1.35))
    assert row["Ersparnis vs. Standard-Regeln [€]"] == "98,65 € gespart"
    assert "1,35 € abgezogen" in row["Hinweis"]


def test_log_before_this_valuation_says_so():
    row = _live_row(_meta(None))
    assert row["Ersparnis vs. Standard-Regeln [€]"] == "100,00 € gespart"
    assert "nicht bewertet" in row["Hinweis"]


@pytest.fixture
def ladder_env(monkeypatch):
    with activate_backtesting_fixtures(monkeypatch):
        yield {
            "cache": load_fixture_cache(),
            "scenario": {
                **fixture_scenario_params(),
                **fixture_tariff_params("de_spot_test", "fixed_37ct", timezone_name="Europe/Berlin"),
            },
            "prices": build_synthetic_prices_df(
                pd.Timestamp("2024-07-01"), pd.Timestamp("2026-06-26")
            ),
        }


def _ladder_run(env: dict, step: str) -> "object":
    day = pd.Timestamp(HIGH_EAUTO_DAY)
    return compute_ladder_reference(
        step, day, day, env["scenario"], env["prices"], env["cache"], horizon_mode=SUNRISE_WINDOW
    )


def test_ladder_frame_carries_the_chart_columns_and_its_end_soc(ladder_env):
    result = _ladder_run(ladder_env, "l2")
    frame = result.frame
    assert frame.attrs[RUN_END_SOC_ATTR] == pytest.approx(result.end_soc)
    assert {"batt_action_kw", "baseload_kw"} <= set(frame.columns)
    flex_columns = [
        col
        for col in frame.columns
        if col.endswith("_kw") and col not in {"consumption_kw", "baseload_kw", "batt_action_kw"}
    ]
    assert flex_columns
    # Fixed load sits in the base load's column split, so the sum reproduces the total.
    assert (frame["baseload_kw"] + frame[flex_columns].sum(axis=1)).sum() == pytest.approx(
        frame["consumption_kw"].sum(), rel=1e-3
    )


def test_real_runs_value_their_soc_difference_with_the_scenarios_battery(ladder_env):
    l1, l2 = _ladder_run(ladder_env, "l1"), _ladder_run(ladder_env, "l2")
    block = ladder_soc_correction(
        {"live": l2.frame, "l1:live": l1.frame, "l2:live": l2.frame},
        "live",
        {"l1": "l1:live", "l2": "l2:live"},
        ladder_env["scenario"],
        pd.Timestamp(HIGH_EAUTO_DAY),
    )
    assert block["steps"]["l2"]["correction_eur"] == 0.0
    step = block["steps"]["l1"]
    capacity = float(ladder_env["scenario"]["battery_capacity_kwh"])
    efficiency = float(ladder_env["scenario"]["battery_efficiency"])
    assert step["correction_eur"] == pytest.approx(
        (block["soc_end_percent"] - step["soc_end_percent"])
        / 100.0
        * capacity
        * efficiency
        * block["p_ref_cent"]
        / 100.0
    )
    assert block["p_ref_cent"] > 0.0


def test_book_segment_shows_the_slots_the_window_booked():
    """SA₀→SA₂ follows the anchor's calendar date, as in the run; not anchor − 24 h."""
    from simulation.backtesting_horizon import resolve_ready_by_sunrise_step
    from ui.backtesting_chart_context import _backtesting_sunrise_segment_window
    from zoneinfo import ZoneInfo

    tz = "Europe/Vienna"
    anchor = datetime(2026, 10, 11, 12, 0, tzinfo=ZoneInfo(tz))
    step = resolve_ready_by_sunrise_step(anchor, 48.2, 16.4, tz)
    book = _backtesting_sunrise_segment_window(anchor, 1, 48.2, 16.4, tz)
    lead_in = _backtesting_sunrise_segment_window(anchor, 0, 48.2, 16.4, tz)
    assert tuple(book.slot_datetimes) == step.book_slots
    assert lead_in.slot_datetimes[-1] < book.slot_datetimes[0]
    assert (book.sa0, book.sa1, book.sa2) == (step.sa0, step.sa1, step.sa2)


def test_equal_end_soc_needs_no_hint():
    assert "SoC" not in _live_row(_meta(0.0))["Hinweis"]


def _hourly(start: datetime, slots: int, scenario_id: str, cost: float, soc: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": [start + timedelta(minutes=15 * i) for i in range(slots)],
            "scenario_id": scenario_id,
            "sim_cost": [cost] * slots,
            "consumption_kw": [2.0] * slots,
            "sim_soc": [soc] * slots,
            "batt_action_kw": [0.5] * slots,
            "ev_kw": [3.0] * slots,
        }
    )


def _chart_rows(start: datetime, slots: int) -> list[dict]:
    return [
        {"slot_datetime": start + timedelta(minutes=15 * i), "Uhrzeit": f"{i}"} for i in range(slots)
    ]


_START = datetime(2026, 6, 10, 6, 0)
_CONSUMER = {"id": "ev", "name": "EV"}


def _series(slots: int = 8, *, start: datetime = _START) -> StandardRulesSeries:
    hourly = pd.concat(
        [_hourly(start, slots, "l2:live", 0.5, 40.0), _hourly(start, slots, "live", 0.2, 60.0)]
    )
    series = standard_rules_series(
        {"ladder_by_scenario": {"live": {"l2": "l2:live"}}}, hourly, "live"
    )
    assert series is not None
    return series


def test_window_saving_sums_to_l2_minus_l3_of_its_slots():
    info = apply_standard_rules({"baseline_rows": []}, _chart_rows(_START, 8), _series(), [_CONSUMER])
    assert sum(info["hourly_savings_euro"]) == pytest.approx(8 * (0.5 - 0.2))
    assert info["savings_matched_euro"] == pytest.approx(2.4)
    assert info["matched_baseline_cost_euro"] == pytest.approx(4.0)
    assert info["optimized_cost_euro"] == pytest.approx(1.6)
    assert info["hourly_matched_baseline_consumption_kwh"] == pytest.approx([0.5] * 8)
    assert info["standard_rules_slots_outside_period"] == 0
    assert info["baseline_rows"] == []


def test_slots_outside_the_period_count_nothing_and_are_named():
    """The first window starts before the period: the first 4 slots were never booked."""
    rows = _chart_rows(_START - timedelta(hours=1), 12)
    info = apply_standard_rules({}, rows, _series(), [_CONSUMER])
    assert info["hourly_matched_baseline_cost_euro"][:4] == [0.0] * 4
    assert info["hourly_optimized_cost_euro"][:4] == [0.0] * 4
    assert sum(info["hourly_savings_euro"]) == pytest.approx(2.4)
    assert info["standard_rules_slots_outside_period"] == 4
    baseline = pd.DataFrame(info["matched_baseline_rows"])
    assert baseline["Simulierter SoC (%)"].iloc[:4].isna().all()
    assert baseline["Simulierter SoC (%)"].iloc[4] == 40.0
    assert "1 h des Fensters liegen außerhalb" in standard_rules_caption(info)


def test_baseline_rows_have_what_chart_1_draws():
    from optimizer.targets import consumer_column_name

    info = apply_standard_rules({}, _chart_rows(_START, 2), _series(), [_CONSUMER])
    row = info["matched_baseline_rows"][0]
    assert row["Simulierter SoC (%)"] == 40.0
    assert row["Geplante Batterie-Aktion (kW)"] == 0.5
    assert row[consumer_column_name(_CONSUMER)] == 3.0


def test_repeated_hour_counts_once():
    hourly = pd.concat([_hourly(_START, 2, "l2:live", 0.5, 40.0)] * 2 + [_hourly(_START, 2, "live", 0.2, 60.0)])
    series = standard_rules_series({"ladder_by_scenario": {"live": {"l2": "l2:live"}}}, hourly, "live")
    assert len(series.l2) == 2


def test_log_without_a_ladder_keeps_its_baseline():
    assert standard_rules_series({}, pd.DataFrame(), "live") is None
    assert standard_rules_caption({}) is None


def test_missing_series_fails_loud():
    meta = {"ladder_by_scenario": {"live": {"l2": "l2:live"}}}
    with pytest.raises(ValueError, match="l2:live"):
        standard_rules_series(meta, _hourly(_START, 2, "live", 0.2, 60.0), "live")
    with pytest.raises(ValueError, match="Stundenreihen"):
        standard_rules_series(meta, None, "live")


def test_label_scope():
    assert baseline_label() == DEFAULT_BASELINE_LABEL
    with chart_baseline_label_context(STANDARD_RULES_LABEL):
        assert baseline_label() == STANDARD_RULES_LABEL
        with chart_baseline_label_context(None):
            assert baseline_label() == STANDARD_RULES_LABEL
    assert baseline_label() == DEFAULT_BASELINE_LABEL


def test_chart_2_names_the_baseline():
    from ui.chart_cumulative import add_cumulative_cost_traces
    from ui.chart_decorations import _cost_summary_annotations
    from ui.chart_slot_axis import ChartSlotAxis
    import plotly.graph_objects as go

    frame = pd.DataFrame(_chart_rows(_START, 4))
    axis = ChartSlotAxis.from_dataframe(frame)
    fig = go.Figure()
    with chart_baseline_label_context(STANDARD_RULES_LABEL):
        add_cumulative_cost_traces(fig, frame["Uhrzeit"], axis, [1.0] * 4, [0.5] * 4)
        texts = [a["text"] for a in _cost_summary_annotations(4.0, 2.0)]
    assert "Kosten Standard-Regeln" in {trace.name for trace in fig.data}
    assert "Standard-Regeln: 4,00 €" in texts

"""SE consumption accounting: native pool-filter booking and booked series totals."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from optimizer import filter_context as fc
from optimizer.slot_duration import DEFAULT_DT_H, slot_step
from simulation.booked_consumption import (
    booked_consumption_by_result,
    booked_consumption_totals,
    slot_coverage_diff,
)
from simulation.engine_scenario import (
    _consumption_kw_columns_from_chart_rows,
    scenario_standby_power_kw,
)
from simulation.matrix_builder import native_filter_kw_by_slot
from simulation.plausibility import validate_window_consumption


def _pool_filter() -> dict:
    return {
        "id": "pool_filter",
        "name": "Pool-Filter",
        "nominal_power_kw": 0.18,
        "min_on_quarterhours": 2,
        "signal_type": "binary",
        "daily_target_source": "loxone_remaining_hours",
        "filter_schedule": {
            "enabled": True,
            "config_fallback": {"native_start_hour": 12, "native_duration_hours": 4.0},
        },
    }


def _slots(start: datetime, hours: int) -> list[datetime]:
    step = slot_step()
    return [start + step * i for i in range(int(hours / DEFAULT_DT_H))]


def _matrix(start: datetime, hours: int) -> list[dict]:
    return [
        {
            "hour": slot.hour,
            "date": slot.date(),
            "slot_datetime": slot,
            "expected_p_act": 0.3,
            "expected_p_pv": 0.0,
            "k_act": 20.0,
            "consumption_mode": "profile_spec",
        }
        for slot in _slots(start, hours)
    ]


# --- native filter booked as fixed load -------------------------------------------------


def test_native_filter_kw_by_slot_books_daily_duty_cycle():
    slots = _slots(datetime(2026, 5, 2, 7, 0), 24)
    native = native_filter_kw_by_slot(slots, [_pool_filter()])
    running = [slot for slot, by_id in zip(slots, native) if by_id]
    assert running[0] == datetime(2026, 5, 2, 12, 0)
    assert running[-1] == datetime(2026, 5, 2, 15, 45)
    energy = sum(by_id.get("pool_filter", 0.0) for by_id in native) * DEFAULT_DT_H
    assert energy == pytest.approx(0.72)


def test_native_filter_kw_by_slot_without_fallback_window_books_nothing():
    consumer = _pool_filter()
    consumer["filter_schedule"]["config_fallback"] = {}
    slots = _slots(datetime(2026, 5, 2, 0, 0), 24)
    assert all(not by_id for by_id in native_filter_kw_by_slot(slots, [consumer]))


def test_native_credit_limited_to_book_window():
    """48 h sunrise horizon: only the book window's native run offsets its target."""
    consumer = _pool_filter()
    matrix = _matrix(datetime(2026, 5, 1, 6, 0), 48)
    ctx = fc.resolve_filter_context(consumer, matrix, logged_simulation=True)
    book = list(range(len(matrix) // 2, len(matrix)))
    whole = fc.adjust_targets_for_native_filter(
        {"pool_filter": 1.08}, [consumer], matrix, {"pool_filter": ctx}
    )
    booked = fc.adjust_targets_for_native_filter(
        {"pool_filter": 1.08}, [consumer], matrix, {"pool_filter": ctx}, book
    )
    assert whole["pool_filter"] == pytest.approx(0.0)  # 1.08 − 2 × 0.72
    assert booked["pool_filter"] == pytest.approx(0.36)  # 1.08 − 0.72


def _chart_row(slot: datetime, prognose_kw: float, filter_kw: float = 0.0) -> dict:
    return {
        "slot_datetime": slot,
        "Verbrauch-Prognose (kW)": prognose_kw,
        "Pool-Filter (kW)": filter_kw,
        "Strompreis (Cent/kWh)": 20.0,
        "PV-Prognose (kW)": 0.0,
        "Simulierter SoC (%)": 50.0,
        "Geplante Batterie-Aktion (kW)": 0.0,
        "Steuerbefehl": "Automatik",
    }


def test_series_books_native_run_on_filter_column_not_baseload():
    slots = _slots(datetime(2026, 5, 2, 7, 0), 24)
    native = native_filter_kw_by_slot(slots, [_pool_filter()])
    rows = [
        _chart_row(slot, 0.3 + sum(by_id.values()))
        for slot, by_id in zip(slots, native)
    ]
    columns = _consumption_kw_columns_from_chart_rows(rows, [_pool_filter()])
    assert sum(columns["pool_filter_kw"]) * DEFAULT_DT_H == pytest.approx(0.72)
    assert set(columns["baseload_kw"]) == {0.3}
    assert sum(columns["consumption_kw"]) * DEFAULT_DT_H == pytest.approx(
        0.3 * 24 + 0.72
    )


def test_series_split_fails_loud_when_native_run_missing_from_prognose():
    rows = [_chart_row(datetime(2026, 5, 2, 13, 0), 0.05)]
    with pytest.raises(ValueError, match="nativen Filterlauf"):
        _consumption_kw_columns_from_chart_rows(rows, [_pool_filter()])


def test_plausibility_counts_native_run_as_filter_flex():
    slots = _slots(datetime(2026, 5, 2, 7, 0), 24)
    native = native_filter_kw_by_slot(slots, [_pool_filter()])
    rows = [
        _chart_row(slot, 0.3 + sum(by_id.values()))
        for slot, by_id in zip(slots, native)
    ]
    meta = {
        "window_end": datetime(2026, 5, 3, 7, 0),
        "consumption_source": "profile_spec",
        "spec_total_kwh": round(0.3 * 24 + 0.72, 3),
        "spec_baseload_kwh": round(0.3 * 24, 3),
        "spec_flex_targets_kwh": {"pool_filter": 0.72},
        "_flexible_consumers": [_pool_filter()],
        # Earnie target was fully covered by the native run → MILP planned 0 kWh
        "plausibility_optimized_flex_kwh": 0.0,
    }
    result = validate_window_consumption(rows, meta)
    assert result.ok
    assert result.optimized_flex_kwh == pytest.approx(0.72)
    assert result.optimized_baseload_kwh == pytest.approx(7.2)


# --- booked series totals -----------------------------------------------------------------


def _frame(start: str, slots: int, consumption_kw: float, **extra: float) -> pd.DataFrame:
    index = pd.date_range(start, periods=slots, freq=timedelta(hours=DEFAULT_DT_H))
    data = {"consumption_kw": [consumption_kw] * slots}
    for col, value in extra.items():
        data[col] = [value] * slots
    return pd.DataFrame(data, index=index)


def test_booked_totals_split_standby_and_count_each_slot_once():
    df = _frame("2026-05-01", 96, 1.026, baseload_kw=0.426, pool_filter_kw=0.6)
    duplicated = pd.concat([df, df.iloc[-8:]])
    totals = booked_consumption_totals(duplicated, standby_kw=0.026)
    assert totals["slots"] == 96
    assert totals["duplicate_slots"] == 8
    assert totals["gap_slots"] == 0
    assert totals["standby_kwh"] == pytest.approx(0.6)
    assert totals["consumption_kwh"] == pytest.approx(24.0)
    assert totals["components_kwh"] == {"baseload": 9.6, "pool_filter": 14.4}


def test_booked_totals_report_peeled_known_load_as_other():
    df = _frame("2026-05-01", 4, 2.0, baseload_kw=1.0, pool_filter_kw=0.5)
    totals = booked_consumption_totals(df, standby_kw=0.0)
    assert totals["components_kwh"]["other"] == pytest.approx(0.5)


def test_booked_totals_fail_loud_without_consumption_column():
    df = _frame("2026-05-01", 4, 1.0).rename(columns={"consumption_kw": "x"})
    with pytest.raises(ValueError, match="consumption_kw"):
        booked_consumption_totals(df, standby_kw=0.0)


def test_slot_coverage_diff_counts_unique_slots():
    scenario = _frame("2026-05-01 07:00", 8, 1.0)
    reference = _frame("2026-05-01 08:00", 8, 1.0)
    assert slot_coverage_diff(scenario, reference) == {
        "only_scenario_slots": 4,
        "only_reference_slots": 4,
    }


def test_booked_by_result_requires_standby_for_every_series():
    results = {"live": _frame("2026-05-01", 4, 1.0), "ref:live": _frame("2026-05-01", 4, 1.0)}
    with pytest.raises(ValueError, match="ref:live"):
        booked_consumption_by_result(
            results,
            standby_kw_by_result={"live": 0.0},
            reference_by_scenario={"live": "ref:live"},
        )
    booked = booked_consumption_by_result(
        results,
        standby_kw_by_result={"live": 0.0, "ref:live": 0.0},
        reference_by_scenario={"live": "ref:live"},
    )
    assert booked["live"]["reference_coverage"] == {
        "reference_id": "ref:live",
        "only_scenario_slots": 0,
        "only_reference_slots": 0,
    }
    assert "reference_coverage" not in booked["ref:live"]


def test_scenario_standby_power_sums_all_batteries(monkeypatch):
    monkeypatch.setattr(
        "simulation.engine_scenario._scenario_to_battery_params",
        lambda _params: [{"standby_power_kw": 0.026}, {"standby_power_kw": 0.013}],
    )
    assert scenario_standby_power_kw({}) == pytest.approx(0.039)


def test_reference_standby_follows_scenario_storage(monkeypatch):
    from simulation.reference_costs import reference_standby_power_kw

    monkeypatch.setattr(
        "simulation.engine_scenario._scenario_to_battery_params",
        lambda _params: {"standby_power_kw": 0.026},
    )
    assert reference_standby_power_kw({"battery_ids": ["x"]}) == pytest.approx(0.026)
    assert reference_standby_power_kw(None) == 0.0


def test_reference_standby_zero_for_stripped_historical_params():
    from house_config.entity_resolution import strip_assets_for_reference
    from simulation.reference_costs import reference_standby_power_kw

    stripped = strip_assets_for_reference({"standby_power_kw": 0.026})
    assert reference_standby_power_kw(stripped) == 0.0


# --- references evaluate the optimized run's slots -------------------------------------------


def test_reference_slots_follow_sunrise_book_step():
    from simulation.backtesting_horizon import (
        naive_backtesting_slot,
        resolve_sunrise_book_step_for_scenario,
    )
    from simulation.horizon_mode import FIXED_24H, SUNRISE_WINDOW
    from simulation.reference_costs import reference_slot_datetimes

    anchor = datetime(2025, 12, 12, 7, 0)  # Friday, ready_by before sunrise
    params = {"latitude": 47.4, "longitude": 9.7}
    book = [
        naive_backtesting_slot(slot)
        for slot in resolve_sunrise_book_step_for_scenario(anchor, params).book_slots
    ]
    assert reference_slot_datetimes(anchor, params, SUNRISE_WINDOW) == book
    fixed = reference_slot_datetimes(anchor, params, FIXED_24H)
    assert fixed[0] == anchor - timedelta(hours=24)
    assert fixed[-1] == anchor - slot_step()


def test_reference_slots_sunrise_requires_scenario_geo():
    from simulation.horizon_mode import SUNRISE_WINDOW
    from simulation.reference_costs import reference_slot_datetimes

    with pytest.raises(ValueError, match="sunrise_window"):
        reference_slot_datetimes(datetime(2025, 12, 12, 7, 0), None, SUNRISE_WINDOW)


def test_booked_totals_count_gaps_inside_the_series():
    df = _frame("2026-05-01", 96, 1.0)
    holed = df.drop(df.index[40:48])
    assert booked_consumption_totals(holed, standby_kw=0.0)["gap_slots"] == 8

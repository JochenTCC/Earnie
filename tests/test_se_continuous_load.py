"""SE: a continuous generic load (>= 24 h on every weekday) is booked as fixed load.

Regression for the Jahres Verbrauch gap between the references and the optimized
scenario (dev-pc 0.12 kW 24/7 = 1 051 kWh/a): the generic target rule never let a
24 h run end before the sunrise book window end, so the optimized run planned
0 kWh while the reference model kept the constant load.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from house_config.generic_schedule import (
    continuous_window_kwh,
    generic_flex_target_kwh_for_window,
    is_continuous_schedule,
)
from house_config.planning_flex_converters import planning_consumer_to_milp
from house_config.planning_flex_overlays import planning_flex_daily_targets
from optimizer.fixed_load import (
    adjust_targets_for_continuous_load,
    continuous_load_kw,
    fixed_load_kw_at,
    resolve_fixed_load_windows,
)
from optimizer.slot_duration import DEFAULT_DT_H, slot_step
from simulation.engine_scenario import _consumption_kw_columns_from_chart_rows
from simulation.matrix_builder import fixed_load_kw_by_slot
from simulation.plausibility import validate_window_consumption


def _dev_pc(**overrides) -> dict:
    consumer = {
        "id": "dev-pc",
        "label": "Dev-PC",
        "type": "generic",
        "nominal_power_kw": 0.12,
        "earnie_role": "manual",
        "schedule": {
            "runs_per_week": 7,
            "duration_h": 24.0,
            "start_hour": 12,
            "start_shift_h": 6.0,
        },
    }
    consumer.update(overrides)
    return consumer


def _washer() -> dict:
    return {
        "id": "waschmaschine",
        "label": "Waschmaschine",
        "type": "generic",
        "nominal_power_kw": 0.6,
        "earnie_role": "manual",
        "schedule": {"runs_per_week": 3, "duration_h": 2.0, "start_hour": 12, "start_shift_h": 6.0},
    }


SA1 = datetime(2025, 10, 1, 7, 15)
SA2 = SA1 + timedelta(days=1)


def _book_slots(start: datetime = SA1, hours: float = 24.0) -> list[datetime]:
    return [start + slot_step() * i for i in range(int(hours / DEFAULT_DT_H))]


# --- schedule classification and window target ------------------------------------------


def test_continuous_schedule_requires_daily_runs_of_at_least_24h():
    assert is_continuous_schedule(_dev_pc())
    assert not is_continuous_schedule(_washer())
    assert not is_continuous_schedule(
        _dev_pc(schedule={"runs_per_week": 5, "duration_h": 24.0, "start_hour": 12})
    )
    assert not is_continuous_schedule(
        _dev_pc(schedule={"runs_per_week": 7, "duration_h": 23.0, "start_hour": 12})
    )
    assert not is_continuous_schedule(_dev_pc(nominal_power_kw=0.0))
    assert not is_continuous_schedule(_dev_pc(type="ev"))


def test_window_target_of_continuous_load_is_nominal_times_window_hours():
    slots = _book_slots()
    assert generic_flex_target_kwh_for_window(_dev_pc(), slots, SA2) == pytest.approx(2.88)
    # The old rule (run must end before window_end) still drops a 24 h run that starts
    # at 12:00: documented as the negative control for a non-daily 24 h run.
    weekly = _dev_pc(schedule={"runs_per_week": 1, "duration_h": 24.0, "start_hour": 12})
    assert generic_flex_target_kwh_for_window(weekly, slots, SA2) == 0.0
    # Slot-aligned: a 23 h DST window books 23 h, not a calendar day.
    assert continuous_window_kwh(_dev_pc(), _book_slots(hours=23)) == pytest.approx(2.76)


def test_planning_flex_daily_targets_use_slots_for_continuous_load():
    profile = {"consumers": [_dev_pc(), _washer()]}
    flex = [planning_consumer_to_milp(_dev_pc()), planning_consumer_to_milp(_washer())]
    slots = _book_slots()
    targets = planning_flex_daily_targets(flex, profile, slots, window_end=SA2)
    assert targets["dev-pc"] == pytest.approx(2.88)
    assert targets["waschmaschine"] == pytest.approx(1.2)
    # Without an anchor the continuous load must not be counted per calendar day (2 days).
    assert planning_flex_daily_targets(flex, profile, slots)["dev-pc"] == pytest.approx(2.88)


def test_milp_consumer_carries_the_continuous_flag():
    assert planning_consumer_to_milp(_dev_pc()).get("continuous_load") is True
    assert "continuous_load" not in planning_consumer_to_milp(_washer())


# --- fixed load in the SE energy balance --------------------------------------------------


def test_fixed_load_books_continuous_load_in_every_slot():
    milp = [planning_consumer_to_milp(_dev_pc()), planning_consumer_to_milp(_washer())]
    assert continuous_load_kw(milp) == {"dev-pc": 0.12}
    slots = _book_slots()
    fixed = fixed_load_kw_by_slot(slots, milp)
    assert all(by_id == {"dev-pc": 0.12} for by_id in fixed)
    windows = resolve_fixed_load_windows(milp)
    assert windows
    assert fixed_load_kw_at(windows, slots[5]) == {"dev-pc": 0.12}
    assert not resolve_fixed_load_windows([planning_consumer_to_milp(_washer())])


def test_continuous_target_is_credited_against_the_booked_slots():
    milp = [planning_consumer_to_milp(_dev_pc()), planning_consumer_to_milp(_washer())]
    targets = {"dev-pc": 2.88, "waschmaschine": 1.2}
    credited = adjust_targets_for_continuous_load(targets, milp, credit_slots=96)
    assert credited["dev-pc"] == pytest.approx(0.0)
    assert credited["waschmaschine"] == pytest.approx(1.2)
    # Live: target 0 stays 0 (no negative credit).
    assert adjust_targets_for_continuous_load({"dev-pc": 0.0}, milp, 96)["dev-pc"] == 0.0
    assert adjust_targets_for_continuous_load(targets, [], 96) == targets


def _chart_row(slot: datetime, prognose_kw: float) -> dict:
    return {
        "slot_datetime": slot,
        "Verbrauch-Prognose (kW)": prognose_kw,
        "Dev-PC (kW)": 0.0,
        "Strompreis (Cent/kWh)": 20.0,
        "PV-Prognose (kW)": 0.0,
        "Simulierter SoC (%)": 50.0,
        "Geplante Batterie-Aktion (kW)": 0.0,
        "Steuerbefehl": "Automatik",
    }


def test_series_books_continuous_load_on_its_column_not_baseload():
    milp = [planning_consumer_to_milp(_dev_pc())]
    slots = _book_slots()
    rows = [_chart_row(slot, 0.3 + 0.12) for slot in slots]
    columns = _consumption_kw_columns_from_chart_rows(rows, milp)
    assert sum(columns["dev-pc_kw"]) * DEFAULT_DT_H == pytest.approx(2.88)
    assert set(columns["baseload_kw"]) == {0.3}


def test_series_split_fails_loud_when_continuous_load_missing_from_prognose():
    milp = [planning_consumer_to_milp(_dev_pc())]
    with pytest.raises(ValueError, match="Dauerlast"):
        _consumption_kw_columns_from_chart_rows([_chart_row(SA1, 0.05)], milp)


def test_plausibility_counts_continuous_load_as_its_flex():
    milp = [planning_consumer_to_milp(_dev_pc())]
    slots = _book_slots()
    rows = [_chart_row(slot, 0.3 + 0.12) for slot in slots]
    meta = {
        "window_end": SA2,
        "consumption_source": "profile_spec",
        "spec_total_kwh": round(0.3 * 24 + 2.88, 3),
        "spec_baseload_kwh": round(0.3 * 24, 3),
        "spec_flex_targets_kwh": {"dev-pc": 2.88},
        "_flexible_consumers": milp,
        "plausibility_optimized_flex_kwh": 0.0,
    }
    result = validate_window_consumption(rows, meta)
    assert result.ok
    assert result.optimized_flex_kwh == pytest.approx(2.88)
    assert result.optimized_baseload_kwh == pytest.approx(7.2)

"""Monitor block "Leistungspreis" (max-power tariff P6b): what the block holds per case."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from optimizer.import_cap_report import (
    CAUSE_BATTERY_ENERGY,
    CAUSE_BATTERY_POWER,
    CAUSE_FORECAST,
)
from runtime_store.capacity_peak_store import MonthPeak
from tests.test_capacity_charge import VAT_FACTOR, _charge, _params
from ui.capacity_charge_panel import build_capacity_panel, main_cause

NOW = datetime(2027, 3, 15, 12, 0)
CAP = {"import_cap_kw": 5.0, "import_cap_margin_kw": 0.3, "import_cap_mode": "optimize"}
EMPTY_REPORT = {"plan": None, "measured": {}}


def month_peak(peak_kw: float, *, month: str = "2027-03", missing: int = 0) -> MonthPeak:
    return MonthPeak(
        month=month,
        peak_kw=peak_kw,
        peak_slot=f"{month}-10T18:15:00",
        peak_source="counter",
        first_slot=f"{month}-01T00:00:00",
        last_slot=f"{month}-15T11:45:00",
        slots_logged=1300,
        slots_missing=missing,
    )


def _peaks(peak: MonthPeak | None):
    return lambda month: peak if peak is not None and peak.month == month else None


def _panel(params, peak: MonthPeak | None = None, report=EMPTY_REPORT):
    return build_capacity_panel(params, NOW, read_peak=_peaks(peak), report=report)


def test_no_cap_and_no_charge_shows_nothing(tmp_path: Path):
    assert _panel(_params(tmp_path, None)) is None


def test_a_charge_without_cap_bills_the_peak_gross(tmp_path: Path):
    panel = _panel(_params(tmp_path, [_charge()]), month_peak(5.0))
    assert panel.month == "2027-03"
    assert panel.cap is None
    assert panel.billed_kw == 5.0
    assert panel.gross_eur == pytest.approx(7.5 * VAT_FACTOR)
    assert panel.next_kw_gross_eur == pytest.approx(1.5 * VAT_FACTOR)
    assert panel.minimum_gross_eur is None
    assert panel.planning_limit_kw is None
    assert panel.plan_report is None


def test_a_peak_below_the_minimum_bills_the_minimum(tmp_path: Path):
    panel = _panel(_params(tmp_path, [_charge()]), month_peak(1.0))
    assert panel.billed_kw == 2.0
    assert panel.gross_eur == pytest.approx(3.0 * VAT_FACTOR)
    assert panel.next_kw_gross_eur == pytest.approx(1.5 * VAT_FACTOR)


def test_the_next_kw_across_a_band_limit_mixes_both_rates(tmp_path: Path):
    panel = _panel(_params(tmp_path, [_charge()]), month_peak(9.5))
    assert panel.next_kw_gross_eur == pytest.approx((0.5 * 1.5 + 0.5 * 3.0) * VAT_FACTOR)


def test_a_month_without_entry_is_unknown_not_zero(tmp_path: Path):
    panel = _panel(_params(tmp_path, [_charge()]), month_peak(4.0, month="2027-02"))
    assert panel.peak is None
    assert panel.billed_kw is None
    assert panel.gross_eur is None
    assert panel.next_kw_gross_eur is None
    assert panel.minimum_gross_eur == pytest.approx(3.0 * VAT_FACTOR)


def test_a_cap_plans_up_to_the_cap_or_the_higher_peak_less_the_margin(tmp_path: Path):
    params = {**_params(tmp_path, [_charge()]), **CAP}
    assert _panel(params, month_peak(3.0)).planning_limit_kw == pytest.approx(4.7)
    assert _panel(params, month_peak(6.0)).planning_limit_kw == pytest.approx(5.7)
    assert _panel(params, None).planning_limit_kw == pytest.approx(4.7)


def test_a_cap_before_the_charge_starts_is_inactive(tmp_path: Path):
    params = {**_params(tmp_path, [_charge(valid_from="2027-06-01")]), **CAP}
    panel = _panel(params, month_peak(3.0))
    assert panel.charge is None
    assert panel.cap_notes == ("Die Grenze bleibt inaktiv bis 06/2027: Dann beginnt der Leistungspreis.",)
    assert panel.planning_limit_kw is None
    assert panel.peak is None


def test_a_cap_below_the_minimum_is_named(tmp_path: Path):
    params = {**_params(tmp_path, [_charge(min_kw=6.0)]), **CAP}
    panel = _panel(params, month_peak(3.0))
    assert panel.has_grid_area
    assert len(panel.cap_errors) == 1
    assert "unter der Mindestleistung des Netzbereichs (6 kW)" in panel.cap_errors[0]


def test_a_cap_carries_the_plan_report_and_this_months_measured_events(tmp_path: Path):
    params = {**_params(tmp_path, [_charge()]), **CAP}
    event = {"slot": "2027-03-10T18:15", "import_kw": 6.0, "threshold_kw": 5.0, "over_kw": 1.0,
             "cause": CAUSE_FORECAST, "planned": False}
    old = {**event, "slot": "2027-02-10T18:15"}
    plan = {"planned": True, "reason": None, "first_slot": "2027-03-15T12:00", "slots": []}
    report = {"plan": plan, "measured": {"2027-02": [old], "2027-03": [event]}}
    panel = _panel(params, month_peak(6.0), report)
    assert panel.plan_report == plan
    assert panel.measured == (event,)


def test_without_a_cap_the_report_is_left_out(tmp_path: Path):
    report = {"plan": {"planned": True, "slots": []}, "measured": {"2027-03": [{"slot": "x"}]}}
    panel = _panel(_params(tmp_path, [_charge()]), month_peak(3.0), report)
    assert panel.plan_report is None
    assert panel.measured == ()


def test_a_gap_in_the_grid_areas_charges_fails_loud(tmp_path: Path):
    params = _params(tmp_path, [_charge(valid_from="2027-01-01", valid_to="2027-01-31")])
    with pytest.raises(ValueError):
        _panel(params, month_peak(3.0))


def test_main_cause_is_the_most_frequent_then_the_earliest():
    slots = [{"cause": CAUSE_BATTERY_ENERGY}, {"cause": CAUSE_BATTERY_POWER}, {"cause": CAUSE_BATTERY_POWER}]
    assert main_cause(slots) == CAUSE_BATTERY_POWER
    assert main_cause(slots[:2]) == CAUSE_BATTERY_ENERGY

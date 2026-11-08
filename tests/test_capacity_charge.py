"""Capacity charge in the SE: month peak, amount from Edibert, summary, invoice, table."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import config
from house_config.edibert_tariffs import EdibertLoadError
from house_config.scenario_resolution import resolve_scenario_settings
from simulation.backtesting_log import _build_summary, _fee_and_summary_parts
from simulation.capacity_charge import (
    CAPACITY_KEY,
    CapacityResult,
    capacity_by_result,
    capacity_for_result,
    check_capacity_coverage,
)
from simulation.monthly_fees import ScenarioFeeBreakdown
from simulation.se_invoice_markdown import render_scenario_invoice_markdown, write_se_invoices
from ui.backtesting_results_helpers import build_capacity_rows, capacity_skipped_text

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = str(REPO_ROOT / "share" / "config" / "tariffs.json")
GRID_FEES = REPO_ROOT / "share" / "config" / "grid_fees.json"
VAT_FACTOR = 1.2  # awattar_at


def _charge(**overrides) -> dict:
    """Placeholder prices: 1.50 EUR per kW up to 10 kW, 3.00 EUR above, minimum 2 kW."""
    return {
        "id": "lp_2027",
        "basis": "monthly_peak_15min",
        "min_kw": 2.0,
        "bands": [
            {"up_to_kw": 10, "cent_per_kw_month": 150},
            {"up_to_kw": None, "cent_per_kw_month": 300},
        ],
        **overrides,
    }


def _params(tmp_path: Path, charges: list[dict] | None) -> dict:
    grid_fees = tmp_path / "grid_fees.json"
    shutil.copyfile(GRID_FEES, grid_fees)
    area = {
        "id": "user_home",
        "label": "Eigen",
        "land": "AT",
        "base_cent_kwh": {"unmetered_power": 4.5, "metered_power": 4.5},
    }
    if charges is not None:
        area["capacity_charges"] = charges
    (tmp_path / "user_grid_fees.json").write_text(
        json.dumps({"tariff_format": 1, "rule_sets": {}, "areas": [area]}), encoding="utf-8"
    )
    profiles = tmp_path / "house_profiles.json"
    profiles.write_text(
        json.dumps({
            "profiles": [{
                "id": "home",
                "annual_kwh": 4000,
                "land": "AT",
                "latitude": 47.4,
                "longitude": 9.74,
                "timezone_name": "Europe/Vienna",
                "netznutzung": {"area_id": "user_home", "quarter_hour_meter": True},
                "consumers": [],
            }]
        }),
        encoding="utf-8",
    )
    return resolve_scenario_settings(
        {"house_profile_id": "home", "import_tariff_id": "awattar_at", "export_tariff_id": "dynamic_epex"},
        raw_config=config.CONFIG._raw_config,
        components_path=config.CONFIG.components_path,
        tariffs_path=CATALOG,
        house_profiles_path=str(profiles),
        grid_fees_path=str(grid_fees),
    )


def _frame(peaks_kw: dict[datetime, float], *, base_kw: float = 0.5) -> pd.DataFrame:
    """Four slots per given time: one at the peak, the others at ``base_kw``."""
    rows: dict[datetime, float] = {}
    for moment, kw in peaks_kw.items():
        for slot in range(4):
            rows[moment + timedelta(minutes=15 * slot)] = kw if slot == 1 else base_kw
    index = pd.DatetimeIndex(sorted(rows))
    import_kwh = [rows[ts.to_pydatetime()] * 0.25 for ts in index]
    return pd.DataFrame(
        {
            "sim_cost": [kwh * 0.2 for kwh in import_kwh],
            "import_cost_eur": [kwh * 0.2 for kwh in import_kwh],
            "export_earn_eur": 0.0,
            "import_kwh": import_kwh,
            "export_kwh": 0.0,
            "consumption_kw": 1.0,
            "k_act": 20.0,
            "k_push_act": 5.0,
        },
        index=index,
    )


@pytest.fixture
def params(tmp_path) -> dict:
    return _params(tmp_path, [_charge()])


JAN = datetime(2027, 1, 12, 18, 0)


@pytest.mark.parametrize(
    ("peak_kw", "billed_kw", "net_eur"),
    [
        (1.8, 2.0, 3.00),  # below the minimum
        (3.4, 3.4, 5.10),
        (5.0, 5.0, 7.50),
        (10.0, 10.0, 15.00),
        (12.0, 12.0, 21.00),  # only the share above 10 kW costs more
    ],
)
def test_month_amount_follows_peak_minimum_and_bands(params, peak_kw, billed_kw, net_eur):
    month = capacity_for_result(_frame({JAN: peak_kw}), params).months[0]
    assert month.month == "2027-01"
    assert month.peak_kw == pytest.approx(peak_kw)
    assert month.billed_kw == pytest.approx(billed_kw)
    assert month.net_eur == pytest.approx(net_eur)
    assert month.gross_eur == pytest.approx(net_eur * VAT_FACTOR)
    assert month.peak_slot == "2027-01-12T18:15:00"


def test_further_peaks_up_to_the_highest_cost_nothing(params):
    once = capacity_for_result(_frame({JAN: 3.4}), params)
    often = capacity_for_result(
        _frame({JAN: 3.4, datetime(2027, 1, 20, 18): 2.6, datetime(2027, 1, 25, 18): 3.1}), params
    )
    assert often.gross_eur == pytest.approx(once.gross_eur)


def test_each_month_starts_again(params):
    result = capacity_for_result(
        _frame({JAN: 9.0, datetime(2027, 2, 3, 18): 3.0}), params
    )
    assert [(month.month, round(month.billed_kw, 2)) for month in result.months] == [
        ("2027-01", 9.0),
        ("2027-02", 3.0),
    ]


def test_export_does_not_count_and_a_slot_counts_once(params):
    frame = _frame({JAN: 3.0})
    frame["export_kwh"] = 50.0
    double = pd.concat([frame.iloc[[1]].assign(import_kwh=2.0), frame])  # earlier booking of the slot
    assert capacity_for_result(double, params).months[0].peak_kw == pytest.approx(3.0)


def test_booked_series_stays_as_it_is(params):
    frame = _frame({JAN: 3.0})
    before = frame.copy()
    capacity_for_result(frame, params)
    pd.testing.assert_frame_equal(frame, before)


def test_no_charge_before_the_area_starts(tmp_path):
    params = _params(tmp_path, [_charge(valid_from="2027-02-01")])
    result = capacity_for_result(_frame({JAN: 3.0, datetime(2027, 2, 3, 18): 3.0}), params)
    assert [month.month for month in result.months] == ["2027-02"]
    check_capacity_coverage(params, pd.Timestamp("2027-01-01"), pd.Timestamp("2027-02-28"))


def test_gap_fails_loud_and_before_the_run(tmp_path):
    params = _params(tmp_path, [_charge(valid_from="2027-01-01", valid_to="2027-01-31")])
    with pytest.raises(EdibertLoadError, match="kein Leistungspreis für 2027-02") as exc:
        capacity_for_result(_frame({datetime(2027, 2, 3, 18): 3.0}), params)
    assert exc.value.code == "CAPACITY_CHARGE_MISSING"
    with pytest.raises(EdibertLoadError, match="2027-02"):
        check_capacity_coverage(params, pd.Timestamp("2027-01-01"), pd.Timestamp("2027-03-31"))


def test_entry_outside_include_status_is_reported_not_charged(tmp_path):
    params = _params(tmp_path, [_charge(status="entwurf")])
    result = capacity_for_result(_frame({JAN: 3.0}), params)
    assert result.months == ()
    assert result.skipped == {"lp_2027": "entwurf"}


@pytest.mark.parametrize("charges", [None, []])
def test_area_without_charge_has_no_result(tmp_path, charges):
    params = _params(tmp_path, charges)
    assert capacity_by_result({"s": _frame({JAN: 3.0})}, {"s": params}) == {}


def test_without_pricing_reference_there_is_no_charge():
    assert capacity_for_result(_frame({JAN: 3.0}), {}) == CapacityResult()
    assert capacity_for_result(_frame({JAN: 3.0}), None) == CapacityResult()
    check_capacity_coverage(None, pd.Timestamp("2027-01-01"), pd.Timestamp("2027-01-31"))


def test_summary_adds_the_month_amount_outside_sim_cost(params):
    frame = _frame({JAN: 5.0, datetime(2027, 2, 3, 18): 3.0})
    capacity = capacity_by_result({"s": frame}, {"s": params})
    without = _build_summary({"s": frame}, {"s": "S"})
    summary = _build_summary({"s": frame}, {"s": "S"}, capacity_by_scenario=capacity)
    assert summary["total_eur"]["s"] == pytest.approx(
        without["total_eur"]["s"] + (7.50 + 4.50) * VAT_FACTOR, abs=1e-3
    )
    assert summary["monthly_eur"]["2027-01"]["S"] == pytest.approx(
        without["monthly_eur"]["2027-01"]["S"] + 7.50 * VAT_FACTOR, abs=1e-3
    )
    assert summary["monthly_eur"]["2027-02"]["S"] == pytest.approx(
        without["monthly_eur"]["2027-02"]["S"] + 4.50 * VAT_FACTOR, abs=1e-3
    )


def test_log_payload_is_json_and_absent_without_charge(params):
    frame = _frame({JAN: 5.0})
    capacity = capacity_by_result({"s": frame}, {"s": params})
    parts = _fee_and_summary_parts({"s": frame}, {"s": "S"}, None, None, capacity)
    assert json.loads(json.dumps(parts))[CAPACITY_KEY]["s"]["months"][0]["month"] == "2027-01"
    assert CAPACITY_KEY not in _fee_and_summary_parts({"s": frame}, {"s": "S"}, None, None, {})


def _invoice(frame: pd.DataFrame, capacity: CapacityResult | None) -> str:
    return render_scenario_invoice_markdown(
        scenario_id="s",
        label="S",
        df=frame,
        fees=ScenarioFeeBreakdown(),
        import_spec={"vat_percent": 20.0},
        export_spec=None,
        booked_consumption={"consumption_kwh": 1.0, "standby_kwh": 0.0},
        capacity=capacity,
    )


def test_invoice_lists_year_line_month_table_and_total(params):
    frame = _frame({JAN: 12.0})
    capacity = capacity_for_result(frame, params)
    body = _invoice(frame, capacity)
    energy = float(frame["import_cost_eur"].sum())
    assert "| Leistungspreis | 25.20 € |" in body  # 21.00 EUR net + 20 % VAT
    assert "| 2027-01 | 12.00 kW | 12.00 kW | 21.00 € | 25.20 € |" in body
    assert f"| **Gesamt** | **{energy + 25.20:.2f} €** |" in body
    assert "Leistungspreis fehlt" not in body


def test_invoice_without_charge_has_no_year_line():
    body = _invoice(_frame({JAN: 3.0}), None)
    assert "| Leistungspreis |" not in body


def test_invoice_names_a_skipped_entry(tmp_path):
    params = _params(tmp_path, [_charge(status="entwurf")])
    frame = _frame({JAN: 3.0})
    body = _invoice(frame, capacity_for_result(frame, params))
    assert "Nicht berücksichtigter Leistungspreis: lp_2027 (status=entwurf)." in body
    assert "Für diesen Zeitraum gilt im Netzbereich kein Leistungspreis." in body


def test_write_invoices_uses_the_given_capacity(tmp_path, params):
    frame = _frame({JAN: 5.0})
    capacity = capacity_by_result({"s": frame}, {"s": params})
    write_se_invoices(
        log_dir=str(tmp_path),
        results={"s": frame},
        labels={"s": "S"},
        fee_breakdown_by_scenario={"s": ScenarioFeeBreakdown()},
        scenarios={"s": params},
        historical_params=None,
        historical_id="historical_reference",
        booked_consumption_by_scenario={"s": {"consumption_kwh": 1.0, "standby_kwh": 0.0}},
        capacity_by_scenario=capacity,
    )
    text = (tmp_path / "invoices" / "S_jahresrechnung.md").read_text(encoding="utf-8")
    assert "| Leistungspreis | 9.00 € |" in text


def test_table_rows_show_the_highest_month_and_the_sum(params):
    frame = _frame({JAN: 5.0, datetime(2027, 2, 3, 18): 3.0})
    capacity = capacity_by_result({"s": frame}, {"s": params})
    meta = {
        "scenario_ids": ["s"],
        "labels": {"s": "S"},
        "summary": {"total_eur": {"s": 1.0}},
        CAPACITY_KEY: {sid: item.as_dict() for sid, item in capacity.items()},
    }
    row = build_capacity_rows(meta)[0]
    assert row["Szenario"] == "S"
    assert row["Monat"] == "2027-01"
    assert "5" in row["Höchste Monatsspitze [kW]"]
    assert "14" in row["Leistungspreis [€]"]  # (7.50 + 4.50) * 1.2 = 14.40
    assert capacity_skipped_text(meta) is None


def test_table_is_empty_for_an_older_log():
    assert build_capacity_rows({"summary": {"total_eur": {"s": 1.0}}}) == []
    assert capacity_skipped_text({}) is None


def test_skipped_text_names_the_status(tmp_path):
    params = _params(tmp_path, [_charge(status="entwurf")])
    capacity = capacity_by_result({"s": _frame({JAN: 3.0})}, {"s": params})
    meta = {CAPACITY_KEY: {sid: item.as_dict() for sid, item in capacity.items()}}
    assert capacity_skipped_text(meta) == "lp_2027 (Status entwurf)"

"""Tests for SE monthly standing charges and fee breakdown (2.3.1)."""
from __future__ import annotations

import pandas as pd
import pytest

from house_config.tariffs_store import _normalize_dach_fields, resolve_supplier_id
from optimizer.simulation import calculate_step_cost_parts_from_row
from simulation.backtesting_log import _build_summary
from simulation.monthly_fees import (
    ScenarioFeeBreakdown,
    fee_breakdown_from_specs,
    monthly_fee_eur_from_params,
    monthly_fee_eur_from_specs,
    monthly_fees_by_result_id,
)
from simulation.se_invoice_markdown import (
    render_scenario_invoice_markdown,
    write_se_invoices,
)
from ui.tariff_filter_helpers import tariff_parameter_rows


def test_monthly_fee_same_supplier_uses_max() -> None:
    assert monthly_fee_eur_from_specs(
        {"supplier_id": "awattar_at", "monthly_fee_eur": 4.79},
        {"supplier_id": "awattar_at", "monthly_fee_eur": 4.79},
    ) == pytest.approx(4.79)


def test_monthly_fee_different_suppliers_sum() -> None:
    assert monthly_fee_eur_from_specs(
        {"supplier_id": "vkw", "monthly_fee_eur": 3.0},
        {"supplier_id": "oemag", "monthly_fee_eur": 1.0},
    ) == pytest.approx(4.0)
    assert monthly_fee_eur_from_specs(
        {"supplier_id": "vkw", "monthly_fee_eur": 3.0},
        None,
    ) == pytest.approx(3.0)
    assert monthly_fee_eur_from_specs(None, None) == 0.0


def test_household_fees_once_from_import() -> None:
    breakdown = fee_breakdown_from_specs(
        {
            "supplier_id": "vkw",
            "monthly_fee_eur": 3.0,
            "grid_monthly_fee_eur": 10.0,
            "metering_monthly_fee_eur": 2.5,
            "other_monthly_fee_eur": 1.0,
        },
        {
            "supplier_id": "oemag",
            "monthly_fee_eur": 1.0,
            "grid_monthly_fee_eur": 99.0,
            "metering_monthly_fee_eur": 99.0,
            "other_monthly_fee_eur": 99.0,
        },
    )
    assert breakdown.supplier_monthly_eur == pytest.approx(4.0)
    assert breakdown.grid_monthly_eur == pytest.approx(10.0)
    assert breakdown.metering_monthly_eur == pytest.approx(2.5)
    assert breakdown.other_monthly_eur == pytest.approx(1.0)
    assert breakdown.total_monthly_eur == pytest.approx(17.5)


def test_household_fees_fallback_to_export() -> None:
    breakdown = fee_breakdown_from_specs(
        {"supplier_id": "vkw", "monthly_fee_eur": 3.0},
        {
            "supplier_id": "oemag",
            "metering_monthly_fee_eur": 4.0,
        },
    )
    assert breakdown.metering_monthly_eur == pytest.approx(4.0)
    assert breakdown.total_monthly_eur == pytest.approx(7.0)


def test_monthly_fee_missing_supplier_id_raises() -> None:
    with pytest.raises(ValueError, match="supplier_id fehlt"):
        monthly_fee_eur_from_specs({"monthly_fee_eur": 1.0}, None)


def test_monthly_fee_from_params() -> None:
    params = {
        "_import_tariff_spec": {
            "supplier_id": "smartenergy",
            "monthly_fee_eur": 2.99,
        },
        "_export_tariff_spec": {},
    }
    assert monthly_fee_eur_from_params(params) == 2.99
    assert monthly_fee_eur_from_params(None) == 0.0


def test_monthly_fees_by_result_id() -> None:
    fees = monthly_fees_by_result_id(
        scenarios={
            "live": {
                "_import_tariff_spec": {
                    "supplier_id": "awattar_at",
                    "monthly_fee_eur": 4.79,
                },
                "_export_tariff_spec": {
                    "supplier_id": "awattar_at",
                    "monthly_fee_eur": 4.79,
                },
            }
        },
        historical_params={
            "_import_tariff_spec": {
                "supplier_id": "awattar_at",
                "monthly_fee_eur": 4.79,
            },
            "_export_tariff_spec": {},
        },
        historical_id="historical_reference",
        extra_ref_specs=[
            (
                "live_ref",
                {
                    "_import_tariff_spec": {
                        "supplier_id": "vkw",
                        "monthly_fee_eur": 3.0,
                    },
                    "_export_tariff_spec": {},
                },
                "Live Ref",
            )
        ],
    )
    assert fees["historical_reference"] == 4.79
    assert fees["live"] == 4.79
    assert fees["live_ref"] == 3.0


def test_build_summary_adds_full_month_fees() -> None:
    idx2 = pd.date_range("2025-01-31", periods=48, freq="h")
    df2 = pd.DataFrame({"sim_cost": [2.0] * 48}, index=idx2)
    summary = _build_summary(
        {"s1": df2},
        {"s1": "S1"},
        monthly_fee_by_scenario={"s1": 10.0},
    )
    months = summary["monthly_eur"]
    assert "2025-01" in months
    assert "2025-02" in months
    assert months["2025-01"]["S1"] == round(24 * 2.0 + 10.0, 4)
    assert months["2025-02"]["S1"] == round(24 * 2.0 + 10.0, 4)
    assert summary["total_eur"]["s1"] == round(48 * 2.0 + 2 * 10.0, 4)
    assert float(df2["sim_cost"].sum()) == 96.0


def test_build_summary_zero_fee_matches_volumetric() -> None:
    idx = pd.date_range("2025-03-01", periods=24, freq="h")
    df = pd.DataFrame({"sim_cost": [0.5] * 24}, index=idx)
    summary = _build_summary({"a": df}, {"a": "A"})
    assert summary["total_eur"]["a"] == 12.0
    assert summary["monthly_eur"]["2025-03"]["A"] == 12.0


def test_clip_results_drops_spill_months_for_fees() -> None:
    from simulation.period_clip import clip_results_to_period

    idx = pd.date_range("2025-06-30 18:00:00", periods=12, freq="h")
    df = pd.DataFrame({"sim_cost": [1.0] * 12}, index=idx)
    clipped = clip_results_to_period(df, "2025-07-01", "2025-07-31")
    assert clipped.index.min() == pd.Timestamp("2025-07-01 00:00:00")
    assert "2025-06" not in {ts.strftime("%Y-%m") for ts in clipped.index}
    summary = _build_summary(
        {"live": clipped},
        {"live": "Live"},
        monthly_fee_by_scenario={"live": 4.79},
    )
    assert list(summary["monthly_eur"].keys()) == ["2025-07"]
    assert "2025-06" not in summary["monthly_eur"]
    assert summary["total_eur"]["live"] == round(float(clipped["sim_cost"].sum()) + 4.79, 4)


def test_normalize_dach_copies_monthly_fee() -> None:
    spec: dict = {}
    _normalize_dach_fields(
        {
            "monthly_fee_eur": 5.99,
            "grid_monthly_fee_eur": 8.0,
            "metering_monthly_fee_eur": 1.5,
            "other_monthly_fee_eur": 0.5,
            "land": "DE",
        },
        spec,
    )
    assert spec["monthly_fee_eur"] == 5.99
    assert spec["grid_monthly_fee_eur"] == 8.0
    assert spec["metering_monthly_fee_eur"] == 1.5
    assert spec["other_monthly_fee_eur"] == 0.5


def test_resolve_supplier_id_legacy_awattar_pair() -> None:
    assert (
        resolve_supplier_id({}, tariff_id="awattar_at", label="aWATTar — HOURLY")
        == "awattar_at"
    )
    assert (
        resolve_supplier_id({}, tariff_id="dynamic_epex", label="aWATTar — SUNNY SPOT")
        == "awattar_at"
    )


def test_tariff_preview_shows_monthly_fee_and_supplier() -> None:
    rows = dict(
        tariff_parameter_rows(
            {
                "type": "spot_hourly",
                "settlement_fee_cent_kwh": 1.2,
                "monthly_fee_eur": 3.0,
                "grid_monthly_fee_eur": 7.0,
                "supplier_id": "vkw",
                "prices_include_vat": False,
            },
            kind="import",
        )
    )
    assert "Lieferant-Grundpreis (ca.)" in rows
    assert "3" in rows["Lieferant-Grundpreis (ca.)"]
    assert "Netzentgelt-Grundpreis (ca.)" in rows
    assert rows["Anbieter (supplier_id)"] == "vkw"


def test_step_cost_parts_import_and_export() -> None:
    import_row = {
        "Verbrauch-Prognose (kW)": 1.0,
        "Strompreis (Cent/kWh)": 20.0,
        "Netzbezug (kW)": 2.0,
        "Einspeisevergütung (Cent/kWh)": 5.0,
    }
    import_eur, export_eur, net_eur, import_kwh, export_kwh = (
        calculate_step_cost_parts_from_row(import_row)
    )
    assert import_eur == pytest.approx(0.4)
    assert export_eur == 0.0
    assert net_eur == pytest.approx(0.4)
    assert import_kwh == pytest.approx(2.0)
    assert export_kwh == 0.0

    export_row = {
        "Verbrauch-Prognose (kW)": 0.0,
        "Strompreis (Cent/kWh)": 20.0,
        "Netzbezug (kW)": -3.0,
        "Einspeisevergütung (Cent/kWh)": 10.0,
    }
    import_eur, export_eur, net_eur, import_kwh, export_kwh = (
        calculate_step_cost_parts_from_row(export_row)
    )
    assert import_eur == 0.0
    assert export_eur == pytest.approx(0.3)
    assert net_eur == pytest.approx(-0.3)
    assert import_kwh == 0.0
    assert export_kwh == pytest.approx(3.0)


def test_write_se_invoices_markdown(tmp_path) -> None:
    idx = pd.date_range("2025-01-01", periods=24, freq="h")
    df = pd.DataFrame(
        {
            "sim_cost": [1.0] * 12 + [-0.5] * 12,
            "import_cost_eur": [1.0] * 12 + [0.0] * 12,
            "export_earn_eur": [0.0] * 12 + [0.5] * 12,
            "import_kwh": [10.0] * 12 + [0.0] * 12,
            "export_kwh": [0.0] * 12 + [5.0] * 12,
            "consumption_kw": [8.0] * 24,
        },
        index=idx,
    )
    fees = ScenarioFeeBreakdown(
        supplier_monthly_eur=4.0,
        grid_monthly_eur=1.0,
        metering_monthly_eur=0.5,
        other_monthly_eur=0.0,
    )
    paths = write_se_invoices(
        log_dir=str(tmp_path),
        results={"live": df},
        labels={"live": "Live"},
        fee_breakdown_by_scenario={"live": fees},
        scenarios={
            "live": {
                "_import_tariff_spec": {
                    "id": "awattar_at",
                    "label": "aWATTar HOURLY",
                    "supplier_id": "awattar_at",
                },
                "_export_tariff_spec": {
                    "id": "dynamic_epex",
                    "label": "SUNNY SPOT",
                    "supplier_id": "awattar_at",
                },
            }
        },
        historical_params=None,
        historical_id="historical_reference",
    )
    assert len(paths) == 1
    text = (tmp_path / "invoices" / "live_jahresrechnung.md").read_text(encoding="utf-8")
    assert "Fake-Jahresrechnung — Live" in text
    assert "aWATTar HOURLY" in text
    assert "SUNNY SPOT" in text
    # 12*1.0 import - 12*0.5 export + 5.5 fees = 11.50
    assert "11.50 €" in text
    body = render_scenario_invoice_markdown(
        scenario_id="live",
        label="Live",
        df=df,
        fees=fees,
        import_spec={"id": "awattar_at", "label": "aWATTar HOURLY"},
        export_spec={"id": "dynamic_epex", "label": "SUNNY SPOT"},
    )
    assert "Energiebezug" in body
    assert "Einspeiseerlös" in body
    assert "Verbrauch (Info)" in body
    assert "| Monat | Verbrauch kWh | Bezug kWh | Bezug € | Einspeisung kWh | Einspeisung € |" in body
    assert "| 2025-01 | 192.0 | 120.0 | 12.00 | 60.0 | 6.00 |" in body

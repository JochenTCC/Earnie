# tests/test_backtesting_fingerprint.py
"""Tests für Backtesting-Konfigurations-Fingerprint."""
from __future__ import annotations

from simulation.backtesting_fingerprint import (
    _spot_export_fee_from_specs,
    compute_backtesting_fingerprint,
)


def test_fingerprint_stable_for_same_settings():
    settings = {
        "live": {"battery_capacity_kwh": 5.0, "pv_kwp": 10.0},
        "alt": {"battery_capacity_kwh": 10.0, "pv_kwp": 10.0},
    }
    fp1 = compute_backtesting_fingerprint(list(settings.keys()), settings)
    fp2 = compute_backtesting_fingerprint(list(settings.keys()), settings)
    assert fp1 == fp2


def test_fingerprint_changes_when_scenario_changes():
    base = {"battery_capacity_kwh": 5.0}
    fp_a = compute_backtesting_fingerprint(["live"], {"live": base})
    fp_b = compute_backtesting_fingerprint(
        ["live"],
        {"live": {**base, "pv_kwp": 8.0}},
    )
    assert fp_a != fp_b


def test_fingerprint_includes_import_tariff_spec():
    base_spec = {
        "id": "fixed_imp",
        "type": "fixed_cent",
        "fix_cent_kwh": 25.0,
    }
    scenario = {
        "import_tariff_type": "fixed_cent",
        "import_fixed_cent_kwh": 25.0,
        "_import_tariff_spec": dict(base_spec),
    }
    fp_a = compute_backtesting_fingerprint(["live"], {"live": scenario})
    changed = {
        **scenario,
        "_import_tariff_spec": {**base_spec, "fix_cent_kwh": 30.0},
    }
    fp_b = compute_backtesting_fingerprint(["live"], {"live": changed})
    assert fp_a != fp_b


def test_fingerprint_includes_monthly_rates_of_export_tariff():
    rates_a = ((2025, 6, 5.86),)
    rates_b = ((2025, 6, 7.10),)
    scenario_a = {"_export_tariff_spec": {"id": "monthly", "monthly_rates": rates_a}}
    scenario_b = {"_export_tariff_spec": {"id": "monthly", "monthly_rates": rates_b}}
    fp_a = compute_backtesting_fingerprint(["live"], {"live": scenario_a})
    fp_b = compute_backtesting_fingerprint(["live"], {"live": scenario_b})
    assert fp_a != fp_b


def test_fingerprint_includes_spot_export_fees_when_provided():
    scenario = {
        "import_tariff_type": "spot_hourly",
        "_export_tariff_spec": {
            "id": "dynamic_epex",
            "type": "spot_hourly",
            "feed_in_fee_factor": 0.19,
            "feed_in_fix_cent": 0.0,
        },
    }
    fees_a = _spot_export_fee_from_specs(scenario)
    fees_b = _spot_export_fee_from_specs(
        {
            **scenario,
            "_export_tariff_spec": {
                **scenario["_export_tariff_spec"],
                "feed_in_fee_factor": 0.25,
            },
        }
    )
    fp_a = compute_backtesting_fingerprint(
        ["live"],
        {"live": scenario},
        awattar_pricing=fees_a,
    )
    fp_b = compute_backtesting_fingerprint(
        ["live"],
        {"live": scenario},
        awattar_pricing=fees_b,
    )
    assert fp_a != fp_b


def test_fingerprint_ignores_unrelated_private_keys():
    scenario_a = {"battery_capacity_kwh": 5.0, "_house_profile": {"id": "home_a"}}
    scenario_b = {"battery_capacity_kwh": 5.0, "_house_profile": {"id": "home_b"}}
    fp_a = compute_backtesting_fingerprint(["live"], {"live": scenario_a})
    fp_b = compute_backtesting_fingerprint(["live"], {"live": scenario_b})
    assert fp_a == fp_b


def test_fingerprint_changes_when_own_reference_changes():
    settings = {"live": {"battery_capacity_kwh": 5.0, "pv_kwp": 10.0}}
    fp_auto = compute_backtesting_fingerprint(["live"], settings)
    fp_forced = compute_backtesting_fingerprint(
        ["live"],
        settings,
        own_reference_by_id={"live": True},
    )
    fp_off = compute_backtesting_fingerprint(
        ["live"],
        settings,
        own_reference_by_id={"live": False},
    )
    assert fp_auto != fp_forced
    assert fp_forced != fp_off

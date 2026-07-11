# tests/test_backtesting_fingerprint.py
"""Tests für Backtesting-Konfigurations-Fingerprint."""
from __future__ import annotations

from simulation.backtesting_fingerprint import (
    _awattar_pricing_from_specs,
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


def test_fingerprint_includes_monthly_fixed_tariffs():
    rates_a = [{"year": 2025, "month": 6, "tariff_cent_kwh": 5.86}]
    rates_b = [{"year": 2025, "month": 6, "tariff_cent_kwh": 7.10}]
    scenario_a = {
        "feed_in_mode": "fixed",
        "_monthly_fixed_tariffs": rates_a,
    }
    scenario_b = {
        "feed_in_mode": "fixed",
        "_monthly_fixed_tariffs": rates_b,
    }
    fp_a = compute_backtesting_fingerprint(["live"], {"live": scenario_a})
    fp_b = compute_backtesting_fingerprint(["live"], {"live": scenario_b})
    assert fp_a != fp_b


def test_fingerprint_includes_awattar_pricing_when_provided():
    scenario = {
        "import_tariff_type": "awattar",
        "_import_tariff_spec": {
            "id": "awattar_at",
            "type": "awattar",
            "fix_aufschlag_cent": 1.5,
            "netzverlust_faktor": 1.03,
            "mwst_austria_faktor": 1.2,
        },
    }
    awattar_a = _awattar_pricing_from_specs(scenario)
    awattar_b = _awattar_pricing_from_specs(
        {
            **scenario,
            "_import_tariff_spec": {
                **scenario["_import_tariff_spec"],
                "fix_aufschlag_cent": 2.0,
            },
        }
    )
    fp_a = compute_backtesting_fingerprint(
        ["live"],
        {"live": scenario},
        awattar_pricing=awattar_a,
    )
    fp_b = compute_backtesting_fingerprint(
        ["live"],
        {"live": scenario},
        awattar_pricing=awattar_b,
    )
    assert fp_a != fp_b


def test_fingerprint_ignores_unrelated_private_keys():
    scenario_a = {"battery_capacity_kwh": 5.0, "_house_profile": {"id": "home_a"}}
    scenario_b = {"battery_capacity_kwh": 5.0, "_house_profile": {"id": "home_b"}}
    fp_a = compute_backtesting_fingerprint(["live"], {"live": scenario_a})
    fp_b = compute_backtesting_fingerprint(["live"], {"live": scenario_b})
    assert fp_a == fp_b

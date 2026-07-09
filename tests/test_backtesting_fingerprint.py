# tests/test_backtesting_fingerprint.py
"""Tests für Backtesting-Konfigurations-Fingerprint."""
from __future__ import annotations

from simulation.backtesting_fingerprint import compute_backtesting_fingerprint


def test_fingerprint_stable_for_same_settings():
    settings = {
        "runtime_settings": {"battery_capacity_kwh": 5.0, "pv_kwp": 10.0},
        "alt": {"battery_capacity_kwh": 10.0, "pv_kwp": 10.0},
    }
    fp1 = compute_backtesting_fingerprint(list(settings.keys()), settings)
    fp2 = compute_backtesting_fingerprint(list(settings.keys()), settings)
    assert fp1 == fp2


def test_fingerprint_changes_when_scenario_changes():
    base = {"battery_capacity_kwh": 5.0}
    fp_a = compute_backtesting_fingerprint(["runtime_settings"], {"runtime_settings": base})
    fp_b = compute_backtesting_fingerprint(
        ["runtime_settings"],
        {"runtime_settings": {**base, "pv_kwp": 8.0}},
    )
    assert fp_a != fp_b

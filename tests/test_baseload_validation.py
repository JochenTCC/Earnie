"""Tests für konsistente Grundlast-Ableitung und Plausibilitätsprüfung."""
from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from simulation.baseload_validation import (
    derive_historical_baseload_kwh,
    resolve_hourly_baseload_kw,
)
from simulation.engine import validate_window_consumption


class TestDeriveHistoricalBaseload:
    def test_total_minus_flex(self):
        assert derive_historical_baseload_kwh(
            20.71, {"swimspa": 11.66, "eauto": 0.0}
        ) == pytest.approx(9.05)


class TestResolveHourlyBaseload:
    def test_scales_when_flex_exceeds_total_in_one_hour(self):
        total = [1.555] + [0.5] * 23
        flex = [3.815] + [0.0] * 23
        hourly, baseload_sum = resolve_hourly_baseload_kw(total, flex)
        assert baseload_sum == pytest.approx(sum(total) - sum(flex))
        assert sum(hourly) == pytest.approx(baseload_sum)
        assert all(value >= 0.0 for value in hourly)

    def test_requires_equal_length(self):
        with pytest.raises(ValueError, match="gleich lang"):
            resolve_hourly_baseload_kw([1.0, 2.0], [1.0])


class TestValidateWindowConsumption:
    def test_ok_when_baseload_and_flex_match(self):
        meta = {
            "window_end": datetime(2025, 8, 11, 7, 0),
            "historical_total_kwh": 20.71,
            "baseload_kwh": 9.05,
            "historical_totals": {"swimspa": 11.66, "eauto": 0.0},
        }
        rows = [
            {
                "Verbrauch-Prognose (kW)": 9.05 / 24,
                "SwimSpa (kW)": 11.66 / 24,
                "E-Auto (kW)": 0.0,
                "Wärmepumpe (kW)": 0.0,
            }
        ] * 24
        # Skaliere auf exakte Summen
        rows[0]["Verbrauch-Prognose (kW)"] = 9.05 - sum(
            r["Verbrauch-Prognose (kW)"] for r in rows[1:]
        )
        rows[0]["SwimSpa (kW)"] = 11.66 - sum(r["SwimSpa (kW)"] for r in rows[1:])

        result = validate_window_consumption(rows, meta)
        assert result.ok
        assert result.baseload_diff_kwh == pytest.approx(0.0, abs=0.5)
        assert result.flex_diff_kwh == pytest.approx(0.0, abs=0.5)

    def test_fails_on_flex_only_mismatch(self):
        meta = {
            "window_end": datetime(2025, 8, 2, 10, 0),
            "historical_total_kwh": 25.38,
            "baseload_kwh": 8.85,
            "historical_totals": {"swimspa": 11.86, "eauto": 6.16},
        }
        rows = [
            {
                "Verbrauch-Prognose (kW)": 8.85 / 24,
                "SwimSpa (kW)": 11.86 / 24,
                "E-Auto (kW)": 3.5 / 24,
                "Wärmepumpe (kW)": 0.0,
            }
        ] * 24
        result = validate_window_consumption(rows, meta)
        assert not result.ok
        assert result.flex_diff_kwh is not None
        assert result.flex_diff_kwh > 0.5

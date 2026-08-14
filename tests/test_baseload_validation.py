"""Tests für konsistente Grundlast-Ableitung und Plausibilitätsprüfung."""
from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from optimizer.slot_duration import DEFAULT_DT_H, energy_kwh_from_kw, slots_for_wall_hours
from simulation.baseload_validation import (
    baseload_kwh_from_chart_rows,
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
        target_kw = sum(total) - sum(flex)
        assert baseload_sum == pytest.approx(target_kw * DEFAULT_DT_H)
        assert sum(hourly) == pytest.approx(target_kw)
        assert all(value >= 0.0 for value in hourly)

    def test_requires_equal_length(self):
        with pytest.raises(ValueError, match="gleich lang"):
            resolve_hourly_baseload_kw([1.0, 2.0], [1.0])


class TestBaseloadFromChartRows:
    def test_includes_known_generic_columns_after_chart_peel(self):
        rows = [
            {"Verbrauch-Prognose (kW)": 0.063, "Fernsehen (kW)": 0.2, "Smart (kW)": 1.0},
            {"Verbrauch-Prognose (kW)": 0.063, "Kochen (kW)": 2.0, "Smart (kW)": 1.0},
        ]
        flex = [{"id": "ev", "name": "Smart"}]
        assert baseload_kwh_from_chart_rows(rows) == pytest.approx(
            energy_kwh_from_kw([0.063, 0.063])
        )
        assert baseload_kwh_from_chart_rows(rows, flexible_consumers=flex) == pytest.approx(
            energy_kwh_from_kw([0.063 + 0.2, 0.063 + 2.0])
        )


class TestValidateWindowConsumption:
    def test_ok_when_baseload_and_flex_match(self):
        meta = {
            "window_end": datetime(2025, 8, 11, 7, 0),
            "historical_total_kwh": 20.71,
            "baseload_kwh": 9.05,
            "historical_totals": {"swimspa": 11.66, "eauto": 0.0},
        }
        n = slots_for_wall_hours(24)
        rows = [
            {
                "Verbrauch-Prognose (kW)": 9.05 / 24,
                "SwimSpa (kW)": 11.66 / 24,
                "E-Auto (kW)": 0.0,
                "Wärmepumpe (kW)": 0.0,
            }
        ] * n
        # Skaliere auf exakte Energiesummen (sum(kW) * dt_h)
        rows[0]["Verbrauch-Prognose (kW)"] = 9.05 / DEFAULT_DT_H - sum(
            r["Verbrauch-Prognose (kW)"] for r in rows[1:]
        )
        rows[0]["SwimSpa (kW)"] = 11.66 / DEFAULT_DT_H - sum(
            r["SwimSpa (kW)"] for r in rows[1:]
        )

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
        n = slots_for_wall_hours(24)
        rows = [
            {
                "Verbrauch-Prognose (kW)": 8.85 / 24,
                "SwimSpa (kW)": 11.86 / 24,
                "E-Auto (kW)": 3.5 / 24,
                "Wärmepumpe (kW)": 0.0,
            }
        ] * n
        result = validate_window_consumption(rows, meta)
        assert not result.ok
        assert result.flex_diff_kwh is not None
        assert result.flex_diff_kwh > 0.5

    def test_standby_in_verbrauch_prognose_does_not_fail(self):
        """ESS standby is in Verbrauch-Prognose but not in cons_data baseload."""
        standby = 0.026
        house_kwh = 6.276
        n = slots_for_wall_hours(24)
        house_kw = house_kwh / 24.0
        meta = {
            "window_end": datetime(2026, 3, 2, 7, 0),
            "historical_total_kwh": house_kwh,
            "baseload_kwh": house_kwh,
            "historical_totals": {},
            "standby_power_kw": standby,
        }
        rows = [{"Verbrauch-Prognose (kW)": house_kw + standby}] * n
        result = validate_window_consumption(rows, meta)
        assert result.ok
        assert result.baseload_diff_kwh == pytest.approx(0.0, abs=0.05)


class TestPlanningFlexPlausibility:
    def test_delivered_flex_uses_planning_consumers(self):
        from optimizer.simulation import delivered_flex_kwh_from_rows

        planning = [{"id": "swimspa", "name": "Swimspa"}]
        rows = [{"Swimspa (kW)": 2.8, "Verbrauch-Prognose (kW)": 1.0}] * 2
        delivered = delivered_flex_kwh_from_rows(rows, flexible_consumers=planning)
        assert delivered["swimspa"] == pytest.approx(2.8 * 2 * DEFAULT_DT_H)

    def test_validate_uses_stashed_full_horizon_flex(self):
        planning = [{"id": "ev", "name": "Smart"}]
        meta = {
            "window_end": datetime(2026, 3, 3, 7, 0),
            "historical_total_kwh": 30.0,
            "baseload_kwh": 22.0,
            "historical_totals": {"ev": 8.0},
            "_flexible_consumers": planning,
            "plausibility_optimized_flex_kwh": 8.0,
        }
        # Book rows only show WP-less / no EV (as after SA₁ cut).
        # Single-row energy = kW * dt_h → scale power so baseload energy is 22 kWh.
        rows = [
            {
                "Verbrauch-Prognose (kW)": 22.0 / DEFAULT_DT_H,
                "Smart (kW)": 0.0,
            }
        ]
        result = validate_window_consumption(rows, meta)
        assert result.ok
        assert result.optimized_flex_kwh == pytest.approx(8.0)
        assert result.flex_diff_kwh == pytest.approx(0.0, abs=0.05)

    def test_ok_when_known_generics_peeled_from_baseload_column(self):
        meta = {
            "window_end": datetime(2025, 12, 15, 7, 0),
            "consumption_source": "profile_spec",
            "spec_total_kwh": 12.712,
            "spec_baseload_kwh": 4.712,
            "spec_flex_targets_kwh": {"ev": 8.0},
            "historical_total_kwh": 12.712,
            "baseload_kwh": 4.712,
            "consumer_daily_targets_kwh": {"ev": 8.0},
            "_flexible_consumers": [{"id": "ev", "name": "Smart"}],
        }
        # Scale kW so energy (kW * dt_h) matches the historical kWh targets.
        rows = [
            {
                "Verbrauch-Prognose (kW)": 2.512 / DEFAULT_DT_H,
                "Fernsehen (kW)": 0.2 / DEFAULT_DT_H,
                "Kochen (kW)": 2.0 / DEFAULT_DT_H,
                "Smart (kW)": 8.0 / DEFAULT_DT_H,
            }
        ]
        result = validate_window_consumption(rows, meta)
        assert result.ok
        assert result.baseload_diff_kwh == pytest.approx(0.0, abs=0.05)
        assert result.flex_diff_kwh == pytest.approx(0.0, abs=0.05)

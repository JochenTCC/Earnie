"""profile_spec must honor use_profile_csv for thermal_rc overlay and flex targets."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from data.consumption_profiles import modeled_consumer_kw_at_datetime
from house_config.consumption_csv import write_canonical_hourly_csv
from house_config.planning_flex_bridge import (
    collect_planning_flex_consumers,
    house_profile_baseload_overlay,
    milp_flex_thermal_annual_ids,
    planning_ev_daily_targets,
    planning_thermal_daily_targets,
    profile_flat_baseload_kw,
    resolve_profile_spec_flex_targets,
)


def _hourly_csv(path: Path, start: datetime, hours: int, power: float) -> None:
    rows = [
        ((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), power)
        for i in range(hours)
    ]
    write_canonical_hourly_csv(str(path), rows)


def test_modeled_kw_prefers_csv_over_climate(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "ev.csv"
    start = datetime(2025, 6, 14, 0, 0)
    _hourly_csv(path, start, 24, 3.0)
    consumer = {
        "id": "ev",
        "type": "ev",
        "profile_csv": str(path),
        "use_profile_csv": True,
        "nominal_power_kw": 11.0,
        "charging_schedule": {
            "weekday": {"car_available_from_hour": 18, "ready_by_hour": 7, "daily_rest_soc": 30.0},
            "weekend": {"car_available_from_hour": 18, "ready_by_hour": 7, "daily_rest_soc": 30.0},
            "target_soc_percent": 100.0,
            "charging_efficiency": 0.95,
        },
        "battery_capacity_kwh": 40.0,
    }

    class _Climate:
        def thermal_rc_consumer_kw_at(self, *_a, **_k):
            return 99.0

        def thermal_consumer_kw_at(self, *_a, **_k):
            return 99.0

    assert modeled_consumer_kw_at_datetime(
        consumer, start + timedelta(hours=5), climate=_Climate()
    ) == pytest.approx(3.0)


def test_csv_thermal_rc_in_overlay_not_milp_flex(tmp_path: Path) -> None:
    path = tmp_path / "swim.csv"
    start = datetime(2025, 6, 14, 7, 0)
    _hourly_csv(path, start, 48, 2.5)
    profile = {
        "id": "home",
        "baseload_kwh": 876.0,
        "consumers": [
            {
                "id": "swimspa",
                "type": "thermal_rc",
                "nominal_power_kw": 2.8,
                "profile_csv": str(path),
                "use_profile_csv": True,
                "thermal_rc": {
                    "setpoint_c": 38.0,
                    "tolerance_c": 1.0,
                    "water_volume_liters": 5000.0,
                    "heat_loss_kw_per_k": 0.05,
                    "heating_efficiency": 1.0,
                },
            }
        ],
    }
    flex = collect_planning_flex_consumers(profile)
    flex_ids = {c["id"] for c in flex}
    assert "swimspa" not in flex_ids
    # CSV SwimSpa meter already includes filter; do not add bridge filter flex.
    assert "pool_filter" not in flex_ids

    slots = [start + timedelta(hours=i) for i in range(24)]
    overlay = house_profile_baseload_overlay(
        profile,
        slots,
        historical_totals=None,
        cons_data_consumer_ids=set(),
        milp_flex_thermal_ids=milp_flex_thermal_annual_ids(flex),
    )
    flat = profile_flat_baseload_kw(profile)
    assert sum(overlay) == pytest.approx(2.5 * 24, rel=1e-6)
    assert sum(flat + o for o in overlay) == pytest.approx(flat * 24 + 2.5 * 24)


def test_ev_and_thermal_targets_use_csv_window(tmp_path: Path) -> None:
    start = datetime(2025, 6, 14, 7, 0)
    ev_csv = tmp_path / "ev.csv"
    wp_csv = tmp_path / "wp.csv"
    _hourly_csv(ev_csv, start, 48, 1.0)
    _hourly_csv(wp_csv, start, 48, 0.5)
    profile = {
        "id": "home",
        "baseload_kwh": 876.0,
        "consumers": [
            {
                "id": "ev",
                "type": "ev",
                "nominal_power_kw": 11.0,
                "min_power_kw": 1.4,
                "battery_capacity_kwh": 40.0,
                "profile_csv": str(ev_csv),
                "use_profile_csv": True,
                "charging_schedule": {
                    "target_soc_percent": 100.0,
                    "charging_efficiency": 0.95,
                    "weekday": {
                        "car_available_from_hour": 18,
                        "ready_by_hour": 7,
                        "daily_rest_soc": 30.0,
                    },
                    "weekend": {
                        "car_available_from_hour": 18,
                        "ready_by_hour": 7,
                        "daily_rest_soc": 30.0,
                    },
                },
            },
            {
                "id": "wp_heating",
                "type": "thermal_annual",
                "nominal_power_kw": 5.0,
                "profile_csv": str(wp_csv),
                "use_profile_csv": True,
                "thermal": {
                    "heat_demand_kwh_a": 10000.0,
                    "cop": 3.0,
                },
            },
        ],
    }
    slots = [start + timedelta(hours=i) for i in range(24)]
    flex = collect_planning_flex_consumers(profile)
    targets = resolve_profile_spec_flex_targets(flex, profile, slots, window_end=slots[-1])
    assert targets["ev"] == pytest.approx(24.0)
    assert targets["wp_heating"] == pytest.approx(12.0)
    assert planning_ev_daily_targets(flex, profile, slots, window_end=slots[-1])[
        "ev"
    ] == pytest.approx(24.0)
    assert planning_thermal_daily_targets(flex, profile, slots)[
        "wp_heating"
    ] == pytest.approx(12.0)


def test_non_csv_thermal_rc_in_profile_spec_targets(monkeypatch) -> None:
    """Without use_profile_csv, thermal_rc stays MILP-flex and must get window kWh."""
    from house_config.planning_flex_bridge import planning_thermal_rc_daily_targets

    start = datetime(2025, 6, 14, 7, 0)
    profile = {
        "id": "home",
        "baseload_kwh": 876.0,
        "consumers": [
            {
                "id": "swimspa",
                "type": "thermal_rc",
                "nominal_power_kw": 2.8,
                "use_profile_csv": False,
                "thermal_rc": {
                    "setpoint_c": 38.0,
                    "tolerance_c": 1.0,
                    "water_volume_liters": 5000.0,
                    "heat_loss_kw_per_k": 0.05,
                    "heating_efficiency": 1.0,
                },
            }
        ],
    }
    slots = [start + timedelta(hours=i) for i in range(24)]
    monkeypatch.setattr(
        "data.consumption_profiles.modeled_consumer_kw_at_datetime",
        lambda *_a, **_k: 1.5,
    )
    flex = collect_planning_flex_consumers(profile)
    assert "swimspa" in {c["id"] for c in flex}
    rc_targets = planning_thermal_rc_daily_targets(flex, profile, slots)
    assert rc_targets["swimspa"] == pytest.approx(36.0)
    targets = resolve_profile_spec_flex_targets(flex, profile, slots, window_end=slots[-1])
    assert targets["swimspa"] == pytest.approx(36.0)
    assert "pool_filter" not in targets

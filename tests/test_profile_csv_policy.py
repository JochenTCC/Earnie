"""Tests for profile CSV A/B gate and balance derive."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from house_config.consumption_csv import (
    derive_total_from_balance,
    write_canonical_hourly_csv,
)
from house_config.planning_flex_bridge import (
    collect_planning_flex_consumers,
    fixed_generic_hourly_overlay,
    monthly_residual_baseload_kw,
    planning_flex_daily_targets,
    profile_flat_baseload_kw,
    split_planning_generic_consumers,
)
from house_config.profile_csv_policy import (
    controllable_generics,
    se_uses_meter_residual_baseload,
    se_uses_monthly_baseload,
)


def _hourly_csv(path: Path, start: datetime, hours: int, power: float) -> None:
    rows = [
        ((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), power)
        for i in range(hours)
    ]
    write_canonical_hourly_csv(str(path), rows)


def test_se_uses_meter_residual_requires_controllable_csv(tmp_path: Path) -> None:
    total = tmp_path / "total.csv"
    _hourly_csv(total, datetime(2025, 1, 1), 24, 5.0)
    flex_csv = tmp_path / "flex.csv"
    _hourly_csv(flex_csv, datetime(2025, 1, 1), 24, 1.0)
    profile = {
        "total_profile_csv": str(total),
        "consumers": [
            {
                "id": "wm",
                "type": "generic",
                "earnie_role": "flex",
                "nominal_power_kw": 2.0,
                "schedule": {
                    "runs_per_week": 3,
                    "duration_h": 2.0,
                    "start_hour": 8,
                    "start_shift_h": 4.0,
                },
            }
        ],
    }
    assert controllable_generics(profile)
    assert not se_uses_meter_residual_baseload(profile)
    profile["consumers"][0]["profile_csv"] = str(flex_csv)
    profile["consumers"][0]["use_profile_csv"] = True
    assert se_uses_meter_residual_baseload(profile)


def test_se_uses_monthly_baseload_when_not_path_b(tmp_path: Path) -> None:
    total = tmp_path / "total.csv"
    rows = []
    start = datetime(2025, 1, 1)
    for i in range(24):
        rows.append(((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), 3.0))
    start_feb = datetime(2025, 2, 1)
    for i in range(24):
        rows.append(
            ((start_feb + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), 0.5)
        )
    write_canonical_hourly_csv(str(total), rows)
    flex_blocker = {
        "id": "wm",
        "type": "generic",
        "earnie_role": "flex",
        "nominal_power_kw": 2.0,
        "schedule": {
            "runs_per_week": 3,
            "duration_h": 2.0,
            "start_hour": 8,
            "start_shift_h": 4.0,
        },
    }
    profile = {
        "baseload_kwh": 8760.0,
        "baseload_distribution": "monthly",
        "total_profile_csv": str(total),
        "consumers": [flex_blocker],
    }
    assert not se_uses_meter_residual_baseload(profile)
    assert se_uses_monthly_baseload(profile)
    profile["baseload_distribution"] = "equal"
    assert not se_uses_monthly_baseload(profile)
    profile["baseload_distribution"] = "monthly"
    # Path B wins over monthly when all controllable have CSV
    flex_csv = tmp_path / "flex.csv"
    _hourly_csv(flex_csv, start, 48, 1.0)
    profile["consumers"][0]["profile_csv"] = str(flex_csv)
    profile["consumers"][0]["use_profile_csv"] = True
    assert se_uses_meter_residual_baseload(profile)
    assert not se_uses_monthly_baseload(profile)


def test_monthly_residual_baseload_kw_shapes_months(tmp_path: Path) -> None:
    total = tmp_path / "total.csv"
    rows = []
    start = datetime(2025, 1, 1)
    for i in range(24):
        rows.append(((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), 3.0))
    start_feb = datetime(2025, 2, 1)
    for i in range(24):
        rows.append(
            ((start_feb + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), 0.5)
        )
    write_canonical_hourly_csv(str(total), rows)
    profile = {
        "baseload_kwh": 8760.0,
        "baseload_distribution": "monthly",
        "total_profile_csv": str(total),
        "consumers": [],
    }
    slots = [start + timedelta(hours=i) for i in range(24)] + [
        start_feb + timedelta(hours=i) for i in range(24)
    ]
    series = monthly_residual_baseload_kw(profile, slots)
    assert series[:24] == pytest.approx([3.0] * 24)
    assert series[24:] == pytest.approx([0.5] * 24)
    assert series[0] != pytest.approx(profile_flat_baseload_kw(profile))


def test_manual_is_milp_flex_not_fixed_overlay() -> None:
    profile = {
        "consumers": [
            {
                "id": "dryer",
                "type": "generic",
                "earnie_role": "manual",
                "nominal_power_kw": 2.0,
                "schedule": {
                    "runs_per_week": 2,
                    "duration_h": 1.5,
                    "start_hour": 10,
                    "start_shift_h": 6.0,
                },
                "appliance_recommendation": {"default_runtime_h": 1.5},
            }
        ]
    }
    fixed, flex = split_planning_generic_consumers(profile)
    assert fixed == []
    assert len(flex) == 1
    assert flex[0]["id"] == "dryer"
    collected = collect_planning_flex_consumers(profile)
    assert any(c["id"] == "dryer" for c in collected)


def test_flex_targets_use_csv_window(tmp_path: Path) -> None:
    path = tmp_path / "wm.csv"
    start = datetime(2025, 6, 14, 0, 0)
    _hourly_csv(path, start, 24, 2.0)
    profile = {
        "consumers": [
            {
                "id": "wm",
                "type": "generic",
                "earnie_role": "flex",
                "nominal_power_kw": 2.0,
                "profile_csv": str(path),
                "use_profile_csv": True,
                "schedule": {
                    "runs_per_week": 7,
                    "duration_h": 1.0,
                    "start_hour": 8,
                    "start_shift_h": 4.0,
                },
            }
        ]
    }
    from optimizer.slot_duration import slots_for_wall_hours, slot_step

    step = slot_step()
    slots = [start + step * i for i in range(slots_for_wall_hours(24))]
    flex = collect_planning_flex_consumers(profile)
    targets = planning_flex_daily_targets(flex, profile, slots, window_end=slots[-1])
    assert targets["wm"] == pytest.approx(48.0)


def test_known_csv_overlay_uses_csv_not_schedule(tmp_path: Path) -> None:
    path = tmp_path / "known.csv"
    start = datetime(2025, 6, 14, 0, 0)
    _hourly_csv(path, start, 24, 3.0)
    profile = {
        "consumers": [
            {
                "id": "fridge",
                "type": "generic",
                "earnie_role": "known",
                "nominal_power_kw": 0.1,
                "profile_csv": str(path),
                "use_profile_csv": True,
                "schedule": {
                    "runs_per_week": 7,
                    "duration_h": 1.0,
                    "start_hour": 0,
                    "start_shift_h": 0.0,
                },
            }
        ]
    }
    slots = [start + timedelta(hours=i) for i in range(3)]
    overlay = fixed_generic_hourly_overlay(
        profile, slots, meter_residual_mode=False
    )
    assert overlay[0] == pytest.approx(3.0)


def test_derive_total_from_balance_signs_and_clip() -> None:
    rows_pv = [("2025-01-01 00:00:00", 2.0), ("2025-01-01 01:00:00", 1.0)]
    rows_batt = [("2025-01-01 00:00:00", 1.0), ("2025-01-01 01:00:00", -3.0)]
    rows_grid = [("2025-01-01 00:00:00", 0.5), ("2025-01-01 01:00:00", 0.5)]
    total, clipped = derive_total_from_balance(rows_pv, rows_batt, rows_grid)
    assert total[0][1] == pytest.approx(3.5)
    assert total[1][1] == pytest.approx(0.0)  # 1 - 3 + 0.5 = -1.5 → clip
    assert clipped == 1


def test_derive_total_from_balance_without_battery() -> None:
    rows_pv = [("2025-01-01 00:00:00", 2.0), ("2025-01-01 01:00:00", 1.0)]
    rows_grid = [("2025-01-01 00:00:00", 0.5), ("2025-01-01 01:00:00", -0.25)]
    total, clipped = derive_total_from_balance(rows_pv, None, rows_grid)
    assert len(total) == 2
    assert total[0][1] == pytest.approx(2.5)
    assert total[1][1] == pytest.approx(0.75)
    assert clipped == 0
    total_empty, _ = derive_total_from_balance(rows_pv, [], rows_grid)
    assert total_empty == total


def test_energiemonitor_balance_without_verbrauch(tmp_path: Path) -> None:
    from house_config.consumption_csv import (
        import_energiemonitor_balance_to_canonical,
        load_hourly_profile_csv,
    )

    path = tmp_path / "em.csv"
    start = datetime(2023, 1, 1)
    lines = [
        "Datum;Zeit;Leistung Produktion [kW];"
        "Leistung Energieversorger [kW];Leistung Batterie"
    ]
    for i in range(48):
        ts = start + timedelta(hours=i)
        lines.append(
            f"{ts.strftime('%d.%m.%Y')};{ts.strftime('%H:%M:%S')};1,000;0,500;0,250"
        )
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    result = import_energiemonitor_balance_to_canonical(
        str(path),
        verbrauch_dest=str(tmp_path / "t.csv"),
        pv_dest=str(tmp_path / "p.csv"),
        battery_dest=str(tmp_path / "b.csv"),
        grid_dest=str(tmp_path / "g.csv"),
    )
    rows = load_hourly_profile_csv(str(result["total_profile_csv"]))
    assert rows[0][1] == pytest.approx(1.75)
    assert result["clipped_hours"] == 0

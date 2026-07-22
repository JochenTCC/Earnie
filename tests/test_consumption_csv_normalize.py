"""Tests for house-profile consumption CSV detect/normalize pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from house_config.consumption_csv import (
    MIN_HOURS_FULL_YEAR,
    consumer_uses_profile_csv,
    is_digital_on_off_series,
    load_and_normalize_profile_csv,
    load_hourly_profile_csv,
    normalize_hourly_power_kw,
    normalize_profile_csv_file,
    profile_csv_looks_digital,
    write_canonical_hourly_csv,
)


def _write_canonical_hours(path: Path, hours: int, *, power_kw: float = 1.5) -> None:
    start = datetime(2023, 1, 1)
    rows = [
        ((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), power_kw)
        for i in range(hours)
    ]
    write_canonical_hourly_csv(str(path), rows)


def test_load_hourly_profile_csv_canonical(tmp_path: Path) -> None:
    path = tmp_path / "hourly.csv"
    _write_canonical_hours(path, 48, power_kw=2.0)
    rows = load_hourly_profile_csv(str(path))
    assert len(rows) == 48
    assert rows[0][1] == pytest.approx(2.0)


def test_normalize_15min_mean(tmp_path: Path) -> None:
    path = tmp_path / "qtr.csv"
    start = datetime(2023, 1, 1)
    lines = ["timestamp;power_kw"]
    for i in range(MIN_HOURS_FULL_YEAR * 4):
        ts = start + timedelta(minutes=15 * i)
        lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')};1,0")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = load_and_normalize_profile_csv(str(path))
    assert len(rows) >= MIN_HOURS_FULL_YEAR
    assert rows[0][1] == pytest.approx(1.0)


def test_normalize_15min_energy_conserved() -> None:
    """Regular 15-min samples: hour mean equals mean of four samples when hour is closed."""
    from data.loxone_csv_timeseries import resample_to_hourly_zoh

    start = datetime(2023, 1, 1)
    powers = [2.0, 4.0, 6.0, 8.0]
    idx = [start + timedelta(minutes=15 * i) for i in range(4)]
    # Close the hour so ZOH covers :45–:59 (same pattern as continuous meter logs).
    idx.append(start + timedelta(hours=1))
    series = pd.Series(powers + [powers[-1]], index=pd.DatetimeIndex(idx))
    hourly = resample_to_hourly_zoh(series)
    assert hourly.loc[start] == pytest.approx(sum(powers) / 4.0)
    # Mean kW over 1 h equals ∫P·dt for that hour (kWh).
    assert float(hourly.loc[start]) == pytest.approx(sum(p * 0.25 for p in powers))


def test_normalize_irregular_pulse_zoh_energy() -> None:
    """Event log: 10 min at 3.5 kW then off → hour mean = 3.5 * 10/60, not 1.75."""
    from data.loxone_csv_timeseries import resample_to_hourly_zoh

    idx = pd.to_datetime(
        ["2023-06-01 12:00:00", "2023-06-01 12:10:00", "2023-06-01 13:00:00"]
    )
    series = pd.Series([3.5, 0.0, 0.0], index=idx)
    hourly = resample_to_hourly_zoh(series)
    assert hourly.loc["2023-06-01 12:00:00"] == pytest.approx(3.5 * 10 / 60)
    assert hourly.loc["2023-06-01 12:00:00"] != pytest.approx(1.75)


def test_normalize_sparse_zoh_holds(tmp_path: Path) -> None:
    """Sparse samples: gaps hold last value (ZOH), not linear midpoints."""
    path = tmp_path / "sparse.csv"
    start = datetime(2023, 1, 1)
    lines = ["timestamp;power_kw"]
    # every 2 hours for a full year+ → ZOH fills intervening hours at 2.0
    for i in range((MIN_HOURS_FULL_YEAR // 2) + 2):
        ts = start + timedelta(hours=2 * i)
        lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')};2.0")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = load_and_normalize_profile_csv(str(path))
    assert len(rows) >= MIN_HOURS_FULL_YEAR
    assert rows[0][1] == pytest.approx(2.0)
    assert rows[1][1] == pytest.approx(2.0)


def test_resample_sparse_gap_holds_constant() -> None:
    from data.loxone_csv_timeseries import resample_to_hourly_zoh

    idx = pd.to_datetime(["2023-01-01 00:00:00", "2023-01-01 03:00:00"])
    series = pd.Series([4.0, 4.0], index=idx)
    hourly = resample_to_hourly_zoh(series)
    assert hourly.loc["2023-01-01 00:00:00"] == pytest.approx(4.0)
    assert hourly.loc["2023-01-01 01:00:00"] == pytest.approx(4.0)
    assert hourly.loc["2023-01-01 02:00:00"] == pytest.approx(4.0)


def test_normalize_sign_flip(tmp_path: Path) -> None:
    path = tmp_path / "neg.csv"
    _write_canonical_hours(path, MIN_HOURS_FULL_YEAR, power_kw=-3.0)
    rows = load_and_normalize_profile_csv(str(path))
    assert rows[0][1] == pytest.approx(3.0)


def test_normalize_watt_to_kw(tmp_path: Path) -> None:
    path = tmp_path / "watt.csv"
    _write_canonical_hours(path, MIN_HOURS_FULL_YEAR, power_kw=1500.0)
    rows = load_and_normalize_profile_csv(str(path))
    assert rows[0][1] == pytest.approx(1.5)


def test_normalize_too_short_raises(tmp_path: Path) -> None:
    path = tmp_path / "short.csv"
    _write_canonical_hours(path, 100)
    with pytest.raises(ValueError, match="8760"):
        load_and_normalize_profile_csv(str(path))


def test_loxone_style_import(tmp_path: Path) -> None:
    path = tmp_path / "lox.csv"
    start = datetime(2023, 1, 1)
    lines = ["Datum;Zeit;Wert;Leistung"]
    for i in range(MIN_HOURS_FULL_YEAR):
        ts = start + timedelta(hours=i)
        lines.append(
            f"{ts.strftime('%d.%m.%Y')};{ts.strftime('%H:%M:%S')};0;2,5"
        )
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    rows = load_and_normalize_profile_csv(str(path))
    assert len(rows) >= MIN_HOURS_FULL_YEAR
    assert rows[0][1] == pytest.approx(2.5)


def test_loxone_three_col_digital_import(tmp_path: Path) -> None:
    path = tmp_path / "lox_digital.csv"
    start = datetime(2023, 1, 1)
    lines = ["Datum;Zeit;Wert"]
    for i in range(MIN_HOURS_FULL_YEAR):
        ts = start + timedelta(hours=i)
        value = "1" if i % 2 == 0 else "0"
        lines.append(
            f"{ts.strftime('%d.%m.%Y')};{ts.strftime('%H:%M:%S')};{value}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    rows = load_and_normalize_profile_csv(str(path))
    assert len(rows) >= MIN_HOURS_FULL_YEAR
    assert rows[0][1] == pytest.approx(1.0)
    assert rows[1][1] == pytest.approx(0.0)


def test_loxone_prefers_leistung_over_wert(tmp_path: Path) -> None:
    path = tmp_path / "lox_leistung.csv"
    start = datetime(2023, 1, 1)
    lines = ["Datum;Zeit;Wert;Leistung"]
    for i in range(MIN_HOURS_FULL_YEAR):
        ts = start + timedelta(hours=i)
        lines.append(
            f"{ts.strftime('%d.%m.%Y')};{ts.strftime('%H:%M:%S')};9;1,5"
        )
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    rows = load_and_normalize_profile_csv(str(path))
    assert rows[0][1] == pytest.approx(1.5)


def test_loxone_combined_timestamp_import(tmp_path: Path) -> None:
    path = tmp_path / "lox_combined.csv"
    start = datetime(2023, 1, 1)
    lines = ["Datum/Uhrzeit;Wert"]
    for i in range(MIN_HOURS_FULL_YEAR):
        ts = start + timedelta(hours=i)
        lines.append(f"{ts.strftime('%d.%m.%Y %H:%M:%S')};3,0")
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    rows = load_and_normalize_profile_csv(str(path))
    assert len(rows) >= MIN_HOURS_FULL_YEAR
    assert rows[0][1] == pytest.approx(3.0)


def test_consumer_uses_profile_csv_requires_flag() -> None:
    assert not consumer_uses_profile_csv({"profile_csv": "a.csv"})
    assert not consumer_uses_profile_csv({"profile_csv": "", "use_profile_csv": True})
    assert consumer_uses_profile_csv({"profile_csv": "a.csv", "use_profile_csv": True})
    assert not consumer_uses_profile_csv({"profile_csv": "a.csv", "use_profile_csv": False})


def test_serialize_consumer_keeps_use_profile_csv_false() -> None:
    from house_config.profiles_store import _serialize_consumer

    for consumer_type, extra in (
        ("generic", {"annual_kwh": 100.0, "schedule": None}),
        (
            "ev",
            {
                "min_power_kw": 1.0,
                "min_on_quarterhours": 4,
                "battery_capacity_kwh": 40.0,
                "charging_schedule": {
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
                    "target_soc_percent": 100.0,
                    "charging_efficiency": 0.95,
                },
            },
        ),
        ("thermal_annual", {"thermal": {"living_area_m2": 100.0}}),
        ("thermal_rc", {"thermal_rc": {"water_volume_liters": 1000.0}}),
    ):
        consumer = {
            "id": f"c_{consumer_type}",
            "label": consumer_type,
            "type": consumer_type,
            "nominal_power_kw": 1.0,
            "profile_csv": "config/uploads/x.csv",
            "use_profile_csv": False,
            **extra,
        }
        out = _serialize_consumer(consumer)
        assert "use_profile_csv" in out
        assert out["use_profile_csv"] is False
        consumer["use_profile_csv"] = True
        assert _serialize_consumer(consumer)["use_profile_csv"] is True


def test_estimate_annual_kwh_from_profile_csv_calendar_year(tmp_path: Path) -> None:
    from house_config.consumption_csv import estimate_annual_kwh_from_profile_csv

    path = tmp_path / "sparse.csv"
    rows = []
    # Sparse 2024: 10 hours at 2 kW → 20 kWh
    for i in range(10):
        rows.append((f"2024-01-01 {i:02d}:00:00", 2.0))
    # Sparse 2025: 5 hours at 2 kW → 10 kWh (fewer samples)
    for i in range(5):
        rows.append((f"2025-06-01 {i:02d}:00:00", 2.0))
    write_canonical_hourly_csv(str(path), rows)
    # Prefer year with most samples (2024), missing hours count as 0.
    assert estimate_annual_kwh_from_profile_csv(str(path)) == pytest.approx(20.0)

def test_normalize_hourly_power_kw_direct() -> None:
    idx = pd.date_range("2023-01-01", periods=MIN_HOURS_FULL_YEAR, freq="h")
    series = pd.Series([1.0] * MIN_HOURS_FULL_YEAR, index=idx)
    rows = normalize_hourly_power_kw(series, min_hours=MIN_HOURS_FULL_YEAR)
    assert len(rows) == MIN_HOURS_FULL_YEAR


def test_is_digital_on_off_series_true() -> None:
    idx = pd.date_range("2023-01-01", periods=100, freq="h")
    values = [0.0 if i % 3 else 1.0 for i in range(100)]
    assert is_digital_on_off_series(pd.Series(values, index=idx))


def test_is_digital_on_off_series_false() -> None:
    idx = pd.date_range("2023-01-01", periods=100, freq="h")
    values = [0.5 + (i % 5) * 0.1 for i in range(100)]
    assert not is_digital_on_off_series(pd.Series(values, index=idx))


def test_normalize_digital_scale_by_nominal(tmp_path: Path) -> None:
    path = tmp_path / "digital.csv"
    start = datetime(2023, 1, 1)
    rows = [
        (
            (start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"),
            1.0 if i % 2 == 0 else 0.0,
        )
        for i in range(MIN_HOURS_FULL_YEAR)
    ]
    write_canonical_hourly_csv(str(path), rows)
    assert profile_csv_looks_digital(str(path))
    out = load_and_normalize_profile_csv(str(path), digital_scale_kw=3.5)
    assert out[0][1] == pytest.approx(3.5)
    assert out[1][1] == pytest.approx(0.0)


def test_normalize_digital_scale_rejects_non_digital(tmp_path: Path) -> None:
    path = tmp_path / "analog.csv"
    _write_canonical_hours(path, MIN_HOURS_FULL_YEAR, power_kw=2.0)
    with pytest.raises(ValueError, match="kein digitales"):
        load_and_normalize_profile_csv(str(path), digital_scale_kw=3.5)


def test_normalize_without_digital_scale_leaves_house_path(tmp_path: Path) -> None:
    path = tmp_path / "house.csv"
    _write_canonical_hours(path, MIN_HOURS_FULL_YEAR, power_kw=2.0)
    rows = load_and_normalize_profile_csv(str(path))
    assert rows[0][1] == pytest.approx(2.0)


def test_normalize_profile_csv_file_rewrites_scaled(tmp_path: Path) -> None:
    path = tmp_path / "dig_file.csv"
    start = datetime(2023, 1, 1)
    rows = [
        ((start + timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"), 1.0)
        for i in range(MIN_HOURS_FULL_YEAR)
    ]
    write_canonical_hourly_csv(str(path), rows)
    normalize_profile_csv_file(str(path), digital_scale_kw=2.0)
    loaded = load_hourly_profile_csv(str(path))
    assert loaded[0][1] == pytest.approx(2.0)
    assert not profile_csv_looks_digital(str(path))